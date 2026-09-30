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

Before any host-side Git touches the workspace, ``_validate_workspace_git``
refuses a tampered ``ws\\.git`` (gitfile, junction, ``commondir``, alternates,
reparse points, ``core.worktree``) and any junction in the work tree (Git for
Windows descends into junctions). Those checks hold only while no agent
process runs, which the single-run lease and the kill-on-close Job ensure.
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
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from backend.app.contracts.models import JournalEventType, WorkspaceState, utc_now
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.execution._process import CapturedProcess
from backend.app.execution.agent_ports import (
    CredentialFingerprint,
    contains_credential_material,
)
from backend.app.execution.appcontainer import (
    delete_profile,
    ensure_profile,
    local_appdata_known_folder,
    profile_exists,
    remove_tree_no_follow,
    validate_profile_name,
)
from backend.app.git.safe_exec import METADATA_LIMIT, RECOVERY_IDENTITY, GitIdentity, run_git
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
from backend.app.workspace.models import (
    CREDENTIAL_FLAG,
    PREVIEW_COMMIT_LIMIT,
    PREVIEW_PATCH_LIMIT,
    SECRET_SCAN_LIMIT,
    ApplyPreview,
    ApplyRefusal,
    SweepReport,
    WorkspaceRecord,
    path_flags,
)
from backend.app.workspace.repository import WorkspaceRepository

LOGGER = logging.getLogger(__name__)

_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_STDERR_KEEP = 4096
_WORKSPACE_DIRECTORY = "ws"
_CONTAINER_SUBDIRECTORIES = ("ws", "home", "tools", "Temp")
_REMOVE_ATTEMPTS = 5
_REMOVE_BACKOFF_SECONDS = 0.2
_TRANSIENT_WINERRORS = frozenset({5, 32})  # access denied, sharing violation
PROFILE_DISPLAY_NAME = "Sentinel workspace"

UNTRACKED_SOURCE_LIMITATION = (
    "Untracked files in the source repository are not present in the workspace.")
NO_BASELINE_LIMITATION = (
    "No BASELINE checkpoint existed when the workspace was created; evidence comparisons "
    "may not describe the workspace base.")
PREVIEW_LIMITATIONS: tuple[str, ...] = (
    "The repository's own Git hooks (for example post-merge) do not run during apply-back.",
    "Git filters, including Git LFS, are neutralized; content is applied exactly as stored "
    "in the sealed commit.",
    "Submodules were not cloned into the workspace.",
    "Only files committed at the base commit were present in the workspace; uncommitted, "
    "untracked and ignored files (for example node_modules or .env) were absent.",
)
CREDENTIAL_DETECTION_LIMITATION = (
    "Credential detection covers verbatim, base64 and hex copies of the staged credential only.")
CREDENTIAL_IN_DIFF_LIMITATION = (
    "Sentinel found the staged model credential in the workspace changes; apply-back is "
    "refused. Detection covers verbatim, base64 and hex copies only.")
DIFF_TOO_LARGE_TO_SCAN_LIMITATION = (
    "The workspace changes are larger than Sentinel scans for the staged model credential "
    f"({SECRET_SCAN_LIMIT // 1_048_576} MiB); apply-back is refused rather than applied unscanned.")


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


def _followable_link_in_worktree(workspace: Path) -> bool:
    """Whether the work tree holds a junction or any non-symlink reparse point.

    Measured on Git for Windows 2.50: ``git add -A`` records a true symbolic
    link (``IO_REPARSE_TAG_SYMLINK``) as a ``120000`` link without reading
    its target, but it DESCENDS into a junction (mount point) and commits the
    files behind it. Host-side seal runs at the user's full authority, so a
    junction would let the workspace pull files the agent itself cannot read
    into the sealed commit (and into the agent-readable object store). Every
    reparse point other than a true symbolic link is therefore refused.
    ``.git`` is excluded here; it has its own, stricter check.
    """

    pending = [os.fspath(workspace)]
    top = True
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if top and os.path.normcase(entry.name) == ".git":
                    continue
                info = entry.stat(follow_symlinks=False)
                if _reparse_attributes(info):
                    tag = getattr(os.lstat(entry.path), "st_reparse_tag", 0)
                    if tag != stat.IO_REPARSE_TAG_SYMLINK:
                        return True
                    continue  # recorded as a link by Git, never followed
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
        top = False
    return False


_C_ESCAPES = {ord("a"): 7, ord("b"): 8, ord("t"): 9, ord("n"): 10, ord("v"): 11,
              ord("f"): 12, ord("r"): 13, ord('"'): 34, ord("\\"): 92}
_DIFF_HEADER = b"diff --git "


