"""Disposable confined check boxes: one AppContainer profile per check run.

A box is ``sentinel.check.<run-id>``. Its ``check_runs`` row is written
(CREATING) before the profile exists; the tree copy, the runtime ACEs and the
profile are all removed by ``close()``, and a DB-driven sweep at startup
finishes any row that is not CLEANED. The sweep only ever touches profiles,
folders and runtime entries its own rows name.

The check tree is exactly ``git ls-files -z --cached --others
--exclude-standard`` (listed through ``git/safe_exec.run_git``; deleted paths
are dropped), minus every untracked file the Change's baseline commit's
committed ``.gitignore`` files ignore: the tested tree's ignore rules are part
of the agent's change, so they alone never decide what a box may see (CR-01).
Ignored files never reach a box. A reparse point anywhere on a
listed path, a gitlink or embedded repository, a skip-worktree or
assume-unchanged index entry, or a tree over the size limit is refused before
any row or profile exists. Runs go through ``spawn_appcontainer_supervised``
(token verified before resume) and the bounded ``_process.capture`` loop the
agent launcher uses; each run is journaled as ``check.confined_run`` with ids
and digests only (no argv text, output or host paths).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path, PureWindowsPath
from types import MappingProxyType, TracebackType
from typing import Any
from uuid import UUID, uuid4

from backend.app.contracts.models import JournalEventType, utc_now
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.execution import acl, appcontainer
from backend.app.execution._process import capture
from backend.app.execution.agent_staging import _is_reparse
from backend.app.execution.check_repository import (
    CheckRunRecord,
    CheckRunRepository,
    CheckRunState,
    RuntimeGrant,
)
from backend.app.execution.check_runtime import (
    ManifestEntry,
    PythonRuntime,
    RuntimeSnapshot,
    _long,
    manifest_digest,
)
from backend.app.git.safe_exec import run_git

LOGGER = logging.getLogger(__name__)

DEFAULT_PROFILE_PREFIX = "sentinel.check."
# Box-owned folders under the container folder (removed before the profile is deleted).
CONTAINER_SUBDIRECTORIES = ("tree", "scratch", "Temp")
_REMOVE_ATTEMPTS = 6
_REMOVE_BACKOFF_SECONDS = 0.25
_TRANSIENT_WINERRORS = frozenset({5, 32})
DEFAULT_TREE_SIZE_LIMIT_BYTES = 512 * 1024**2
MAX_CHECK_TIMEOUT_SECONDS = 3600
GIT_LIST_TIMEOUT_SECONDS = 120
GIT_LIST_LIMIT = 8 * 1_048_576
BOUNDARY_APPCONTAINER = "APPCONTAINER"
NETWORK_CAPABILITIES = ("internetClient",)
_GITLINK_MODE = "160000"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
IGNORE_RULES_LIMIT = 1_048_576
BASELINE_CHECKPOINT_NAME = "baseline"
_CHUNK = 1 << 20
# base_environment owns these; a runtime may never override them.
_RESERVED_ENV_KEYS = frozenset({
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "LOCALAPPDATA", "TEMP", "TMP",
})


def check_box_cleanup_failed(reason: str) -> AppError:
    return AppError(
        "CHECK_BOX_CLEANUP_FAILED",
        "The confined check box could not be fully removed; it is recorded for the sweep.",
        status_code=500,
        details={"reason": reason},
    )


def check_tree_refused(code: str, reason: str, path: str | None = None) -> AppError:
    details: dict[str, Any] = {"reason": reason}
    if path is not None:
        details["path"] = path
    return AppError(
        code,
        "Sentinel refuses to build a check tree from this repository state.",
        status_code=409,
        details=details,
    )


def check_box_invalid_argv(reason: str) -> AppError:
    return AppError("CHECK_BOX_INVALID_ARGV", "The confined check command is invalid.",
                    status_code=400, details={"reason": reason})


def check_output_refused(code: str, reason: str) -> AppError:
    return AppError(code, "The check output cannot be read back from the box.",
                    status_code=404 if code == "CHECK_OUTPUT_NOT_FOUND" else 409,
                    details={"reason": reason})


# ---------------------------------------------------------------------- platform seam


@dataclass(frozen=True, slots=True)
class BoxPlatform:
    """The Windows operations a box uses; unit tests substitute fakes."""

    derive_package_sid: Callable[[str], str] = appcontainer.derive_package_sid
    ensure_profile: Callable[..., Any] = appcontainer.ensure_profile
    delete_profile: Callable[[str], None] = appcontainer.delete_profile
    profile_exists: Callable[[str], bool] = appcontainer.profile_exists
    container_folder: Callable[[str], Path] = appcontainer.container_folder
    local_appdata: Callable[[], Path] = appcontainer.local_appdata_known_folder
    base_environment: Callable[..., dict[str, str]] = appcontainer.base_environment
    spawn: Callable[..., Any] = appcontainer.spawn_appcontainer_supervised
    grant: Callable[..., None] = acl.grant_package_read
    revoke: Callable[..., None] = acl.revoke_package_read
    remove_tree: Callable[[str | Path], None] = appcontainer.remove_tree_no_follow


@dataclass(frozen=True, slots=True)
class SweepReport:
    cleaned: tuple[UUID, ...] = ()
    failed: tuple[tuple[UUID, str], ...] = ()


def _same_path(left: str | Path, right: str | Path) -> bool:
    return (os.path.normcase(os.path.abspath(left))
            == os.path.normcase(os.path.abspath(right)))


# ---------------------------------------------------------------------- manager


class CheckBoxes:
    """Opens confined check boxes and owns their persistence, journal and cleanup."""

    def __init__(
        self, database: Database, *, journal: JournalWriter | None = None,
        profile_prefix: str = DEFAULT_PROFILE_PREFIX, runtime_root: str | Path | None = None,
        platform: BoxPlatform | None = None, clock: Callable[[], datetime] = utc_now,
        resolver: Callable[..., Any] | None = None,
    ) -> None:
        appcontainer.validate_profile_name(profile_prefix + "0" * 32)
        self.repository = CheckRunRepository(database)
        # Toolchain -> runtime resolution; snapshots are built under the same
        # cache root this manager grants on (default: check_toolchains).
        self._resolver = resolver
        self._journal = journal
        self._prefix = profile_prefix
        self._runtime_root = None if runtime_root is None else Path(runtime_root)
        self._platform = platform or BoxPlatform()
        self._clock = clock
        # Boxes open in THIS process; the sweep never touches them.
        self._live: set[UUID] = set()

    # ------------------------------------------------------------------ persistence

    def _save(
        self, record: CheckRunRecord, expected: CheckRunState, *,
        event: JournalEventType | None = None, payload: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> CheckRunRecord:
        """Persist ``record`` with ``changes`` (compare-and-set on ``expected``).

        With ``event`` (and a journal) the row update and the journal event
        commit in ONE transaction. The append is skipped, never failed, when the
        Change row no longer exists (the check row outlives its Change).
        """

        updated = replace(record, updated_at=self._clock(), **changes)
        if event is None or self._journal is None:
            return self.repository.update(updated, expected_state=expected)
        with self.repository.database.connection(immediate=True) as connection:
            self.repository.update(updated, expected_state=expected, connection=connection)
            exists = connection.execute(
                "SELECT 1 FROM changes WHERE id = ?", (str(record.change_id),)
            ).fetchone()
            if exists is not None:
                self._journal.append(
                    record.change_id, event, subject_type="check_run", subject_id=record.id,
                    payload=dict(payload or {}), connection=connection,
                )
        return updated

    # ------------------------------------------------------------------ runtimes

    def resolve_runtime(
        self, executable: str, *, interpreter: str | Path | None = None,
        source_root: str | Path | None = None,
    ) -> Any:
        """The confined runtime for ``executable`` (a ``ResolvedCheckRuntime``) or a refusal.

        Snapshots are built in this manager's runtime cache root, the root its
        grants are restricted to.
        """

        if self._resolver is not None:
            return self._resolver(executable, interpreter=interpreter, source_root=source_root)
        from backend.app.execution.check_toolchains import RuntimeBuilders, resolve_check_runtime

        return resolve_check_runtime(
            executable, interpreter=interpreter, source_root=source_root,
            builders=RuntimeBuilders.for_root(self._runtime_root),
        )

    # ------------------------------------------------------------------ unconfined

    @property
    def journaled(self) -> bool:
        """True when runs (including unconfined opt-in runs) can be journaled."""

        return self._journal is not None

    def record_unconfined_run(
        self, change_id: UUID, run_id: UUID, payload: Mapping[str, Any],
    ) -> None:
        """Journal one check run that executed outside any box (``check.unconfined_run``).

        Only the delegated ``checks.unconfined`` path calls this. No box, row or
        profile exists for such a run; the event is its record.
        """

        if self._journal is None:
            raise AppError("CHECK_JOURNAL_UNAVAILABLE",
                           "An unconfined check cannot run without a journal.", status_code=503)
        self._journal.append(change_id, JournalEventType.CHECK_UNCONFINED_RUN,
                             subject_type="check_run", subject_id=run_id, payload=dict(payload))

    # ------------------------------------------------------------------ cleanup

    def _packages_folder(self, record: CheckRunRecord) -> Path:
        return self._platform.local_appdata() / "Packages" / record.profile_name

    def _remove_with_retries(self, target: Path) -> None:
        for attempt in range(1, _REMOVE_ATTEMPTS + 1):
            try:
                self._platform.remove_tree(target)
                return
            except OSError as exc:
                transient = (isinstance(exc, PermissionError)
                             or getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS)
                if not transient or attempt == _REMOVE_ATTEMPTS:
                    raise
                time.sleep(_REMOVE_BACKOFF_SECONDS * attempt)

    def _revoke_grants(self, record: CheckRunRecord, problems: list[str]) -> None:
        for grant in record.runtime_grants:
            if not os.path.lexists(grant.path):
                continue  # the cache entry is gone, so no ACE remains on it
            try:
                self._platform.revoke(grant.path, record.package_sid,
                                      allowed_root=self._runtime_root)
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else type(exc).__name__
                problems.append(f"could not revoke a runtime grant ({code})")

    def _remove_box(self, record: CheckRunRecord, problems: list[str]) -> bool:
        """Revoke ACEs, remove box folders no-follow, delete the profile; True when all gone."""

        self._revoke_grants(record, problems)
        packages = self._packages_folder(record)
        container = packages / "AC"
        for name in CONTAINER_SUBDIRECTORIES:
            target = container / name
            if os.path.lexists(target):
                try:
                    self._remove_with_retries(target)
                except OSError as exc:
                    problems.append(f"could not remove {name} ({type(exc).__name__})")
        if problems:
            return False
        try:
            self._platform.delete_profile(record.profile_name)
        except AppError as exc:
            problems.append(f"profile delete failed ({exc.details.get('hresult')})")
            return False
        if os.path.lexists(packages):
            try:
                self._remove_with_retries(packages)
            except OSError as exc:
                problems.append(f"could not remove the profile folder ({type(exc).__name__})")
        return (not os.path.lexists(packages)
                and not self._platform.profile_exists(record.profile_name))

    def cleanup(self, run_id: UUID) -> CheckRunRecord:
        """Remove the box of ``run_id``; idempotent for CLEANED, CLEANUP_FAILED on any failure."""

        record = self.repository.get(run_id)
        if record is None:
            raise AppError("CHECK_RUN_NOT_FOUND", "The check run does not exist.",
                           status_code=404, details={"check_run_id": str(run_id)})
        if record.state == CheckRunState.CLEANED:
            return record
        problems: list[str] = []
        try:
            removed = self._remove_box(record, problems)
        except Exception as exc:  # any failure must end CLEANUP_FAILED, never silent
            code = exc.code if isinstance(exc, AppError) else type(exc).__name__
            problems.append(f"cleanup could not run ({code})")
            removed = False
        if removed and not problems:
            return self._save(record, record.state, state=CheckRunState.CLEANED)
        if not problems:
            problems.append("the profile folder or mapping still exists")
        LOGGER.warning("check run %s cleanup failed (was %s)", record.id, record.state.value)
        self._save(record, record.state, state=CheckRunState.CLEANUP_FAILED)
        raise check_box_cleanup_failed("; ".join(problems))

    def sweep(self, *, live_run_ids: Collection[UUID] | None = None) -> SweepReport:
        """Finish every check row recorded in THIS database that is not CLEANED.

        Driven only by ``repository.list_unclean()``: Packages folders and the
        AppContainer registry are never enumerated. Boxes open in this process
        (``live_run_ids``, default: this manager's open boxes) are skipped.
        """

        live = set(self._live if live_run_ids is None else live_run_ids)
        cleaned: list[UUID] = []
        failed: list[tuple[UUID, str]] = []
        for record in self.repository.list_unclean():
            if record.id in live:
                continue
            try:
                self.cleanup(record.id)
                LOGGER.info("sweep: check run %s cleaned (was %s)", record.id,
                            record.state.value)
                cleaned.append(record.id)
            except Exception as exc:  # collected, never raised: one row must not stop the rest
                reason = (str(exc.details.get("reason") or exc.code)
                          if isinstance(exc, AppError) else type(exc).__name__)
                LOGGER.warning("sweep: check run %s failed (%s)", record.id, reason)
                failed.append((record.id, reason))
        return SweepReport(cleaned=tuple(cleaned), failed=tuple(failed))

    # ------------------------------------------------------------------ open

    def baseline_for(self, change_id: UUID) -> str:
        """The commit whose committed ``.gitignore`` files also decide what a box may see.

        The Change's earliest ``baseline`` Git checkpoint; else the base commit
        of its earliest workspace (apply-back fast-forwards HEAD to the agent's
        commit, so HEAD is the agent's); else ``HEAD`` for a Change that never
        recorded either (the agent then wrote nothing Sentinel applied).
        """

        with self.repository.database.connection() as connection:
            row = connection.execute(
                "SELECT head_sha FROM git_checkpoints WHERE change_id = ? AND name = ? "
                "ORDER BY captured_at ASC LIMIT 1",
                (str(change_id), BASELINE_CHECKPOINT_NAME),
            ).fetchone()
            if row is not None:
                return str(row["head_sha"])
            rows = connection.execute(
                "SELECT payload_json FROM change_workspaces WHERE change_id = ? "
                "ORDER BY created_at ASC, rowid ASC", (str(change_id),),
            ).fetchall()
        for workspace in rows:
            try:
                base = json.loads(workspace["payload_json"]).get("base_sha")
            except (ValueError, AttributeError, RecursionError):
                continue
            if isinstance(base, str) and base:
                return base
        return "HEAD"

    def open(
        self, change_id: UUID, source_root: str | Path, runtime: BoxRuntime, *,
        network: bool = False, size_limit: int = DEFAULT_TREE_SIZE_LIMIT_BYTES,
    ) -> CheckBox:
        """Build a disposable box for one check run of ``change_id`` over ``source_root``.

        The tree listing and every refusal happen before anything exists. The
        ``check_runs`` row (CREATING, with the runtime entries it will grant)
        is written before the profile is created, so a crash at any later point
        leaves a row the sweep finishes. Any failure here cleans the box up and
        re-raises.
        """

        if not isinstance(runtime, BoxRuntime):
            raise TypeError("runtime must be a BoxRuntime")
        source = _resolve_source(source_root)
        files = list_check_tree(source, size_limit=size_limit,
                                baseline=self.baseline_for(change_id))
        run_id = uuid4()
        name = self._prefix + run_id.hex
        package_sid = self._platform.derive_package_sid(name)
        now = self._clock()
        record = self.repository.insert(CheckRunRecord(
            id=run_id, change_id=change_id, profile_name=name, package_sid=package_sid,
            state=CheckRunState.CREATING, network=bool(network),
            runtime_grants=tuple(RuntimeGrant(str(snapshot.path), snapshot.manifest_digest)
                                 for snapshot in runtime.snapshots),
            created_at=now, updated_at=now,
        ))
        self._live.add(run_id)
        try:
            profile, _created = self._platform.ensure_profile(name, display_name="Sentinel check")
            if str(profile.package_sid).upper() != package_sid.upper():
                raise appcontainer.verification_failed("package_sid")
            container = self._packages_folder(record) / "AC"
            if not _same_path(profile.container_path, container):
                raise appcontainer.launch_failed("the profile folder is not the expected folder")
            tree = container / "tree"
            scratch = container / "scratch"
            tree.mkdir()
            scratch.mkdir()
            tree_digest = copy_check_tree(source, files, tree, size_limit=size_limit)
            for snapshot in runtime.snapshots:
                self._platform.grant(snapshot.path, package_sid, allowed_root=self._runtime_root)
            record = self._save(record, CheckRunState.CREATING, state=CheckRunState.READY,
                                tree_digest=tree_digest)
        except BaseException:
            try:
                self.cleanup(run_id)
            except Exception:
                LOGGER.warning("check run %s could not be cleaned after a failed open", run_id)
            finally:
                self._live.discard(run_id)
            raise
        return CheckBox(self, record, container=container, runtime=runtime)

    def _release(self, run_id: UUID) -> None:
        try:
            self.cleanup(run_id)
        finally:
            self._live.discard(run_id)


# ---------------------------------------------------------------------- runtime


@dataclass(frozen=True, slots=True)
class BoxRuntime:
    """What a box runs with: cache entries to grant read on, plus extra environment.

    ``env`` may not set a key ``base_environment`` owns (PATH, LOCALAPPDATA,
    TEMP...); ``path_entries`` are prepended to the box PATH.
    """

    snapshots: tuple[RuntimeSnapshot, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    path_entries: tuple[Path, ...] = ()
    executable: Path | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reserved = [key for key in self.env if key.upper() in _RESERVED_ENV_KEYS]
        if reserved:
            raise ValueError(f"a box runtime may not set {sorted(reserved)}")
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))
        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "path_entries", tuple(Path(p) for p in self.path_entries))


def python_box_runtime(runtime: PythonRuntime) -> BoxRuntime:
    """The snapshot interpreter (``PYTHONHOME``) plus its dependency snapshot (``PYTHONPATH``)."""

    interpreter, dependencies, limitations = runtime
    return BoxRuntime(
        snapshots=(interpreter, dependencies),
        env={
            "PYTHONHOME": str(interpreter.path),
            "PYTHONPATH": str(dependencies.path),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        executable=interpreter.path / "python.exe",
        limitations=tuple(limitations),
    )


# ---------------------------------------------------------------------- tree


def _resolve_source(source_root: str | Path) -> Path:
    try:
        source = Path(source_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise check_tree_refused("CHECK_TREE_FAILED", "the repository does not exist") from exc
    if not source.is_dir():
        raise check_tree_refused("CHECK_TREE_FAILED", "the repository is not a directory")
    return source


def _git_list(source: Path, args: Sequence[str]) -> list[str]:
    try:
        result = run_git(source, list(args), timeout=GIT_LIST_TIMEOUT_SECONDS,
                         limit=GIT_LIST_LIMIT)
    except AppError as exc:
        raise check_tree_refused(
            "CHECK_TREE_FAILED", f"Git refused the listing ({exc.code})") from exc
    if result.timed_out or result.incomplete or result.truncated:
        raise check_tree_refused("CHECK_TREE_FAILED", "the Git listing did not complete")
    if result.returncode != 0:
        raise check_tree_refused("CHECK_TREE_FAILED", "the Git listing failed")
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise check_tree_refused("CHECK_TREE_UNSAFE_PATH", "a listed path is not UTF-8") from exc
    return [item for item in text.split("\0") if item]


def _validate_relpath(relpath: str) -> None:
    parts = relpath.split("/")
    if (not relpath or "\\" in relpath or ":" in relpath
            or PureWindowsPath(relpath).anchor
            or any(part in ("", ".", "..") for part in parts)
            or any(part.casefold() == ".git" for part in parts)):
        raise check_tree_refused(
            "CHECK_TREE_UNSAFE_PATH", "a listed path is not a safe relative path", relpath)


def _baseline_commit(source: Path, baseline: str) -> str:
    if baseline != "HEAD" and not _SHA_PATTERN.fullmatch(baseline):
        raise check_tree_refused("CHECK_TREE_BASELINE_UNAVAILABLE",
                                 "the baseline is not a commit id")
    try:
        result = run_git(source, ["rev-parse", "--verify", "-q", f"{baseline}^{{commit}}"],
                         timeout=GIT_LIST_TIMEOUT_SECONDS)
    except AppError as exc:
        raise check_tree_refused(
            "CHECK_TREE_FAILED", f"Git refused the baseline lookup ({exc.code})") from exc
    commit = result.stdout.decode("ascii", errors="replace").strip()
    if result.returncode != 0 or not _SHA_PATTERN.fullmatch(commit):
        raise check_tree_refused(
            "CHECK_TREE_BASELINE_UNAVAILABLE",
            "the baseline commit whose ignore rules decide what a check may see is missing")
    return commit


def baseline_ignored(source: Path, baseline: str, candidates: Sequence[str]) -> set[str]:
    """The ``candidates`` (untracked relpaths) that the baseline commit's ``.gitignore`` ignores.

    The tested tree's ``.gitignore`` files are part of the agent's change, so
    they cannot be what decides which secrets stay out of a box (CR-01). The
    baseline commit's committed ``.gitignore`` blobs are written into a
    throwaway Sentinel-owned repository at their own paths, every candidate
    gets an empty placeholder there, and Git itself answers which are ignored
    (same nesting, negation and directory semantics; no file content is read).
    """

    commit = _baseline_commit(source, baseline)
    rules: list[tuple[str, str]] = []
    for entry in _git_list(source, ["ls-tree", "-r", "-z", "--full-tree", commit]):
        meta, _, relpath = entry.partition("\t")
        fields = meta.split(" ")
        if len(fields) != 3 or fields[1] != "blob" or relpath.rsplit("/", 1)[-1] != ".gitignore":
            continue
        if fields[0] not in ("100644", "100755"):
            continue  # Git does not follow a symlinked .gitignore either
        _validate_relpath(relpath)
        rules.append((relpath, fields[2]))
    if not rules:
        return set()
    scratch = Path(tempfile.mkdtemp(prefix="sentinel-ignore-"))
    try:
        _git_list(scratch, ["init", "-q"])
        root = _long(scratch)
        for relpath, oid in rules:
            try:
                blob = run_git(source, ["cat-file", "blob", oid],
                               timeout=GIT_LIST_TIMEOUT_SECONDS, limit=IGNORE_RULES_LIMIT)
            except AppError as exc:
                raise check_tree_refused(
                    "CHECK_TREE_FAILED", f"Git refused a baseline ignore file ({exc.code})"
                ) from exc
            if blob.returncode != 0 or blob.truncated or blob.incomplete or blob.timed_out:
                raise check_tree_refused(
                    "CHECK_TREE_FAILED", "a baseline ignore file could not be read", relpath)
            target = root.joinpath(*relpath.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob.stdout)
        for relpath in candidates:
            target = root.joinpath(*relpath.split("/"))
            if not os.path.lexists(target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
        ignored = set(_git_list(scratch, ["ls-files", "-z", "--others", "--ignored",
                                          "--exclude-standard"]))
    except OSError as exc:
        raise check_tree_refused(
            "CHECK_TREE_FAILED", f"the baseline ignore rules could not be evaluated "
                                 f"({type(exc).__name__})") from exc
    finally:
        appcontainer.remove_tree_no_follow(scratch)
    return ignored & set(candidates)


def list_check_tree(
    source: Path, *, size_limit: int = DEFAULT_TREE_SIZE_LIMIT_BYTES,
    baseline: str = "HEAD",
) -> list[str]:
    """The sorted posix relpaths a check tree copies from ``source`` (read-only).

    Tracked files, plus untracked files that NEITHER the tested tree's ignore
    rules NOR the ``baseline`` commit's committed ``.gitignore`` files ignore
    (an agent edit to ``.gitignore`` cannot un-ignore a secret; CR-01). With
    untracked files and no resolvable baseline commit the tree is refused.

    Refuses (``CHECK_TREE_*``) gitlinks and embedded repositories,
    skip-worktree/assume-unchanged entries, unsafe paths, reparse points on any
    listed path or its parents, special files and trees over ``size_limit``.
    Paths listed by Git but missing on disk (deleted) are dropped.
    """

    for entry in _git_list(source, ["ls-files", "-z", "--stage"]):
        meta, _, relpath = entry.partition("\t")
        if meta.split(" ", 1)[0] == _GITLINK_MODE:
            raise check_tree_refused("CHECK_TREE_GITLINK", "the index holds a gitlink", relpath)
    listed: dict[str, None] = {}
    untracked: list[str] = []
    for entry in _git_list(source, ["ls-files", "-z", "-v", "--cached", "--others",
                                    "--exclude-standard"]):
        tag, _, relpath = entry.partition(" ")
        if tag == "S" or (len(tag) == 1 and tag.islower()):
            raise check_tree_refused(
                "CHECK_TREE_HIDDEN_INDEX_ENTRY",
                "an index entry is marked skip-worktree or assume-unchanged", relpath)
        if relpath.endswith("/"):
            raise check_tree_refused(
                "CHECK_TREE_GITLINK", "an untracked embedded repository is present", relpath)
        _validate_relpath(relpath)
        listed[relpath] = None
        if tag == "?":
            untracked.append(relpath)
    if untracked:
        for relpath in baseline_ignored(source, baseline, untracked):
            listed.pop(relpath, None)

    root = _long(source)
    checked: dict[str, bool] = {}  # relative directory -> exists as a real directory
    files: list[str] = []
    folded: set[str] = set()
    total = 0
    for relpath in sorted(listed):
        parts = relpath.split("/")
        present = True
        for depth in range(1, len(parts)):
            directory = "/".join(parts[:depth])
            if directory not in checked:
                path = root.joinpath(*parts[:depth])
                try:
                    if _is_reparse(path):
                        raise check_tree_refused(
                            "CHECK_TREE_REPARSE_POINT",
                            "a directory is a link or reparse point", directory)
                    checked[directory] = stat.S_ISDIR(os.lstat(path).st_mode)
                except FileNotFoundError:
                    checked[directory] = False
            if not checked[directory]:
                present = False
                break
        if not present:
            continue  # a deleted path (its directory is gone)
        path = root.joinpath(*parts)
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue  # deleted in the working tree
        if _is_reparse(path):
            raise check_tree_refused(
                "CHECK_TREE_REPARSE_POINT", "a listed path is a link or reparse point", relpath)
        if not stat.S_ISREG(info.st_mode):
            raise check_tree_refused(
                "CHECK_TREE_SPECIAL_FILE", "a listed path is not a regular file", relpath)
        key = relpath.casefold()
        if key in folded:
            raise check_tree_refused(
                "CHECK_TREE_UNSAFE_PATH", "two listed paths differ only by case", relpath)
        folded.add(key)
        total += info.st_size
        if total > size_limit:
            raise check_tree_refused(
                "CHECK_TREE_TOO_LARGE", f"the check tree exceeds {size_limit} bytes")
        files.append(relpath)
    return files


def copy_check_tree(
    source: Path, files: Sequence[str], destination: Path, *,
    size_limit: int = DEFAULT_TREE_SIZE_LIMIT_BYTES,
) -> str:
    """Copy ``files`` from ``source`` into the empty ``destination``; the manifest digest.

    Each file is re-checked (no reparse point, regular) and hashed as it streams.
    """

    root = _long(source)
    target_root = _long(destination)
    entries: list[ManifestEntry] = []
    total = 0
    for relpath in files:
        parts = relpath.split("/")
        path = root.joinpath(*parts)
        if _is_reparse(path) or not stat.S_ISREG(os.lstat(path).st_mode):
            raise check_tree_refused(
                "CHECK_TREE_REPARSE_POINT", "a listed path changed into a link", relpath)
        target = target_root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as reader, open(target, "xb") as writer:
            for chunk in iter(lambda: reader.read(_CHUNK), b""):
                size += len(chunk)
                total += len(chunk)
                if total > size_limit:
                    raise check_tree_refused(
                        "CHECK_TREE_TOO_LARGE", f"the check tree exceeds {size_limit} bytes")
                digest.update(chunk)
                writer.write(chunk)
        entries.append(ManifestEntry(relpath, size, digest.hexdigest()))
    return manifest_digest(entries)


# ---------------------------------------------------------------------- box


@dataclass(frozen=True, slots=True)
class CheckRunFacts:
    """One confined run: bounded output plus the boundary facts verified before it ran."""

    check_run_id: UUID
    exit_code: int | None
    timed_out: bool
    stdout: bytes
    stderr: bytes
    truncated: bool
    stdout_digest: str
    appcontainer: appcontainer.AppContainerFacts
    capabilities: tuple[str, ...]
    network: bool
    argv_sha256: str
    tree_digest: str
    duration_ms: int
    boundary: str = BOUNDARY_APPCONTAINER
    incomplete: bool = False


def verified_boundary(facts: CheckRunFacts) -> str | None:
    """The boundary to report for a box run: APPCONTAINER only for verified token facts.

    Production launches are refused before resume unless the token verifies, so
    this is None only for a test layer (or a regression) whose facts do not
    verify; a contract field must then not claim the box boundary.
    """

    token = facts.appcontainer
    if (facts.boundary == BOUNDARY_APPCONTAINER and token.is_appcontainer is True
            and token.job_verified is True):
        return BOUNDARY_APPCONTAINER
    return None


def argv_digest(argv: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()


class CheckBox:
    """A ready box: ``tree`` (cwd of every run) and ``scratch`` are writable from inside."""

    def __init__(
        self, boxes: CheckBoxes, record: CheckRunRecord, *, container: Path,
        runtime: BoxRuntime,
    ) -> None:
        self._boxes = boxes
        self._record = record
        self._runtime = runtime
        self.container = container
        self.tree = container / "tree"
        self.scratch = container / "scratch"
        self._closed = False

    @classmethod
    def open(
        cls, boxes: CheckBoxes, change_id: UUID, source_root: str | Path,
        runtime: BoxRuntime, *, network: bool = False,
        size_limit: int = DEFAULT_TREE_SIZE_LIMIT_BYTES,
    ) -> CheckBox:
        return boxes.open(change_id, source_root, runtime, network=network,
                          size_limit=size_limit)

    @property
    def id(self) -> UUID:
        return self._record.id

    @property
    def profile_name(self) -> str:
        return self._record.profile_name

    @property
    def package_sid(self) -> str:
        return self._record.package_sid

    @property
    def network(self) -> bool:
        return self._record.network

    @property
    def tree_digest(self) -> str:
        return str(self._record.tree_digest)

    @property
    def capabilities(self) -> tuple[str, ...]:
        return NETWORK_CAPABILITIES if self._record.network else ()

    # ------------------------------------------------------------------ run

    def run(
        self, argv: Sequence[str], *, timeout: float, limit: int,
        stderr_limit: int | None = None,
    ) -> CheckRunFacts:
        """Run ``argv`` (absolute executable) in the box with ``cwd=tree``; bounded output."""

        if self._closed or self._record.state not in (CheckRunState.READY,
                                                      CheckRunState.FINISHED):
            raise AppError("CHECK_RUN_STATE_CONFLICT", "The check box cannot run now.",
                           status_code=409,
                           details={"state": "CLOSED" if self._closed
                                    else self._record.state.value, "operation": "run"})
        arguments = list(argv)
        if not arguments or not all(isinstance(item, str) for item in arguments):
            raise check_box_invalid_argv("argv must be a non-empty list of strings")
        if not os.path.isabs(arguments[0]) or not PureWindowsPath(arguments[0]).drive:
            raise check_box_invalid_argv("the executable must be an absolute path")
        boxes = self._boxes
        platform = boxes._platform
        env = dict(platform.base_environment(self.container,
                                             path_entries=self._runtime.path_entries))
        env.update(self._runtime.env)
        capabilities = self.capabilities
        record = boxes._save(self._record, self._record.state, state=CheckRunState.RUNNING)
        self._record = record
        spawned: list[Any] = []

        def factory(command, cwd, environment):
            process = platform.spawn(
                command, cwd=cwd, env=environment, redact=lambda text: text,
                profile_name=record.profile_name, expected_package_sid=record.package_sid,
                capabilities=capabilities,
            )
            spawned.append(process)
            return process

        started = time.monotonic()
        try:
            result = capture(
                arguments, cwd=self.tree, env=env, timeout=timeout, limit=limit,
                max_timeout=MAX_CHECK_TIMEOUT_SECONDS, stderr_limit=stderr_limit,
                process_factory=factory,
            )
        except BaseException:
            # A refused launch or a failed capture: no confined-run event is claimed.
            self._record = boxes._save(record, CheckRunState.RUNNING,
                                       state=CheckRunState.FINISHED, exit_code=None,
                                       timed_out=None)
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        facts: appcontainer.AppContainerFacts = spawned[0].appcontainer
        digest = argv_digest(arguments)
        payload = {
            "check_run_id": str(record.id),
            "profile_name": record.profile_name,
            "package_sid": facts.package_sid,
            "is_appcontainer": facts.is_appcontainer,
            "integrity_rid": f"{facts.integrity_rid:#06x}",
            "job_verified": facts.job_verified,
            "capabilities": list(capabilities),
            "capability_sids": list(facts.capability_sids),
            "network": record.network,
            "argv_sha256": digest,
            "tree_manifest_digest": record.tree_digest,
            "runtime_manifest_digests": [grant.manifest_digest
                                         for grant in record.runtime_grants],
            "exit_code": result.returncode,
            "timed_out": result.timed_out,
            "boundary": BOUNDARY_APPCONTAINER,
        }
        self._record = boxes._save(
            record, CheckRunState.RUNNING, state=CheckRunState.FINISHED,
            exit_code=result.returncode, timed_out=result.timed_out,
            facts=facts.to_payload(), event=JournalEventType.CHECK_CONFINED_RUN,
            payload=payload,
        )
        return CheckRunFacts(
            check_run_id=record.id, exit_code=result.returncode, timed_out=result.timed_out,
            stdout=result.stdout, stderr=result.stderr,
            truncated=result.truncated or result.incomplete,
            stdout_digest=result.stdout_digest, appcontainer=facts,
            capabilities=capabilities, network=record.network, argv_sha256=digest,
            tree_digest=str(record.tree_digest), duration_ms=duration_ms,
            incomplete=result.incomplete,
        )

    # ------------------------------------------------------------------ outputs

    def read_output(self, name: str, limit: int) -> bytes:
        """Read ``scratch/<name>`` back, at most ``limit`` bytes; never follows a link."""

        if type(limit) is not int or limit < 0:
            raise ValueError("limit must be a non-negative int")
        if not isinstance(name, str) or not name:
            raise check_output_refused("CHECK_OUTPUT_REFUSED", "the name is empty")
        windows = PureWindowsPath(name)
        if windows.anchor or windows.drive or ":" in name:
            raise check_output_refused("CHECK_OUTPUT_REFUSED", "the name is not relative")
        parts = name.replace("\\", "/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise check_output_refused("CHECK_OUTPUT_REFUSED", "the name leaves scratch")
        current = _long(self.scratch)
        try:
            if _is_reparse(current):
                raise check_output_refused("CHECK_OUTPUT_REFUSED", "scratch is a link")
            for part in parts:
                current = current / part
                if _is_reparse(current):
                    raise check_output_refused(
                        "CHECK_OUTPUT_REFUSED", "the output path holds a link or reparse point")
            info = os.lstat(current)
        except FileNotFoundError as exc:
            raise check_output_refused("CHECK_OUTPUT_NOT_FOUND", "no such output") from exc
        if not stat.S_ISREG(info.st_mode):
            raise check_output_refused("CHECK_OUTPUT_REFUSED", "the output is not a file")
        if info.st_size > limit:
            raise check_output_refused(
                "CHECK_OUTPUT_TOO_LARGE", f"the output exceeds {limit} bytes")
        with open(current, "rb") as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise check_output_refused(
                "CHECK_OUTPUT_TOO_LARGE", f"the output exceeds {limit} bytes")
        return data

    # ------------------------------------------------------------------ close

    def close(self) -> None:
        """Revoke runtime ACEs, remove the tree no-follow, delete the profile (row CLEANED)."""

        if self._closed:
            return
        self._closed = True
        self._boxes._release(self._record.id)

    def __enter__(self) -> CheckBox:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        except Exception:
            if exc is None:
                raise
            # Never mask the body's own failure; the row stays CLEANUP_FAILED for the sweep.
            LOGGER.warning("check run %s cleanup failed during an error", self._record.id)
