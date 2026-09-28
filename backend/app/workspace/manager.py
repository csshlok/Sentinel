"""Create, seal, preview, apply back and clean up Sentinel-owned AppContainer workspaces.

A workspace is a ``git clone --no-hardlinks`` of the user's repository inside
the AppContainer profile's own storage folder
(``%LOCALAPPDATA%\\Packages\\<profile>\\AC\\ws``). The agent only ever writes
there. Sentinel's host-side Git runs exclusively through
``backend.app.git.safe_exec.run_git`` and every workspace call names
``--git-dir``/``--work-tree`` explicitly, because everything under the
workspace (including ``ws\\.git``) is agent-controlled input.

Changes reach the user repository only through apply-back: seal (a commit in
the workspace with ``RECOVERY_IDENTITY``) -> preview (approval token bound to
``(base_sha, sealed_sha)``) -> apply: read-only branch/HEAD checks, ``fetch
--no-tags <ws> HEAD:refs/sentinel/changes/<change_id>``, fetched ref ==
sealed commit, ``merge-base --is-ancestor``, ``merge --ff-only``. Never a
force, a reset or a non-fast-forward merge of the user's branch.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from backend.app.contracts.models import WorkspaceState, utc_now
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.execution._process import CapturedProcess
from backend.app.execution.appcontainer import (
    delete_profile,
    ensure_profile,
    local_appdata_known_folder,
    profile_exists,
    remove_tree_no_follow,
    validate_profile_name,
)
from backend.app.git.safe_exec import RECOVERY_IDENTITY, GitIdentity, run_git
from backend.app.workspace.errors import (
    workspace_apply_failed,
    workspace_approval_invalid,
    workspace_base_mismatch,
    workspace_busy,
    workspace_cleanup_failed,
    workspace_cleanup_pending,
    workspace_clone_failed,
    workspace_git_tampered,
    workspace_not_found,
    workspace_seal_failed,
    workspace_source_alternates,
    workspace_source_detached,
    workspace_source_dirty,
    workspace_source_mismatch,
    workspace_state_conflict,
)
from backend.app.workspace.models import ApplyPreview, ApplyRefusal, WorkspaceRecord
from backend.app.workspace.repository import WorkspaceRepository

LOGGER = logging.getLogger(__name__)

_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_STDERR_KEEP = 4096
_WORKSPACE_DIRECTORY = "ws"
_CONTAINER_SUBDIRECTORIES = ("ws", "home", "tools", "Temp")
PROFILE_DISPLAY_NAME = "Sentinel workspace"

UNTRACKED_SOURCE_LIMITATION = (
    "Untracked files in the source repository are not present in the workspace.")
NO_BASELINE_LIMITATION = (
    "No BASELINE checkpoint existed when the workspace was created; evidence comparisons "
    "may not describe the workspace base.")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _text(result: CapturedProcess) -> str:
    return result.stdout.decode("utf-8", errors="replace").strip()


def _same_path(left: str | Path, right: str | Path) -> bool:
    return (os.path.normcase(os.path.realpath(left))
            == os.path.normcase(os.path.realpath(right)))


def _reparse_attributes(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(info.st_mode)


def _is_reparse(path: str | Path) -> bool:
    """Whether ``path`` itself is a junction, symbolic link or other reparse point."""

    return _reparse_attributes(os.lstat(path))


def _reparse_point_below(root: Path) -> bool:
    """Whether any entry below ``root`` is a reparse point (never follows one)."""

    pending = [os.fspath(root)]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if _reparse_attributes(info):
                    return True
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
    return False


class WorkspaceManager:
    """Owns the lifecycle of per-Change workspace clones and their AppContainer profiles."""

    def __init__(
        self, database: Database, *, profile_prefix: str = "sentinel.w.",
        git_timeout: float = 300.0, clock: Callable[[], datetime] = utc_now,
        baseline_head: Callable[[UUID], str | None] | None = None,
        credential_purger: Callable[[Path], bool] | None = None,
    ) -> None:
        validate_profile_name(profile_prefix + "0" * 32)
        self.repository = WorkspaceRepository(database)
        self._prefix = profile_prefix
        self._git_timeout = git_timeout
        self._clock = clock
        self._baseline_head = baseline_head
        self._credential_purger = credential_purger
        # Runs started by THIS process; the sweep treats any other recorded run
        # as interrupted (its Job Object died with the process that owned it).
        self._live_runs: set[str] = set()

    # ------------------------------------------------------------------ queries

    def get(self, workspace_id: UUID) -> WorkspaceRecord:
        record = self.repository.get(workspace_id)
        if record is None:
            raise workspace_not_found(str(workspace_id))
        return record

    def live_for_change(self, change_id: UUID) -> WorkspaceRecord | None:
        return self.repository.live_for_change(change_id)

    # ------------------------------------------------------------------ git helpers

    def _git(
        self, repository: str | Path, args: Sequence[str], *,
        extra_roots: Sequence[str | Path] = (), identity: GitIdentity | None = None,
    ) -> CapturedProcess:
        result = run_git(repository, list(args), timeout=self._git_timeout,
                         extra_roots=extra_roots, identity=identity)
        if result.timed_out or result.incomplete:
            raise AppError("GIT_COMMAND_FAILED", "Git did not complete.", status_code=500)
        return result

    def _ws_git(
        self, record: WorkspaceRecord, args: Sequence[str], *,
        identity: GitIdentity | None = None,
    ) -> CapturedProcess:
        """Git against the workspace with an explicit git dir and work tree.

        A repository-configured worktree or a ``.git`` gitfile can therefore
        never redirect Sentinel's host-side Git to another directory.
        """

        if record.workspace_path is None or record.container_path is None:
            raise workspace_state_conflict(record.state.value, "git")
        workspace = record.workspace_path
        return self._git(
            workspace,
            [f"--git-dir={workspace / '.git'}", f"--work-tree={workspace}", *args],
            extra_roots=[record.container_path], identity=identity,
        )

    def _save(
        self, record: WorkspaceRecord, expected: WorkspaceState, **changes: Any
    ) -> WorkspaceRecord:
        updated = replace(record, updated_at=self._clock(), **changes)
        self.repository.update(updated, expected_state=expected)
        # The run lease column is authoritative; never hand back a stale copy of it.
        return self.repository.get(updated.id) or updated

    # ------------------------------------------------------------------ source checks

    @staticmethod
    def _resolve_source(source_repository: str | Path) -> Path:
        try:
            source = Path(source_repository).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise workspace_clone_failed("the source repository does not exist") from exc
        if not source.is_dir():
            raise workspace_clone_failed("the source repository is not a directory")
        return source

    def _check_source(self, source: Path) -> tuple[str, str, bool]:
        """(branch ref, HEAD sha, has untracked files) of a launchable source.

        Refuses a non-top-level or non-repository source, a detached HEAD
        (D-03 needs a branch to fast-forward), tracked modifications (D-03: the
        workspace only contains committed content) and object alternates (D-04:
        a ``--no-hardlinks`` clone would still depend on the borrowed store).
        Read-only: every command inspects, none writes.
        """

        try:
            top = self._git(source, ["rev-parse", "--show-toplevel"])
            if top.returncode != 0:
                raise workspace_clone_failed("the source is not a Git repository")
            if not _same_path(_text(top), source):
                raise workspace_clone_failed("the source is not the repository top level")
            branch = self._git(source, ["symbolic-ref", "-q", "HEAD"])
            if branch.returncode == 1:
                raise workspace_source_detached()
            if branch.returncode != 0 or not _text(branch).startswith("refs/heads/"):
                raise workspace_clone_failed("the source branch could not be read")
            head = self._git(source, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
            sha = _text(head)
            if head.returncode != 0 or not _SHA.fullmatch(sha):
                raise workspace_clone_failed("the source repository has no commit")
            tracked = self._git(source, ["status", "--porcelain=v1", "--untracked-files=no"])
            if tracked.returncode != 0:
                raise workspace_clone_failed("the source status could not be read")
            if tracked.stdout.strip():
                raise workspace_source_dirty()
            untracked = self._git(
                source, ["status", "--porcelain=v1", "--untracked-files=normal"])
            if untracked.returncode != 0:
                raise workspace_clone_failed("the source status could not be read")
            alternates = self._git(source, ["rev-parse", "--git-path", "objects/info/alternates"])
            if alternates.returncode != 0 or not _text(alternates):
                raise workspace_clone_failed("the source object store could not be read")
            if os.path.lexists(source / _text(alternates)):
                raise workspace_source_alternates()
        except AppError as exc:
            if exc.code.startswith("WORKSPACE_"):
                raise
            raise workspace_clone_failed("the source repository could not be read") from exc
        return _text(branch), sha, bool(untracked.stdout.strip())

    # ------------------------------------------------------------------ create

    def create(self, change_id: UUID, source_repository: str | Path) -> WorkspaceRecord:
        """Clone ``source_repository`` into a new AppContainer profile's storage folder."""

        source = self._resolve_source(source_repository)
        live = self.repository.live_for_change(change_id)
        if live is not None:
            raise workspace_state_conflict(live.state.value, "create")
        base_branch, base_sha, untracked = self._check_source(source)
        return self._create(
            change_id, source, base_branch, base_sha,
            (UNTRACKED_SOURCE_LIMITATION,) if untracked else (),
        )

    def _create(
        self, change_id: UUID, source: Path, base_branch: str, base_sha: str,
        limitations: tuple[str, ...],
    ) -> WorkspaceRecord:
        now = self._clock()
        record = WorkspaceRecord(
            id=uuid4(), change_id=change_id, state=WorkspaceState.CREATING,
            profile_name=self._prefix + uuid4().hex, created_at=now, updated_at=now,
            source_repository=source, base_branch=base_branch, base_sha=base_sha,
            limitations=limitations,
        )
        # Write-ahead: the row names the profile before the profile exists, so a
        # crash between the two is always discoverable by the DB-driven sweep.
        try:
            self.repository.insert(record)
        except sqlite3.IntegrityError as exc:
            raise workspace_state_conflict("LIVE", "create") from exc
        try:
            profile, _created = ensure_profile(record.profile_name, display_name=PROFILE_DISPLAY_NAME)
            container = profile.container_path
            record = self._save(
                record, WorkspaceState.CREATING, package_sid=profile.package_sid,
                container_path=container, workspace_path=container / _WORKSPACE_DIRECTORY,
            )
            clone = self._git(
                source,
                ["clone", "-q", "--no-hardlinks", "--no-checkout", str(source),
                 str(record.workspace_path)],
                extra_roots=[container],
            )
            if clone.returncode != 0:
                raise workspace_clone_failed("git clone failed")
            reset = self._ws_git(record, ["reset", "-q", "--hard", base_sha])
            if reset.returncode != 0:
                raise workspace_clone_failed("the workspace checkout failed")
            head = self._ws_git(record, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
            if head.returncode != 0 or _text(head) != base_sha:
                raise workspace_clone_failed("the workspace HEAD is not the source HEAD")
            return self._save(record, WorkspaceState.CREATING, state=WorkspaceState.READY)
        except Exception as exc:
            try:
                self.cleanup(record.id)
            except Exception:  # the row stays CLEANUP_FAILED for the sweep
                pass
            if isinstance(exc, AppError) and exc.code == "WORKSPACE_CLONE_FAILED":
                raise
            code = exc.code if isinstance(exc, AppError) else type(exc).__name__
            raise workspace_clone_failed(f"workspace creation failed ({code})") from exc

    # ------------------------------------------------------------------ run lease

    def ensure(
        self, change_id: UUID, source_repository: str, *, run_id: UUID,
    ) -> WorkspaceRecord:
        """The Change's workspace, leased to ``run_id`` (created on first use).

        The source preconditions are re-checked on every launch (D-03 applies
        "at launch"). Only one run holds a workspace at a time; the lease is
        a compare-and-set on ``active_run_id`` and is released by
        :meth:`finish_run` (or by the sweep after a crash).
        """

        source = self._resolve_source(source_repository)
        base_branch, base_sha, untracked = self._check_source(source)
        live = self.repository.live_for_change(change_id)
        if live is None:
            limitations: list[str] = []
            if self._baseline_head is not None:
                baseline = self._baseline_head(change_id)
                if baseline is None:
                    limitations.append(NO_BASELINE_LIMITATION)
                elif baseline != base_sha:
                    raise workspace_base_mismatch()
            else:
                limitations.append(NO_BASELINE_LIMITATION)
            if untracked:
                limitations.append(UNTRACKED_SOURCE_LIMITATION)
            try:
                record = self._create(change_id, source, base_branch, base_sha,
                                      tuple(limitations))
            except AppError as exc:
                if exc.code == "WORKSPACE_STATE_CONFLICT":  # a concurrent ensure won
                    raise workspace_busy() from exc
                raise
        else:
            record = live
            if record.state == WorkspaceState.CREATING:
                raise workspace_busy()
            if record.state in (WorkspaceState.APPLIED, WorkspaceState.DISCARDED,
                                WorkspaceState.CLEANUP_FAILED):
                raise workspace_cleanup_pending(record.state.value)
            if record.source_repository is None or not _same_path(
                    record.source_repository, source):
                raise workspace_source_mismatch()
            if record.active_run_id is not None:
                raise workspace_busy()
            changes: dict[str, Any] = {}
            if record.state in (WorkspaceState.SEALED, WorkspaceState.APPLY_REFUSED):
                # A new run changes the content: every earlier approval is void.
                changes.update(state=WorkspaceState.READY, approval_digest=None,
                               approved_base_sha=None, approved_sealed_sha=None,
                               refusal_reason=None)
            if untracked and UNTRACKED_SOURCE_LIMITATION not in record.limitations:
                changes["limitations"] = record.limitations + (UNTRACKED_SOURCE_LIMITATION,)
            if changes:
                record = self._save(record, record.state, **changes)
        if not self.repository.begin_run(record.id, run_id, updated_at=self._clock()):
            raise workspace_busy()
        self._live_runs.add(str(run_id))
        LOGGER.info("workspace %s leased to run %s", record.id, run_id)
        return self.get(record.id)

    def finish_run(
        self, workspace_id: UUID, run_id: UUID, *, facts: Mapping[str, object] | None,
        status: str, limitations: Sequence[str] = (),
    ) -> None:
        """Record the run's outcome and release its lease (idempotent)."""

        key = str(run_id)
        record = self.get(workspace_id)
        if not any(run.get("run_id") == key for run in record.runs):
            entry = {
                "run_id": key,
                "status": status,
                "facts": dict(facts) if facts is not None else None,
                "limitations": list(limitations),
                "finished_at": self._clock().isoformat(),
            }
            self._save(record, record.state, runs=record.runs + (entry,))
        self.repository.end_run(workspace_id, key, updated_at=self._clock())
        self._live_runs.discard(key)
        LOGGER.info("workspace %s released by run %s (%s)", workspace_id, run_id, status)

    # ------------------------------------------------------------------ .git validation

    def _validate_workspace_git(self, record: WorkspaceRecord) -> None:
        """Refuse a workspace whose agent-controlled ``.git`` could steer host-side Git.

        Runs before every host-side Git call on the workspace. It is only
        meaningful while no agent process runs (the run lease plus the
        kill-on-close Job end every agent process before seal/preview/apply).
        """

        if record.workspace_path is None or record.container_path is None:
            raise workspace_state_conflict(record.state.value, "git")
        container = Path(record.container_path)
        workspace = Path(record.workspace_path)
        expected_ws = os.path.join(os.path.realpath(container), _WORKSPACE_DIRECTORY)
        try:
            if (_is_reparse(workspace) or not workspace.is_dir()
                    or not _same_path(workspace.resolve(strict=True), expected_ws)):
                raise workspace_git_tampered("workspace_path")
        except OSError as exc:
            raise workspace_git_tampered("workspace_path") from exc
        git_dir = workspace / ".git"
        try:
            info = os.lstat(git_dir)
        except OSError as exc:
            raise workspace_git_tampered("git_dir_type") from exc
        if not stat.S_ISDIR(info.st_mode) or _is_reparse(git_dir):
            raise workspace_git_tampered("git_dir_type")
        expected_git = os.path.join(expected_ws, ".git")
        if not _same_path(git_dir, expected_git):
            raise workspace_git_tampered("git_dir_location")
        if os.path.lexists(git_dir / "commondir"):
            raise workspace_git_tampered("commondir")
        info_dir = git_dir / "objects" / "info"
        if (os.path.lexists(info_dir / "alternates")
                or os.path.lexists(info_dir / "http-alternates")):
            raise workspace_git_tampered("alternates")
        if _reparse_point_below(git_dir):
            raise workspace_git_tampered("git_dir_links")
        worktree = self._ws_git(record, ["config", "--get", "core.worktree"])
        if worktree.returncode != 1:
            raise workspace_git_tampered("core_worktree")
        absolute = self._ws_git(record, ["rev-parse", "--absolute-git-dir"])
        if absolute.returncode != 0 or not _same_path(_text(absolute), expected_git):
            raise workspace_git_tampered("absolute_git_dir")

    # ------------------------------------------------------------------ seal + preview

    def _live(self, change_id: UUID) -> WorkspaceRecord:
        record = self.repository.live_for_change(change_id)
        if record is None:
            raise workspace_not_found(str(change_id))
        return record

    def preview(self, change_id: UUID) -> ApplyPreview:
        """Seal the workspace and describe what apply-back would land (no user-repo I/O)."""

        record = self._live(change_id)
        if record.state not in (WorkspaceState.READY, WorkspaceState.SEALED):
            raise workspace_state_conflict(record.state.value, "preview")
        if record.active_run_id is not None:
            raise workspace_state_conflict(record.state.value, "preview")
        base = record.base_sha or ""
        self._validate_workspace_git(record)
        try:
            if self._ws_git(record, ["add", "-A"]).returncode != 0:
                raise workspace_seal_failed("git add failed")
            staged = self._ws_git(record, ["diff", "--cached", "--quiet", "--no-ext-diff"])
            if staged.returncode not in (0, 1):
                raise workspace_seal_failed("the staged changes could not be read")
            if staged.returncode == 1:
                commit = self._ws_git(
                    record,
                    ["commit", "-q", "--no-verify", "-m",
                     f"Sentinel workspace seal for change {change_id}"],
                    identity=RECOVERY_IDENTITY,
                )
                if commit.returncode != 0:
                    raise workspace_seal_failed("git commit failed")
            head = self._ws_git(record, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
            sealed = _text(head)
            if head.returncode != 0 or not _SHA.fullmatch(sealed):
                raise workspace_seal_failed("the sealed commit could not be read")
            listed = self._ws_git(record, ["rev-list", "--reverse", f"{base}..{sealed}"])
            if listed.returncode != 0:
                raise workspace_seal_failed("the sealed commits could not be listed")
            names = self._ws_git(
                record, ["diff", "--name-status", "--no-renames", "--no-ext-diff", "-z",
                         base, sealed],
            )
            if names.returncode != 0:
                raise workspace_seal_failed("the changed paths could not be listed")
        except AppError as exc:
            if exc.code.startswith("WORKSPACE_"):
                raise
            raise workspace_seal_failed("Git failed while sealing") from exc
        commits = tuple(line for line in _text(listed).splitlines() if line)
        fields = names.stdout.decode("utf-8", errors="replace").split("\0")
        if fields and fields[-1] == "":
            fields.pop()
        changed = tuple(
            (fields[index], fields[index + 1]) for index in range(0, len(fields) - 1, 2)
        )
        token = secrets.token_urlsafe(32)
        record = self._save(
            record, record.state, state=WorkspaceState.SEALED, sealed_sha=sealed,
            approval_digest=_digest(token), approved_base_sha=base,
            approved_sealed_sha=sealed, refusal_reason=None,
        )
        return ApplyPreview(
            change_id=change_id, workspace_id=record.id, base_sha=base, sealed_sha=sealed,
            commits=commits, changed_paths=changed, approval_token=token,
        )

    # ------------------------------------------------------------------ apply

    def _refuse(
        self, record: WorkspaceRecord, reason: ApplyRefusal, detail: str | None = None
    ) -> WorkspaceRecord:
        limitations = record.limitations + ((detail,) if detail else ())
        return self._save(
            record, record.state, state=WorkspaceState.APPLY_REFUSED,
            refusal_reason=reason.value, limitations=limitations,
        )

    def apply(self, change_id: UUID, approval_token: str) -> WorkspaceRecord:
        """Fast-forward the user's branch to the approved sealed commit, or refuse."""

        record = self._live(change_id)
        if record.active_run_id is not None:
            raise workspace_state_conflict(record.state.value, "apply")
        # A cleared approval (a newer run or preview voided it) is an invalid
        # approval, whatever state the workspace moved to since.
        if (not isinstance(approval_token, str) or not approval_token
                or not record.approval_digest
                or not hmac.compare_digest(_digest(approval_token), record.approval_digest)):
            raise workspace_approval_invalid()
        if record.state != WorkspaceState.SEALED:
            raise workspace_state_conflict(record.state.value, "apply")
        if (record.approved_base_sha != record.base_sha
                or record.approved_sealed_sha != record.sealed_sha
                or record.sealed_sha is None):
            raise workspace_approval_invalid()
        source = record.source_repository
        if source is None or record.workspace_path is None or record.container_path is None:
            raise workspace_state_conflict(record.state.value, "apply")
        self._validate_workspace_git(record)

        # Read-only checks against the user repository come first.
        try:
            branch = self._git(source, ["symbolic-ref", "-q", "HEAD"])
            head = self._git(source, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
        except AppError as exc:
            raise workspace_apply_failed("the user repository could not be read") from exc
        if branch.returncode != 0 or _text(branch) != record.base_branch:
            return self._refuse(record, ApplyRefusal.USER_BRANCH_SWITCHED)
        if head.returncode != 0 or _text(head) != record.base_sha:
            return self._refuse(record, ApplyRefusal.USER_BRANCH_MOVED)

        ref = f"refs/sentinel/changes/{change_id}"
        try:
            self._git(source, ["update-ref", "-d", ref])  # an absent ref is fine
            fetch = self._git(
                source, ["fetch", "--no-tags", str(record.workspace_path), f"HEAD:{ref}"],
                extra_roots=[record.container_path],
            )
            if fetch.returncode != 0:
                raise workspace_apply_failed("fetching the sealed commit failed")
            fetched = self._git(source, ["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"])
            if fetched.returncode != 0 or _text(fetched) != record.sealed_sha:
                return self._refuse(record, ApplyRefusal.SEALED_COMMIT_MISMATCH)
            ancestor = self._git(source, ["merge-base", "--is-ancestor", "HEAD", ref])
            if ancestor.returncode == 1:
                return self._refuse(record, ApplyRefusal.FAST_FORWARD_REFUSED)
            if ancestor.returncode != 0:
                raise workspace_apply_failed("the fast-forward check failed")
            merge = self._git(
                source,
                ["-c", "core.protectNTFS=true", "-c", "core.protectHFS=true",
                 "merge", "--ff-only", "-q", ref],
            )
            if merge.returncode != 0:
                detail = merge.stderr[:_STDERR_KEEP].decode("utf-8", errors="replace").strip()
                return self._refuse(
                    record, ApplyRefusal.FAST_FORWARD_REFUSED,
                    f"git merge --ff-only refused: {detail}" if detail else None,
                )
            after = self._git(source, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
            if after.returncode != 0 or _text(after) != record.sealed_sha:
                raise workspace_apply_failed("the user HEAD is not the sealed commit after merge")
            record = self._save(
                record, WorkspaceState.SEALED, state=WorkspaceState.APPLIED,
                applied_sha=_text(after), refusal_reason=None,
            )
        except AppError as exc:
            if exc.code.startswith("WORKSPACE_"):
                raise
            raise workspace_apply_failed("Git failed during apply-back") from exc
        finally:
            try:
                self._git(source, ["update-ref", "-d", ref])
            except AppError:
                pass
        try:
            return self.cleanup(record.id)
        except AppError:
            return self.get(record.id)  # CLEANUP_FAILED stays visible for the sweep

    # ------------------------------------------------------------------ cleanup

    def _remove_profile_storage(self, record: WorkspaceRecord, problems: list[str]) -> bool:
        """Delete workspace files, the profile and its folder; True when both are gone."""

        packages = local_appdata_known_folder() / "Packages" / record.profile_name
        container = record.container_path or packages / "AC"
        if not _same_path(container.parent, packages):
            problems.append("the recorded container folder is not the profile's folder")
            return False
        for name in _CONTAINER_SUBDIRECTORIES:
            target = container / name
            if os.path.lexists(target):
                try:
                    remove_tree_no_follow(target)
                except OSError as exc:
                    problems.append(f"could not remove {name} ({type(exc).__name__})")
        try:
            delete_profile(record.profile_name)
        except AppError as exc:
            problems.append(f"profile delete failed ({exc.details.get('hresult')})")
        if os.path.lexists(packages):
            try:
                remove_tree_no_follow(packages)
            except OSError as exc:
                problems.append(f"could not remove the profile folder ({type(exc).__name__})")
        return not os.path.lexists(packages) and not profile_exists(record.profile_name)

    def cleanup(self, workspace_id: UUID) -> WorkspaceRecord:
        """Remove the workspace, the profile folder and the AppContainer profile.

        Idempotent for CLEANED. Any failure records CLEANUP_FAILED (visible to the
        DB-driven sweep) and raises ``WORKSPACE_CLEANUP_FAILED``.
        """

        record = self.get(workspace_id)
        if record.state == WorkspaceState.CLEANED:
            return record
        if record.active_run_id is not None:
            raise workspace_state_conflict(record.state.value, "cleanup")
        problems: list[str] = []
        try:
            removed = self._remove_profile_storage(record, problems)
        except Exception as exc:  # any failure must end CLEANUP_FAILED, never silent
            code = exc.code if isinstance(exc, AppError) else type(exc).__name__
            problems.append(f"cleanup could not run ({code})")
            removed = False
        if removed and not problems:
            return self._save(
                record, record.state, state=WorkspaceState.CLEANED, cleaned_at=self._clock(),
            )
        if not problems:
            problems.append("the profile folder or mapping still exists")
        self._save(
            record, record.state, state=WorkspaceState.CLEANUP_FAILED,
            limitations=record.limitations + tuple(problems),
        )
        raise workspace_cleanup_failed("; ".join(problems))