def _unquote_c(data: bytes) -> tuple[bytes, int] | None:
    """(value, index after the closing quote) of a Git C-quoted string at ``data[0]``."""

    if not data.startswith(b'"'):
        return None
    out = bytearray()
    index = 1
    while index < len(data):
        byte = data[index]
        if byte == ord('"'):
            return bytes(out), index + 1
        if byte == ord("\\") and index + 1 < len(data):
            following = data[index + 1]
            if following in _C_ESCAPES:
                out.append(_C_ESCAPES[following])
                index += 2
                continue
            octal = data[index + 1:index + 4]
            if len(octal) == 3 and all(ord("0") <= item <= ord("7") for item in octal):
                out.append(int(octal, 8) & 0xFF)
                index += 4
                continue
            return None
        out.append(byte)
        index += 1
    return None


def _header_path(line: bytes) -> str | None:
    """The path named by a ``diff --git a/P b/P`` header (renames are disabled), or None."""

    rest = line[len(_DIFF_HEADER):].rstrip(b"\r")
    if rest.startswith(b'"'):
        parsed = _unquote_c(rest)
        if parsed is None or not parsed[0].startswith(b"a/"):
            return None
        return parsed[0][2:].decode("utf-8", errors="replace")
    if len(rest) < 5 or (len(rest) - 5) % 2:
        return None
    size = (len(rest) - 5) // 2
    path = rest[2:2 + size]
    if rest[:2] != b"a/" or rest[2 + size:5 + size] != b" b/" or rest[5 + size:] != path:
        return None
    return path.decode("utf-8", errors="replace")


def _patch_additions(patch: bytes) -> list[tuple[str | None, bytes]]:
    """(path, scannable bytes) per file section of a ``git diff -a`` patch.

    The scannable bytes of a section are its header lines (a path can carry
    material too) and its added hunk lines; removed and context lines came from
    the base commit and are skipped. Text before the first header is kept with
    path None.
    """

    sections: list[tuple[str | None, list[bytes]]] = [(None, [])]
    in_hunk = False
    for line in patch.split(b"\n"):
        if line.startswith(_DIFF_HEADER):
            sections.append((_header_path(line), [line]))
            in_hunk = False
            continue
        lines = sections[-1][1]
        if len(sections) == 1:
            lines.append(line)
        elif line.startswith(b"@@"):
            in_hunk = True
        elif not in_hunk:
            lines.append(line)
        elif line.startswith(b"+"):
            lines.append(line[1:])
    return [(path, b"\n".join(lines)) for path, lines in sections if lines]


