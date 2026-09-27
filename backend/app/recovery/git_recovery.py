"""Git-native constrained recovery: implements `backend.app.contracts.ports.RecoveryPort`.

Supported: preview and revert known commits on a dedicated Change
branch, conflict-checked in a temporary worktree before any mutation of
the target repository. Recovery only ever creates new revert commits;
it never resets, rewrites, or checks out the user's actual working
directory. Approval is mandatory and never inferred.

Every Git step runs through `backend.app.git.safe_exec`: hooks, content
filters, diff/merge drivers and execution-bearing configuration from the
(agent-writable) repository are neutralized, temporary worktrees are created
with ``--no-checkout`` and populated by a hardened reset discovered in the
worktree's own context, and recovery commits are authored and committed by
the explicit Sentinel identity (``Sentinel Recovery
<recovery@sentinel.invalid>``), never the user's or the repository's
configured identity.

Unsupported (explicit, never silently claimed): uncommitted/ignored file
changes and environment rollback. A live Change-owned Job Object tree held by
this daemon instance is terminated during approved execution; trees from before
a restart cannot be recovered because their OS handles are no longer owned.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    ChangeView,
    RecoveryAction,
    RecoveryPlan,
    RecoveryStatus,
)
from backend.app.core.database import Database
from backend.app.execution._process import CapturedProcess
from backend.app.git.safe_exec import RECOVERY_IDENTITY, run_git
from backend.app.recovery.checkpoints import get_checkpoint_by_id, get_earliest_checkpoint
from backend.app.recovery.errors import recovery_no_checkpoint_evidence, recovery_not_approved

_UNSUPPORTED_EFFECTS = (
    "Uncommitted or ignored file changes are not restorable; filesystem "
    "tracking is out of scope for this product.",
    "Environment effects are not restorable; environment rollback is out of scope.",
    "Only Change-owned process trees still tracked by this daemon instance can be "
    "terminated; process trees from before a restart cannot be recovered.",
)

# Worktree creation, population and multi-commit reverts can take longer than a
# metadata query on a large repository; still bounded.
RECOVERY_TIMEOUT_SECONDS = 120


def _failed(result: CapturedProcess) -> bool:
    return result.returncode != 0 or result.timed_out or result.incomplete


def _stderr(result: CapturedProcess) -> str:
    return result.stderr.decode("utf-8", errors="replace").strip()


def _default_clock() -> datetime:
    return datetime.now(UTC)


class GitRecoveryEngine:
    """Implements `RecoveryPort`."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] = _default_clock,
        process_tree_terminator: Callable[[UUID], int] | None = None,
    ) -> None:
        self.database = database
        self._clock = clock
        self._process_tree_terminator = process_tree_terminator

    def plan(self, change: ChangeView) -> RecoveryPlan:
        now = self._clock()
        baseline = get_earliest_checkpoint(self.database, change.id)
        if baseline is None:
            raise recovery_no_checkpoint_evidence(str(change.id))

        current_sha = change.git_summary.head_sha if change.git_summary else baseline.head_sha
        actions: list[RecoveryAction] = []
        conflicts: list[str] = []
        unsupported = list(_UNSUPPORTED_EFFECTS)

        if baseline.head_sha == current_sha:
            unsupported.append(
                "The repository is already at the baseline commit; there is nothing to revert."
            )
        else:
            commits = self._commits_between(change.repository_path, baseline.head_sha, current_sha)
            if commits is None:
                unsupported.append(
                    f"Baseline commit {baseline.head_sha} is no longer reachable from HEAD; "
                    "recovery cannot be planned."
                )
            elif not commits:
                unsupported.append(
                    "No committed changes were found between the baseline and current HEAD."
                )
            else:
                branch = self._dedicated_branch_name(change.id)
                preview_branch = f"{branch}-preview-{uuid4().hex[:8]}"
                conflict = self._dry_run_revert(
                    change.repository_path, preview_branch, current_sha, commits
                )
                if conflict:
                    conflicts.append(conflict)
                actions.append(
                    RecoveryAction(
                        id=uuid4(),
                        kind="git.revert_commits",
                        description=(
                            f"Revert {len(commits)} commit(s) from {current_sha} back toward "
                            f"baseline {baseline.head_sha} on dedicated branch '{branch}'."
                        ),
                        supported=conflict is None,
                        reversible_commit=current_sha,
                        limitations=[]
                        if conflict is None
                        else [
                            "A merge conflict was detected in a temporary worktree; "
                            "this action cannot execute until resolved."
                        ],
                    )
                )

        return RecoveryPlan(
            id=uuid4(),
            change_id=change.id,
            status=RecoveryStatus.PLANNED,
            actions=actions,
            unsupported_effects=unsupported,
            conflicts=conflicts,
            source_checkpoint_id=baseline.id,
            created_at=now,
        )

    def execute(
        self, change: ChangeView, plan: RecoveryPlan, approval_token: str
    ) -> RecoveryPlan:
        if not approval_token:
            raise recovery_not_approved()

        now = self._clock()
        processes_terminated = (
            self._process_tree_terminator(change.id)
            if self._process_tree_terminator is not None else 0
        )
        if not plan.actions:
            return plan.model_copy(
                update={
                    "status": RecoveryStatus.RECOVERED,
                    "approved_at": now,
                    "completed_at": now,
                    "processes_terminated": processes_terminated,
                }
            )

        action = plan.actions[0]
        if not action.supported or action.reversible_commit is None:
            return plan.model_copy(
                update={"status": RecoveryStatus.CONFLICTED, "approved_at": now,
                        "processes_terminated": processes_terminated}
            )

        baseline = get_checkpoint_by_id(self.database, plan.source_checkpoint_id)
        if baseline is None:
            raise recovery_no_checkpoint_evidence(str(change.id))

        current_sha = action.reversible_commit
        completed_at_on_failure = self._clock()
        real_head = self._current_head(change.repository_path)
        if real_head is None or real_head.lower() != current_sha.lower():
            # The plan was computed against `current_sha`; if the repository's
            # actual HEAD has since moved, executing against the stale SHA
            # would revert commits relative to a base that no longer reflects
            # reality -- silently "succeeding" while reverting the wrong
            # history. Require a fresh preview instead of proceeding.
            return plan.model_copy(
                update={
                    "status": RecoveryStatus.RECOVERY_FAILED,
                    "approved_at": now,
                    "completed_at": completed_at_on_failure,
                    "conflicts": [
                        *plan.conflicts,
                        "The repository HEAD moved since this plan was previewed; "
                        "re-preview recovery before executing.",
                    ],
                    "processes_terminated": processes_terminated,
                }
            )

        commits = self._commits_between(change.repository_path, baseline.head_sha, current_sha)
        if not commits:
            return plan.model_copy(
                update={
                    "status": RecoveryStatus.RECOVERY_FAILED,
                    "approved_at": now,
                    "completed_at": completed_at_on_failure,
                    "processes_terminated": processes_terminated,
                }
            )

        branch = self._dedicated_branch_name(change.id)
        result_sha, error = self._revert_on_dedicated_branch(
            change.repository_path, branch, current_sha, commits
        )
        completed_at = self._clock()
        if error is not None:
            return plan.model_copy(
                update={
                    "status": RecoveryStatus.CONFLICTED,
                    "approved_at": now,
                    "completed_at": completed_at,
                    "conflicts": [*plan.conflicts, error],
                    "processes_terminated": processes_terminated,
                }
            )

        completed_action = action.model_copy(
            update={"provider_reference": f"branch:{branch}@{result_sha}"}
        )
        return plan.model_copy(
            update={
                "status": RecoveryStatus.RECOVERED,
                "actions": [completed_action],
                "approved_at": now,
                "completed_at": completed_at,
                "processes_terminated": processes_terminated,
            }
        )

    @staticmethod
    def _dedicated_branch_name(change_id: UUID) -> str:
        return f"change-assurance/recovery/{change_id}"

    @staticmethod
    def _current_head(repository_path: str) -> str | None:
        result = run_git(repository_path, ["rev-parse", "HEAD"])
        if _failed(result):
            return None
        return result.stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _commits_between(
        repository_path: str, baseline_sha: str, current_sha: str
    ) -> list[str] | None:
        ancestor_check = run_git(
            repository_path, ["merge-base", "--is-ancestor", baseline_sha, current_sha]
        )
        if _failed(ancestor_check):
            return None
        listed = run_git(repository_path, ["rev-list", "--reverse", f"{baseline_sha}..{current_sha}"])
        if _failed(listed) or listed.truncated:
            return None
        return [
            line
            for line in listed.stdout.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]

    @classmethod
    def _dry_run_revert(
        cls,
        repository_path: str,
        preview_branch: str,
        current_sha: str,
        commits: list[str],
    ) -> str | None:
        """Preview a revert in a throwaway worktree. Never mutates the target repository.

        The worktree is created with ``--no-checkout`` and populated by a
        hardened ``reset --hard`` whose driver discovery runs against the new
        worktree itself, so filters defined only through worktree-conditional
        includes are discovered and neutralized before any content is written.
        """

        del preview_branch  # never created; the worktree stays detached
        repository_root = (Path(repository_path),)
        with tempfile.TemporaryDirectory(prefix="sentinel-recovery-") as temp_dir:
            created = run_git(
                repository_path,
                ["worktree", "add", "--no-checkout", "--detach", temp_dir, current_sha],
                timeout=RECOVERY_TIMEOUT_SECONDS,
            )
            if _failed(created):
                return "Could not create a preview worktree: " + _stderr(created)
            try:
                populated = run_git(
                    temp_dir, ["reset", "--quiet", "--hard", "HEAD"],
                    extra_roots=repository_root, timeout=RECOVERY_TIMEOUT_SECONDS,
                )
                if _failed(populated):
                    return "Could not create a preview worktree: " + _stderr(populated)
                reverted = run_git(
                    temp_dir, ["revert", "--no-commit", *reversed(commits)],
                    extra_roots=repository_root, timeout=RECOVERY_TIMEOUT_SECONDS,
                )
                if _failed(reverted):
                    run_git(temp_dir, ["revert", "--abort"], extra_roots=repository_root)
                    return (
                        "Reverting these commits produced a merge conflict: "
                        + _stderr(reverted)
                    )
                return None
            finally:
                run_git(
                    repository_path, ["worktree", "remove", "--force", temp_dir],
                    timeout=RECOVERY_TIMEOUT_SECONDS,
                )

    @classmethod
    def _revert_on_dedicated_branch(
        cls,
        repository_path: str,
        branch: str,
        current_sha: str,
        commits: list[str],
    ) -> tuple[str | None, str | None]:
        """Create the dedicated branch and commit real revert commits on it.

        Runs entirely inside a temporary worktree so the user's actual
        working directory and index are never touched. The branch and
        its new commits live in the shared repository and persist after
        the temporary worktree is removed. The worktree is created with
        ``--no-checkout`` and populated by a hardened reset discovered in
        its own context; revert commits carry ``RECOVERY_IDENTITY``.
        """

        repository_root = (Path(repository_path),)
        with tempfile.TemporaryDirectory(prefix="sentinel-recovery-") as temp_dir:
            created = run_git(
                repository_path,
                ["worktree", "add", "--no-checkout", "-b", branch, temp_dir, current_sha],
                timeout=RECOVERY_TIMEOUT_SECONDS,
            )
            if _failed(created):
                return None, "Could not create the dedicated recovery branch: " + _stderr(created)

            failure: str | None = None
            result_sha: str | None = None
            try:
                populated = run_git(
                    temp_dir, ["reset", "--quiet", "--hard", "HEAD"],
                    extra_roots=repository_root, timeout=RECOVERY_TIMEOUT_SECONDS,
                )
                if _failed(populated):
                    failure = (
                        "Could not create the dedicated recovery branch: " + _stderr(populated)
                    )
                else:
                    reverted = run_git(
                        temp_dir, ["revert", "--no-edit", *reversed(commits)],
                        identity=RECOVERY_IDENTITY, extra_roots=repository_root,
                        timeout=RECOVERY_TIMEOUT_SECONDS,
                    )
                    if _failed(reverted):
                        run_git(temp_dir, ["revert", "--abort"], extra_roots=repository_root)
                        failure = (
                            "Reverting these commits produced a merge conflict: "
                            + _stderr(reverted)
                        )
                    else:
                        head = run_git(temp_dir, ["rev-parse", "HEAD"], extra_roots=repository_root)
                        if _failed(head):
                            failure = "Could not read the recovery branch head: " + _stderr(head)
                        else:
                            result_sha = head.stdout.decode("utf-8", errors="replace").strip()
            finally:
                run_git(
                    repository_path, ["worktree", "remove", "--force", temp_dir],
                    timeout=RECOVERY_TIMEOUT_SECONDS,
                )
            if failure is not None:
                run_git(repository_path, ["branch", "-D", branch])
                return None, failure
            return result_sha, None
