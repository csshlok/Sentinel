"""Git-native constrained recovery: implements `backend.app.contracts.ports.RecoveryPort`.

Supported: preview and revert known commits on a dedicated Change
branch, conflict-checked in a temporary worktree before any mutation of
the target repository. Recovery only ever creates new revert commits;
it never resets, rewrites, or checks out the user's actual working
directory. Approval is mandatory and never inferred.

Unsupported (explicit, never silently claimed): uncommitted/ignored
file changes, and any environment or process-level effect, since the
filesystem tracker and process supervisor are cut from this product.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    ChangeView,
    RecoveryAction,
    RecoveryPlan,
    RecoveryStatus,
)
from backend.app.core.database import Database
from backend.app.recovery.checkpoints import get_checkpoint_by_id, get_earliest_checkpoint
from backend.app.recovery.errors import recovery_no_checkpoint_evidence, recovery_not_approved

_UNSUPPORTED_EFFECTS = (
    "Uncommitted or ignored file changes are not restorable; filesystem "
    "tracking is out of scope for this product.",
    "Environment and process-level effects are not restorable; the "
    "process supervisor and environment rollback are out of scope for "
    "this product.",
)


def _default_clock() -> datetime:
    return datetime.now(UTC)


class GitRecoveryEngine:
    """Implements `RecoveryPort`."""

    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self.database = database
        self._clock = clock

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
        if not plan.actions:
            return plan.model_copy(
                update={
                    "status": RecoveryStatus.RECOVERED,
                    "approved_at": now,
                    "completed_at": now,
                }
            )

        action = plan.actions[0]
        if not action.supported or action.reversible_commit is None:
            return plan.model_copy(
                update={"status": RecoveryStatus.CONFLICTED, "approved_at": now}
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
                }
            )

        commits = self._commits_between(change.repository_path, baseline.head_sha, current_sha)
        if not commits:
            return plan.model_copy(
                update={
                    "status": RecoveryStatus.RECOVERY_FAILED,
                    "approved_at": now,
                    "completed_at": completed_at_on_failure,
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
            }
        )

    @staticmethod
    def _dedicated_branch_name(change_id: UUID) -> str:
        return f"change-assurance/recovery/{change_id}"

    @staticmethod
    def _current_head(repository_path: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", repository_path, "rev-parse", "HEAD"],
            capture_output=True, shell=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _commits_between(
        repository_path: str, baseline_sha: str, current_sha: str
    ) -> list[str] | None:
        ancestor_check = subprocess.run(
            [
                "git",
                "-C",
                repository_path,
                "merge-base",
                "--is-ancestor",
                baseline_sha,
                current_sha,
            ],
            capture_output=True,
            shell=False,
        )
        if ancestor_check.returncode != 0:
            return None
        listed = subprocess.run(
            [
                "git",
                "-C",
                repository_path,
                "rev-list",
                "--reverse",
                f"{baseline_sha}..{current_sha}",
            ],
            capture_output=True,
            shell=False,
        )
        if listed.returncode != 0:
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
        """Preview a revert in a throwaway worktree. Never mutates the target repository."""

        with tempfile.TemporaryDirectory() as temp_dir:
            created = subprocess.run(
                [
                    "git",
                    "-C",
                    repository_path,
                    "worktree",
                    "add",
                    "--detach",
                    temp_dir,
                    current_sha,
                ],
                capture_output=True,
                shell=False,
            )
            if created.returncode != 0:
                return (
                    "Could not create a preview worktree: "
                    + created.stderr.decode("utf-8", errors="replace").strip()
                )
            try:
                reverted = subprocess.run(
                    ["git", "-C", temp_dir, "revert", "--no-commit", *reversed(commits)],
                    capture_output=True,
                    shell=False,
                )
                if reverted.returncode != 0:
                    subprocess.run(
                        ["git", "-C", temp_dir, "revert", "--abort"],
                        capture_output=True,
                        shell=False,
                    )
                    return (
                        "Reverting these commits produced a merge conflict: "
                        + reverted.stderr.decode("utf-8", errors="replace").strip()
                    )
                return None
            finally:
                subprocess.run(
                    ["git", "-C", repository_path, "worktree", "remove", "--force", temp_dir],
                    capture_output=True,
                    shell=False,
                )
                del preview_branch  # never created; the worktree stayed detached

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
        the temporary worktree is removed.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            created = subprocess.run(
                [
                    "git",
                    "-C",
                    repository_path,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    temp_dir,
                    current_sha,
                ],
                capture_output=True,
                shell=False,
            )
            if created.returncode != 0:
                return None, (
                    "Could not create the dedicated recovery branch: "
                    + created.stderr.decode("utf-8", errors="replace").strip()
                )

            reverted = subprocess.run(
                ["git", "-C", temp_dir, "revert", "--no-edit", *reversed(commits)],
                capture_output=True,
                shell=False,
            )
            failure: str | None = None
            result_sha: str | None = None
            if reverted.returncode != 0:
                subprocess.run(
                    ["git", "-C", temp_dir, "revert", "--abort"],
                    capture_output=True,
                    shell=False,
                )
                failure = (
                    "Reverting these commits produced a merge conflict: "
                    + reverted.stderr.decode("utf-8", errors="replace").strip()
                )
            else:
                head = subprocess.run(
                    ["git", "-C", temp_dir, "rev-parse", "HEAD"],
                    capture_output=True,
                    shell=False,
                )
                result_sha = head.stdout.decode("utf-8", errors="replace").strip()

            subprocess.run(
                ["git", "-C", repository_path, "worktree", "remove", "--force", temp_dir],
                capture_output=True,
                shell=False,
            )
            if failure is not None:
                subprocess.run(
                    ["git", "-C", repository_path, "branch", "-D", branch],
                    capture_output=True,
                    shell=False,
                )
                return None, failure
            return result_sha, None