class WorkspaceManager:
    """Owns the lifecycle of per-Change workspace clones and their AppContainer profiles."""

    def __init__(
        self, database: Database, *, profile_prefix: str = "sentinel.w.",
        git_timeout: float = 300.0, clock: Callable[[], datetime] = utc_now,
        baseline_head: Callable[[UUID], str | None] | None = None,
        credential_purger: Callable[[Path], bool] | None = None,
        journal: JournalWriter | None = None,
    ) -> None:
        validate_profile_name(profile_prefix + "0" * 32)
        self.repository = WorkspaceRepository(database)
        self._prefix = profile_prefix
        self._git_timeout = git_timeout
        self._clock = clock
        self._baseline_head = baseline_head
        self._credential_purger = credential_purger
        self._journal = journal
        # Runs started by THIS process; the sweep treats any other recorded run
        # as interrupted (its Job Object died with the process that owned it).
        self._live_runs: set[str] = set()
        # Workspaces this process is creating right now; the sweep never touches them.
        self._creating: set[UUID] = set()

    # ------------------------------------------------------------------ queries

    def get(self, workspace_id: UUID) -> WorkspaceRecord:
        record = self.repository.get(workspace_id)
        if record is None:
            raise workspace_not_found(str(workspace_id))
        return record

    def live_for_change(self, change_id: UUID) -> WorkspaceRecord | None:
        return self.repository.live_for_change(change_id)

    def latest_for_change(self, change_id: UUID) -> WorkspaceRecord | None:
        """The live workspace, else the most recent (possibly CLEANED) one; None if never."""

        return (self.repository.live_for_change(change_id)
                or self.repository.latest_for_change(change_id))

    # ------------------------------------------------------------------ git helpers

    def _git(
        self, repository: str | Path, args: Sequence[str], *,
        extra_roots: Sequence[str | Path] = (), identity: GitIdentity | None = None,
        limit: int = METADATA_LIMIT,
    ) -> CapturedProcess:
        result = run_git(repository, list(args), timeout=self._git_timeout,
                         extra_roots=extra_roots, identity=identity, limit=limit)
        if result.timed_out or result.incomplete:
            raise AppError("GIT_COMMAND_FAILED", "Git did not complete.", status_code=500)
        return result

    def _ws_git(
        self, record: WorkspaceRecord, args: Sequence[str], *,
        identity: GitIdentity | None = None, limit: int = METADATA_LIMIT,
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
            extra_roots=[record.container_path], identity=identity, limit=limit,
        )

    def _save(
        self, record: WorkspaceRecord, expected: WorkspaceState, *,
        event: JournalEventType | None = None, payload: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> WorkspaceRecord:
        """Persist ``record`` with ``changes`` (compare-and-set on ``expected``).

        With ``event`` (and a journal), the row update and the journal event
        commit in ONE transaction: a failed append rolls the transition back.
        The append is skipped, never failed, when the Change row no longer
        exists (the workspace row deliberately outlives its Change, D-08).
        Payloads carry ids, shas and reasons only -- never an approval token,
        patch text or credential material.
        """

        updated = replace(record, updated_at=self._clock(), **changes)
        if event is None or self._journal is None:
            self.repository.update(updated, expected_state=expected)
        else:
            body = {"workspace_id": str(record.id), "profile_name": record.profile_name,
                    **dict(payload or {})}
            with self.repository.database.connection(immediate=True) as connection:
                self.repository.update(updated, expected_state=expected, connection=connection)
                exists = connection.execute(
                    "SELECT 1 FROM changes WHERE id = ?", (str(record.change_id),)
                ).fetchone()
                if exists is not None:
                    self._journal.append(
                        record.change_id, event, subject_type="workspace",
                        subject_id=record.id, payload=body, connection=connection,
                    )
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
        self._creating.add(record.id)
        try:
            return self._build(record, source, base_sha)
        finally:
            self._creating.discard(record.id)

    def _build(self, record: WorkspaceRecord, source: Path, base_sha: str) -> WorkspaceRecord:
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
            self._pin_line_endings(record)
            return self._save(
                record, WorkspaceState.CREATING, state=WorkspaceState.READY,
                event=JournalEventType.WORKSPACE_CREATED,
                payload={"package_sid": record.package_sid, "base_branch": record.base_branch,
                         "base_sha": record.base_sha},
            )
        except Exception as exc:
            try:
                self.cleanup(record.id, reason="create_failed")
            except Exception:  # the row stays CLEANUP_FAILED for the sweep
                pass
            if isinstance(exc, AppError) and exc.code == "WORKSPACE_CLONE_FAILED":
                raise
            code = exc.code if isinstance(exc, AppError) else type(exc).__name__
            raise workspace_clone_failed(f"workspace creation failed ({code})") from exc

    def _pin_line_endings(self, record: WorkspaceRecord) -> None:
        """Record the checkout's line-ending settings in the workspace's own config.

        Sentinel's host Git carries the system ``core.autocrlf``/``core.eol``
        into the checkout, but the agent's Git runs with
        ``GIT_CONFIG_NOSYSTEM=1``; without the same settings it saw every
        CRLF-checked-out file as modified (measured in the live Claude Code run:
        ``git status`` listed untouched files and ``git rm`` would refuse them).
        Only these two content-semantics keys are written, with values Git
        itself reported for this checkout.
        """

        for key in ("core.autocrlf", "core.eol"):
            current = self._ws_git(record, ["config", "--get", key])
            value = _text(current).lower()
            if current.returncode != 0 or not value:
                continue
            if self._ws_git(record, ["config", "--local", key, value]).returncode != 0:
                raise workspace_clone_failed("the workspace line-ending settings could not be set")

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

    def record_credential(
        self, workspace_id: UUID, fingerprint: CredentialFingerprint,
    ) -> None:
        """Remember a staged credential's digest-only fingerprint (for the diff scan).

        Stored once per distinct file digest; the payload holds Git blob ids and
        SHA-256 digests only, never the credential or its tokens.
        """

        payload = fingerprint.to_payload()
        record = self.get(workspace_id)
        if any(item.get("file_sha256") == payload["file_sha256"]
               for item in record.credential_fingerprints):
            return
        self._save(record, record.state,
                   credential_fingerprints=record.credential_fingerprints + (payload,))

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
        if _followable_link_in_worktree(workspace):
            raise workspace_git_tampered("worktree_links")
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

    def _seal(self, record: WorkspaceRecord, change_id: UUID) -> str:
        """Commit every workspace change (hooks neutralized) and return the sealed sha."""

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
        return sealed

    def _describe(
        self, record: WorkspaceRecord, base: str, sealed: str,
    ) -> tuple[bool, tuple[tuple[str, str, str], ...], bool,
               tuple[tuple[str, str, str, str, tuple[str, ...]], ...], str, bool,
               dict[str, str]]:
        """(diverged, commits, commits truncated, changed paths, patch, patch truncated,
        new blob id per changed path)."""

        ancestor = self._ws_git(record, ["merge-base", "--is-ancestor", base, sealed])
        diverged = ancestor.returncode != 0
        listed = self._ws_git(
            record, ["log", "-z", "--no-color", "--format=%H%x00%an <%ae>%x00%s",
                     f"--max-count={PREVIEW_COMMIT_LIMIT + 1}", f"{base}..{sealed}"],
        )
        if listed.returncode != 0 or listed.truncated:
            raise workspace_seal_failed("the sealed commits could not be listed")
        fields = listed.stdout.decode("utf-8", errors="replace").split("\0")
        if fields and fields[-1] == "":
            fields.pop()
        entries = [tuple(fields[index:index + 3]) for index in range(0, len(fields) - 2, 3)]
        commits = tuple((sha.strip(), author, subject) for sha, author, subject in entries)
        commits_truncated = len(commits) > PREVIEW_COMMIT_LIMIT
        raw = self._ws_git(
            record, ["diff", "--raw", "-z", "--no-abbrev", "--no-renames", "--no-ext-diff",
                     "--no-textconv", base, sealed],
        )
        if raw.returncode != 0 or raw.truncated:
            raise workspace_seal_failed("the changed paths could not be listed")
        items = raw.stdout.decode("utf-8", errors="replace").split("\0")
        changed: list[tuple[str, str, str, str, tuple[str, ...]]] = []
        blobs: dict[str, str] = {}
        index = 0
        while index + 1 < len(items):
            meta, path = items[index], items[index + 1]
            index += 2
            parts = meta.lstrip(":").split()
            if len(parts) != 5:
                raise workspace_seal_failed("the changed paths could not be parsed")
            old_mode, new_mode, _old, new, status = parts
            changed.append((status[:1], path, old_mode, new_mode,
                            path_flags(path, old_mode, new_mode)))
            if new.strip("0"):  # an all-zero id means the path was deleted
                blobs[path] = new.lower()
        patch = self._ws_git(
            record, ["diff", "--no-color", "--no-ext-diff", "--no-textconv", base, sealed],
            limit=PREVIEW_PATCH_LIMIT,
        )
        if patch.returncode != 0:
            raise workspace_seal_failed("the patch could not be produced")
        return (diverged, commits[:PREVIEW_COMMIT_LIMIT], commits_truncated, tuple(changed),
                patch.stdout.decode("utf-8", errors="replace"), patch.truncated, blobs)

    def _scan_for_credentials(
        self, record: WorkspaceRecord, base: str, sealed: str, blobs: Mapping[str, str],
    ) -> tuple[ApplyRefusal | None, frozenset[str]]:
        """(refusal, paths carrying credential material) of the sealed diff.

        Only runs when a credential was staged for this workspace. One bounded
        ``git diff -a`` of ``base..sealed`` is read; a diff too large to read
        completely fails closed (``DIFF_TOO_LARGE_TO_SCAN``). Each changed
        path's new blob id and the added lines of each file's patch section are
        compared, by digest only, against every recorded fingerprint. The
        scanned text is neither logged nor stored.
        """

        fingerprints = [CredentialFingerprint.from_payload(item)
                        for item in record.credential_fingerprints]
        if not fingerprints:
            return None, frozenset()
        flagged: set[str] = {
            path for path, blob in blobs.items()
            if any(contains_credential_material(item, blob_ids=(blob,))
                   for item in fingerprints)
        }
        scan = self._ws_git(
            record,
            ["-c", "core.quotePath=false", "diff", "-a", "--no-color", "--no-ext-diff",
             "--no-textconv", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/",
             base, sealed],
            limit=SECRET_SCAN_LIMIT,
        )
        if scan.truncated:
            return ApplyRefusal.DIFF_TOO_LARGE_TO_SCAN, frozenset(flagged)
        if scan.returncode != 0:
            raise workspace_seal_failed("the changes could not be scanned")
        hit = bool(flagged)
        for path, added in _patch_additions(scan.stdout):
            if any(contains_credential_material(item, text=added) for item in fingerprints):
                hit = True
                if path is not None:
                    flagged.add(path)
        return (ApplyRefusal.CREDENTIAL_IN_DIFF if hit else None), frozenset(flagged)

    def _user_state(self, source: Path) -> tuple[bool, str | None, str | None]:
        """(HEAD detached, branch ref, HEAD sha) of the user repository -- read-only."""

        try:
            branch = self._git(source, ["symbolic-ref", "-q", "HEAD"])
            head = self._git(source, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
        except AppError as exc:
            raise workspace_apply_failed("the user repository could not be read") from exc
        if branch.returncode not in (0, 1):
            raise workspace_apply_failed("the user repository branch could not be read")
        return (branch.returncode == 1,
                _text(branch) if branch.returncode == 0 else None,
                _text(head) if head.returncode == 0 else None)

    @staticmethod
    def _user_refusal(
        record: WorkspaceRecord, detached: bool, branch: str | None, head: str | None,
    ) -> ApplyRefusal | None:
        if detached:
            return ApplyRefusal.USER_HEAD_DETACHED
        if branch != record.base_branch:
            return ApplyRefusal.USER_BRANCH_SWITCHED
        if head != record.base_sha:
            return ApplyRefusal.USER_BRANCH_MOVED
        return None

    def preview(self, change_id: UUID) -> ApplyPreview:
        """Seal the workspace and describe what apply-back would land.

        The user repository is only read (branch and HEAD); nothing is fetched
        into it. An approval token is issued only when apply can succeed, and
        every preview voids the previous token.
        """

        record = self._live(change_id)
        if record.state not in (WorkspaceState.READY, WorkspaceState.SEALED,
                                WorkspaceState.APPLY_REFUSED):
            raise workspace_state_conflict(record.state.value, "preview")
        if record.active_run_id is not None:
            raise workspace_state_conflict(record.state.value, "preview")
        if record.source_repository is None:
            raise workspace_state_conflict(record.state.value, "preview")
        base = record.base_sha or ""
        self._validate_workspace_git(record)
        try:
            sealed = self._seal(record, change_id)
        except AppError as exc:
            if exc.code.startswith("WORKSPACE_"):
                raise
            raise workspace_seal_failed("Git failed while sealing") from exc
        refusal, assessed = self._assess(record, change_id, base, sealed)
        token: str | None = None
        # A new seal (first preview, or content that changed since the last one) is journaled.
        sealed_event = (JournalEventType.WORKSPACE_SEALED
                        if record.state != WorkspaceState.SEALED or record.sealed_sha != sealed
                        else None)
        sealed_payload = {"base_sha": base, "sealed_sha": sealed,
                          "refusal_reason": refusal.value if refusal else None}
        if refusal is None:
            token = secrets.token_urlsafe(32)
            record = self._save(
                record, record.state, state=WorkspaceState.SEALED, sealed_sha=sealed,
                approval_digest=_digest(token), approved_base_sha=base,
                approved_sealed_sha=sealed, refusal_reason=None,
                event=sealed_event, payload=sealed_payload,
            )
        else:
            record = self._save(
                record, record.state, state=WorkspaceState.SEALED, sealed_sha=sealed,
                approval_digest=None, approved_base_sha=None, approved_sealed_sha=None,
                refusal_reason=refusal.value, event=sealed_event, payload=sealed_payload,
            )
        LOGGER.info("workspace %s previewed (refusal=%s)", record.id,
                    refusal.value if refusal else None)
        return replace(assessed, approval_token=token, limitations=tuple(dict.fromkeys(
            record.limitations + assessed.limitations)))

    def _assess(
        self, record: WorkspaceRecord, change_id: UUID, base: str, sealed: str,
    ) -> tuple[ApplyRefusal | None, ApplyPreview]:
        """(refusal, token-less preview) of ``base..sealed``: shared by preview and inspect.

        Read-only: the workspace is described and scanned, the user repository's
        branch and HEAD are read. The caller has already validated ``.git``.
        """

        if record.source_repository is None:
            raise workspace_state_conflict(record.state.value, "preview")
        try:
            diverged, commits, commits_truncated, changed, patch, patch_truncated, blobs = (
                self._describe(record, base, sealed))
            scan_refusal, flagged = self._scan_for_credentials(record, base, sealed, blobs)
        except AppError as exc:
            if exc.code.startswith("WORKSPACE_"):
                raise
            raise workspace_seal_failed("Git failed while sealing") from exc
        extra: list[str] = []
        if record.credential_fingerprints:
            extra.append(CREDENTIAL_DETECTION_LIMITATION)
        if scan_refusal is ApplyRefusal.CREDENTIAL_IN_DIFF:
            extra.append(CREDENTIAL_IN_DIFF_LIMITATION)
        elif scan_refusal is ApplyRefusal.DIFF_TOO_LARGE_TO_SCAN:
            extra.append(DIFF_TOO_LARGE_TO_SCAN_LIMITATION)
        if flagged:
            changed = tuple(
                (status, path, old_mode, new_mode,
                 flags + ((CREDENTIAL_FLAG,) if path in flagged else ()))
                for status, path, old_mode, new_mode, flags in changed)
        detached, user_branch, user_head = self._user_state(record.source_repository)
        # A credential-bearing (or unscannable) diff is refused before anything else:
        # the user can fix a moved branch, but never un-leak a sealed secret.
        refusal = (scan_refusal
                   or (ApplyRefusal.WORKSPACE_HISTORY_DIVERGED if diverged
                       else self._user_refusal(record, detached, user_branch, user_head)))
        return refusal, ApplyPreview(
            change_id=change_id, workspace_id=record.id, base_sha=base, sealed_sha=sealed,
            commits=commits, changed_paths=changed, approval_token=None,
            refusal_reason=refusal.value if refusal else None,
            user_branch=user_branch, user_head=user_head,
            fast_forward_possible=refusal is None,
            patch=patch, patch_truncated=patch_truncated, commits_truncated=commits_truncated,
            limitations=PREVIEW_LIMITATIONS + tuple(extra),
        )

    def inspect(self, change_id: UUID) -> ApplyPreview:
        """A read-only preview of the already-sealed commit: no seal, no commit, no token.

        Used to explain a refused apply. The recorded refusal reason wins over a
        freshly computed one (it is what apply actually decided); the approval
        token is always None and nothing is persisted.
        """

        record = self._live(change_id)
        if record.sealed_sha is None or record.active_run_id is not None:
            raise workspace_state_conflict(record.state.value, "inspect")
        self._validate_workspace_git(record)
        base = record.base_sha or ""
        refusal, assessed = self._assess(record, change_id, base, record.sealed_sha)
        reason = record.refusal_reason or (refusal.value if refusal else None)
        return replace(
            assessed, approval_token=None, refusal_reason=reason,
            fast_forward_possible=reason is None,
            limitations=tuple(dict.fromkeys(record.limitations + assessed.limitations)),
        )

    # ------------------------------------------------------------------ apply

    def _refuse(
        self, record: WorkspaceRecord, reason: ApplyRefusal, detail: str | None = None
    ) -> WorkspaceRecord:
        """Persist an apply refusal; the approval is void (a new preview is required)."""

        limitations = record.limitations + ((detail,) if detail else ())
        LOGGER.info("workspace %s apply refused: %s", record.id, reason.value)
        return self._save(
            record, record.state, state=WorkspaceState.APPLY_REFUSED,
            refusal_reason=reason.value, limitations=limitations, approval_digest=None,
            approved_base_sha=None, approved_sealed_sha=None,
            event=JournalEventType.WORKSPACE_APPLY_REFUSED,
            payload={"reason": reason.value, "base_sha": record.base_sha,
                     "sealed_sha": record.sealed_sha},
        )

    def approval_matches(self, record: WorkspaceRecord, approval_token: object) -> bool:
        """Whether ``approval_token`` is the one issued for ``record`` (constant time, no Git)."""

        return self._token_matches(record, approval_token)

    @staticmethod
    def _token_matches(record: WorkspaceRecord, approval_token: object) -> bool:
        return (isinstance(approval_token, str) and bool(approval_token)
                and bool(record.approval_digest)
                and hmac.compare_digest(_digest(approval_token), record.approval_digest or ""))

    def apply(self, change_id: UUID, approval_token: str) -> WorkspaceRecord:
        """Fast-forward the user's branch to the approved sealed commit, or refuse.

        Idempotent: replaying the approved token after success returns the
        applied record without running Git. Every refusal voids the approval,
        leaves the user's HEAD and working tree as they were and removes the
        private ref; there is never a force, a reset or a merge commit.
        """

        record = (self.repository.live_for_change(change_id)
                  or self.repository.latest_for_change(change_id))
        if record is None:
            raise workspace_not_found(str(change_id))
        if record.applied_sha and record.state in (WorkspaceState.APPLIED,
                                                   WorkspaceState.CLEANED):
            if not self._token_matches(record, approval_token):
                raise workspace_approval_invalid()
            if record.state == WorkspaceState.APPLIED:
                try:
                    return self.cleanup(record.id, reason="applied")
                except AppError:
                    return self.get(record.id)
            return record
        if record.state == WorkspaceState.CLEANED:
            raise workspace_not_found(str(change_id))
        if record.active_run_id is not None:
            raise workspace_state_conflict(record.state.value, "apply")
        # Defense in depth: no token is ever issued for a refused preview, and a
        # record carrying a refusal is never applied whatever token is offered.
        if record.refusal_reason is not None:
            raise workspace_approval_invalid()
        # A cleared approval (a newer run or preview voided it) is an invalid
        # approval, whatever state the workspace moved to since.
        if not self._token_matches(record, approval_token):
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

        # The workspace must still be exactly what was previewed.
        try:
            ws_head = self._ws_git(record, ["rev-parse", "--verify", "-q", "HEAD^{commit}"])
            ws_status = self._ws_git(record, ["status", "--porcelain=v1"])
        except AppError as exc:
            raise workspace_apply_failed("the workspace could not be read") from exc
        if (ws_head.returncode != 0 or _text(ws_head) != record.sealed_sha
                or ws_status.returncode != 0 or ws_status.stdout.strip()):
            return self._refuse(record, ApplyRefusal.SEALED_COMMIT_MISMATCH)

        # Read-only checks against the user repository come before any fetch.
        detached, branch, head = self._user_state(source)
        refusal = self._user_refusal(record, detached, branch, head)
        if refusal is not None:
            return self._refuse(record, refusal)

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
                event=JournalEventType.WORKSPACE_APPLIED,
                payload={"base_sha": record.base_sha, "sealed_sha": record.sealed_sha,
                         "applied_sha": _text(after), "base_branch": record.base_branch},
            )
            LOGGER.info("workspace %s applied as %s", record.id, record.applied_sha)
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
            return self.cleanup(record.id, reason="applied")
        except AppError:
            return self.get(record.id)  # CLEANUP_FAILED stays visible for the sweep

    # ------------------------------------------------------------------ cleanup

    def _remove_with_retries(self, target: Path) -> None:
        """``remove_tree_no_follow`` retried on transient Windows sharing/access errors.

        Handles close late after a Job is terminated (research Pitfall 11), so
        access-denied (5) and sharing-violation (32) errors are retried up to
        ``_REMOVE_ATTEMPTS`` times with a growing delay; anything else raises.
        """

        for attempt in range(1, _REMOVE_ATTEMPTS + 1):
            try:
                remove_tree_no_follow(target)
                return
            except OSError as exc:
                transient = (isinstance(exc, PermissionError)
                             or getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS)
                if not transient or attempt == _REMOVE_ATTEMPTS:
                    raise
                time.sleep(_REMOVE_BACKOFF_SECONDS * attempt)

    def _profile_folder(self, record: WorkspaceRecord) -> tuple[Path, Path]:
        """(``Packages\\<profile>``, its ``AC`` folder), refusing a foreign recorded path."""

        packages = local_appdata_known_folder() / "Packages" / record.profile_name
        container = Path(record.container_path) if record.container_path else packages / "AC"
        if not _same_path(container.parent, packages):
            raise workspace_cleanup_failed(
                "the recorded container folder is not the profile's folder")
        return packages, container

    def _remove_profile_storage(self, record: WorkspaceRecord, problems: list[str]) -> bool:
        """Delete workspace files, the profile and its folder; True when both are gone.

        Every removal is no-follow (an agent-planted junction is unlinked, never
        descended), and the profile is deleted only after the AC children were
        removed, so a failed removal leaves a visible, retryable CLEANUP_FAILED.
        """

        try:
            packages, container = self._profile_folder(record)
        except AppError as exc:
            problems.append(str(exc.details.get("reason")))
            return False
        for name in _CONTAINER_SUBDIRECTORIES:
            target = container / name
            if os.path.lexists(target):
                try:
                    self._remove_with_retries(target)
                except OSError as exc:
                    problems.append(f"could not remove {name} ({type(exc).__name__})")
        if problems:
            return False
        try:
            delete_profile(record.profile_name)
        except AppError as exc:
            problems.append(f"profile delete failed ({exc.details.get('hresult')})")
            return False
        if os.path.lexists(packages):
            try:
                self._remove_with_retries(packages)
            except OSError as exc:
                problems.append(f"could not remove the profile folder ({type(exc).__name__})")
        return not os.path.lexists(packages) and not profile_exists(record.profile_name)

    _CLEANUP_REASONS = {
        WorkspaceState.APPLIED: "applied",
        WorkspaceState.DISCARDED: "discarded",
        WorkspaceState.CREATING: "create_failed",
    }

    def cleanup(self, workspace_id: UUID, *, reason: str | None = None) -> WorkspaceRecord:
        """Remove the workspace, the profile folder and the AppContainer profile.

        Idempotent for CLEANED. Any failure records CLEANUP_FAILED (visible to the
        DB-driven sweep) and raises ``WORKSPACE_CLEANUP_FAILED``. ``reason``
        ("applied", "discarded", "swept", "create_failed") is journaled with
        ``workspace.cleaned``; by default it is derived from the state.
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
            LOGGER.info("workspace %s cleaned (was %s)", record.id, record.state.value)
            return self._save(
                record, record.state, state=WorkspaceState.CLEANED, cleaned_at=self._clock(),
                event=JournalEventType.WORKSPACE_CLEANED,
                payload={"reason": reason or self._CLEANUP_REASONS.get(record.state, "cleanup"),
                         "previous_state": record.state.value,
                         "applied_sha": record.applied_sha},
            )
        if not problems:
            problems.append("the profile folder or mapping still exists")
        LOGGER.warning("workspace %s cleanup failed (was %s)", record.id, record.state.value)
        self._save(
            record, record.state, state=WorkspaceState.CLEANUP_FAILED,
            limitations=tuple(dict.fromkeys(record.limitations + tuple(problems))),
        )
        raise workspace_cleanup_failed("; ".join(problems))

    def discard(self, change_id: UUID) -> WorkspaceRecord:
        """Abandon the Change's unapplied workspace and clean it up.

        READY, SEALED and APPLY_REFUSED become DISCARDED (approval voided) and
        are then cleaned; DISCARDED, APPLIED and CLEANUP_FAILED are cleaned
        again; an already CLEANED workspace is returned as is.
        """

        record = self.repository.live_for_change(change_id)
        if record is None:
            latest = self.repository.latest_for_change(change_id)
            if latest is not None and latest.state == WorkspaceState.CLEANED:
                return latest
            raise workspace_not_found(str(change_id))
        if record.active_run_id is not None or record.state == WorkspaceState.CREATING:
            raise workspace_state_conflict(record.state.value, "discard")
        if record.state in (WorkspaceState.READY, WorkspaceState.SEALED,
                            WorkspaceState.APPLY_REFUSED):
            record = self._save(
                record, record.state, state=WorkspaceState.DISCARDED, approval_digest=None,
                approved_base_sha=None, approved_sealed_sha=None,
            )
            LOGGER.info("workspace %s discarded", record.id)
        return self.cleanup(record.id, reason="discarded")

    # ------------------------------------------------------------------ sweep

    def _purge_home(self, record: WorkspaceRecord) -> str | None:
        """Remove the staged home (credentials) of a preserved workspace; a problem or None."""

        try:
            _packages, container = self._profile_folder(record)
        except AppError as exc:
            return str(exc.details.get("reason"))
        home = container / "home"
        problem: str | None = None
        if self._credential_purger is not None:
            try:
                if not self._credential_purger(home):
                    problem = "the credential purger reported a failure"
            except Exception as exc:
                problem = f"the credential purger failed ({type(exc).__name__})"
        if os.path.lexists(home):
            try:
                self._remove_with_retries(home)
            except OSError as exc:
                problem = f"could not remove the staged home ({type(exc).__name__})"
        return problem

    def sweep(self, *, live_run_ids: Collection[UUID] | None = None) -> SweepReport:
        """Recover every unclean workspace recorded in THIS database (never anything else).

        Driven only by ``repository.list_unclean()``: Packages folders and the
        AppContainer registry are never enumerated, so a sweep can only touch
        profiles its own rows name (research Pitfall 14). Rows whose run is
        live (``live_run_ids``, default: runs started by this process) are
        skipped. CREATING, APPLIED, DISCARDED and CLEANUP_FAILED rows are
        cleaned. READY, SEALED and APPLY_REFUSED rows hold unapplied work and
        are preserved, but their staged home (credentials) is always purged and
        a stale run marker is cleared and disclosed as interrupted.
        """

        live = {str(run) for run in (self._live_runs if live_run_ids is None else live_run_ids)}
        cleaned: list[UUID] = []
        preserved: list[UUID] = []
        failed: list[tuple[UUID, str]] = []
        for record in self.repository.list_unclean():
            if record.active_run_id is not None and record.active_run_id in live:
                LOGGER.info("sweep: workspace %s skipped (run %s is live)",
                            record.id, record.active_run_id)
                continue
            if record.id in self._creating:
                continue
            try:
                interrupted = record.active_run_id
                if interrupted is not None:
                    self.repository.end_run(record.id, interrupted, updated_at=self._clock())
                    record = self.get(record.id)
                    record = self._save(record, record.state, limitations=record.limitations + (
                        f"Run {interrupted} was interrupted before it finished (the backend "
                        "stopped); its process tree was ended by the Job Object.",))
                    LOGGER.warning("sweep: workspace %s run %s was interrupted",
                                   record.id, interrupted)
                if record.state in (WorkspaceState.READY, WorkspaceState.SEALED,
                                    WorkspaceState.APPLY_REFUSED):
                    problem = self._purge_home(record)
                    if problem is not None:
                        LOGGER.warning("sweep: workspace %s home purge failed", record.id)
                        failed.append((record.id, problem))
                    else:
                        LOGGER.info("sweep: workspace %s preserved (%s), staged home purged",
                                    record.id, record.state.value)
                        preserved.append(record.id)
                    continue
                self.cleanup(record.id, reason="swept")
                LOGGER.info("sweep: workspace %s cleaned (was %s)", record.id,
                            record.state.value)
                cleaned.append(record.id)
            except Exception as exc:  # collected, never raised: one row must not stop the rest
                reason = (str(exc.details.get("reason") or exc.code)
                          if isinstance(exc, AppError) else type(exc).__name__)
                LOGGER.warning("sweep: workspace %s failed (%s)", record.id, reason)
                failed.append((record.id, reason))
        return SweepReport(cleaned=tuple(cleaned), preserved=tuple(preserved),
                           failed=tuple(failed))
