"""Where Sentinel's evidence store lives, and the rule that keeps it out of repositories.

The SQLite evidence database and the API bearer token (stored beside it by
`core.auth`) are Sentinel's own state. If they sit inside a Git working tree,
an agent working in that tree can read the token that drives Sentinel's API
and read or alter the evidence that is supposed to describe the agent. So the
default store is a per-user directory, `%LOCALAPPDATA%\\Sentinel` (falling back
to `~/AppData/Local/Sentinel`), and startup refuses any database path that a
Git working tree encloses. That check walks the path and every parent, on both
the lexical path and the junction/symlink resolved path, for a `.git` entry
that is a real repository: it must look like one (a directory holding `HEAD`
and `objects/`, or a gitfile with a `gitdir:` line) and the hardened Git
harness must confirm it (`rev-parse --absolute-git-dir` run against that Git
directory reports exactly that directory). An empty or broken `.git` that Git
itself would not treat as a repository no longer refuses the store, so a
stray `.git` directory is not a denial of service. When Git cannot be run to
confirm (not installed, the harness refuses the configuration), or Git
recognises the repository but refuses to open it (anything other than its
"not a git repository" verdict), a structurally real `.git` still refuses:
the check fails closed.

The default directory's DACL is restricted to the current user and SYSTEM with
inheritance removed (`prepare_store_directory`). That call refuses any
directory not named `Sentinel`, so it can never re-ACL LOCALAPPDATA, the home
directory, or a directory an operator chose with CHANGE_ASSURANCE_DB_PATH. The
restriction keeps other local accounts out; it does not keep out processes
running as the same user.

Moving an existing store is explicit (`sentinel migrate-store`, `migrate_store`
below). Startup never copies a legacy `.change-assurance` store on its own.
When a legacy store exists in the working directory and the default store has
not been created yet, startup refuses (`EVIDENCE_STORE_MIGRATION_REQUIRED`)
instead of creating a fresh default store that would then block the migration
(`ensure_no_unmigrated_legacy_store`). Otherwise it only logs a warning that a
legacy store is left behind. The migration reads the source through a
read-only SQLite connection, copies it with the online backup API, requires
`PRAGMA integrity_check` to return exactly `ok` on the copy, never overwrites
an existing target database or token, and leaves the source in place.

The migration rotates the API token (revised D-06): it never copies the
legacy `api_token`, because that token sat inside a working tree an agent may
already have read. The new store gets a freshly generated token restricted to
the current user; if that restriction cannot be applied the migration fails
and is rolled back. Clients that used the old token must re-read the new one,
and the old store directory (which still holds the stale token) should be
deleted after the new store is verified.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.auth import TOKEN_FILENAME, new_api_token
from backend.app.core.errors import (
    evidence_store_inside_repository,
    evidence_store_migration_integrity_failed,
    evidence_store_migration_io_failed,
    evidence_store_migration_required,
    evidence_store_migration_source_missing,
    evidence_store_migration_target_exists,
    evidence_store_migration_token_unprotected,
    evidence_store_unsafe_location,
)
from backend.app.execution.acl import restrict_to_current_user
from backend.app.git.errors import GitRepositoryError
from backend.app.git.safe_exec import run_git

STORE_DIRECTORY_NAME = "Sentinel"
DATABASE_FILENAME = "change_assurance.sqlite3"
LEGACY_STORE_DIRECTORY = ".change-assurance"
REPOSITORY_CONFIRM_TIMEOUT_SECONDS = 10


def default_store_directory(environ: Mapping[str, str] | None = None) -> Path:
    """Return `%LOCALAPPDATA%\\Sentinel`, or `~/AppData/Local/Sentinel` without it."""

    source = os.environ if environ is None else environ
    local_app_data = source.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / STORE_DIRECTORY_NAME


def default_database_path(environ: Mapping[str, str] | None = None) -> Path:
    return default_store_directory(environ) / DATABASE_FILENAME


def legacy_database_path(cwd: Path | None = None) -> Path:
    """The pre-relocation default: `<cwd>/.change-assurance/change_assurance.sqlite3`."""

    return (cwd or Path.cwd()) / LEGACY_STORE_DIRECTORY / DATABASE_FILENAME


def _git_directory(directory: Path) -> Path | None:
    """The Git directory a `.git` entry names, if it is structurally a repository.

    A directory must hold `HEAD` and `objects/`; a gitfile must start with a
    `gitdir:` line (resolved relative to `directory`). Anything else, such as
    an empty `.git` directory, is not a repository.
    """

    entry = directory / ".git"
    try:
        if entry.is_dir():
            if (entry / "HEAD").is_file() and (entry / "objects").is_dir():
                return entry
            return None
        if entry.is_file():
            with entry.open("rb") as handle:
                first = handle.read(4096).splitlines()[:1]
            if not first or not first[0].startswith(b"gitdir:"):
                return None
            target = Path(first[0][len(b"gitdir:"):].decode("utf-8").strip())
            return target if target.is_absolute() else directory / target
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return None


def _git_confirms_repository(git_dir: Path) -> bool:
    """Ask the hardened harness whether `git_dir` is a real Git directory.

    Runs against the Git directory itself (never the work tree above it) and
    requires Git to report exactly that directory, so upward discovery into
    an unrelated outer repository cannot confirm it. Fails closed: when Git
    cannot run or answer, the structural evidence stands.
    """

    try:
        if not git_dir.is_dir():
            return False
        result = run_git(git_dir, ["rev-parse", "--absolute-git-dir"],
                         timeout=REPOSITORY_CONFIRM_TIMEOUT_SECONDS)
    except (GitRepositoryError, OSError):
        return True
    if result.timed_out or result.incomplete:
        return True
    if result.returncode != 0:
        # Only Git's own "not a git repository" verdict clears structural
        # evidence. Any other refusal (for example an agent-planted
        # `core.repositoryformatversion` or unknown `extensions.*`) means Git
        # recognised a repository it will not open: fail closed.
        return b"not a git repository" not in result.stderr.lower()
    try:
        reported = Path(result.stdout.decode("utf-8").strip())
    except UnicodeDecodeError:
        return True
    return reported.resolve(strict=False) == git_dir.resolve(strict=False)


def enclosing_git_worktree(path: Path) -> Path | None:
    """Return the first directory at or above `path` holding a real repository.

    Both the lexical absolute path and the resolved path are walked, so a
    junction or symlink that points into a repository is caught as well.
    The path itself does not need to exist. A `.git` entry counts only when
    it is structurally a repository and the hardened Git harness confirms it
    (see the module docstring).
    """

    candidates = [Path(os.path.abspath(path))]
    resolved = Path(path).resolve(strict=False)
    if resolved != candidates[0]:
        candidates.append(resolved)
    for candidate in candidates:
        for directory in (candidate, *candidate.parents):
            git_dir = _git_directory(directory)
            if git_dir is not None and _git_confirms_repository(git_dir):
                return directory
    return None


def _encloses_user_directories(root: Path) -> bool:
    """True when `root` is the user profile or encloses LOCALAPPDATA."""

    try:
        resolved = root.resolve(strict=False)
        local = default_store_directory().parent.resolve(strict=False)
        home = Path.home().resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return resolved == home or resolved == local or resolved in local.parents


def ensure_store_outside_repository(database_path: Path) -> None:
    root = enclosing_git_worktree(database_path)
    if root is not None:
        raise evidence_store_inside_repository(
            str(database_path), str(root), user_directory=_encloses_user_directories(root)
        )


def ensure_no_unmigrated_legacy_store(
    database_path: Path,
    *,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Refuse to create a fresh default store while a legacy store awaits migration.

    Applies only when `database_path` is the default store and neither its
    database nor its api_token exists yet (either one makes `migrate-store`
    refuse the target). An operator-chosen CHANGE_ASSURANCE_DB_PATH, or a
    default store that already exists (for example after `migrate-store`),
    is left to `warn_if_legacy_store_present`.
    """

    target = Path(database_path)
    legacy = legacy_database_path(cwd)
    try:
        if target.resolve() != default_database_path(environ).resolve():
            return
        if _exists(target) or _exists(target.parent / TOKEN_FILENAME):
            return
        if not legacy.is_file() or legacy.resolve() == target.resolve():
            return
    except OSError:
        return
    raise evidence_store_migration_required(str(legacy), str(target))


def warn_if_legacy_store_present(
    database_path: Path, *, cwd: Path | None = None, logger: logging.Logger
) -> None:
    """Log (never copy) when a legacy in-repository store is left behind."""

    legacy = legacy_database_path(cwd)
    try:
        if not legacy.is_file():
            return
        if legacy.resolve() == Path(database_path).resolve():
            return
    except OSError:
        return
    logger.warning(
        "A legacy evidence store remains at %s but Sentinel uses %s. If it was "
        "never migrated, stop Sentinel and run `sentinel migrate-store --to` a "
        "location that does not exist yet; otherwise delete the old directory "
        "(it holds a stale API token).",
        legacy,
        database_path,
    )


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or path.is_junction()
    except OSError:
        return True


def prepare_store_directory(
    directory: Path, *, logger: logging.Logger | None = None
) -> bool:
    """Create the Sentinel store directory and restrict it to user + SYSTEM.

    Raises ValueError for a directory not named `Sentinel` and
    EVIDENCE_STORE_UNSAFE_LOCATION for a junction or symlink. Returns True
    when the DACL was applied. A failed restriction is logged as a warning
    and returns False rather than raising, and nothing claims it held.
    """

    if directory.name.casefold() != STORE_DIRECTORY_NAME.casefold():
        raise ValueError(
            f"Refusing to restrict {directory}: only a directory named "
            f"{STORE_DIRECTORY_NAME!r} is ever re-ACL'd."
        )
    if _is_link(directory):
        raise evidence_store_unsafe_location(str(directory))
    directory.mkdir(parents=True, exist_ok=True)
    if _is_link(directory):
        raise evidence_store_unsafe_location(str(directory))
    if restrict_to_current_user(directory, directory=True):
        return True
    (logger or logging.getLogger(__name__)).warning(
        "Could not restrict the evidence store directory %s to the current user "
        "and SYSTEM; it keeps its inherited permissions.",
        directory,
    )
    return False


# ---- explicit migration (D-06) -----------------------------------------------------

_O_BINARY = getattr(os, "O_BINARY", 0)
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


@dataclass(frozen=True, slots=True)
class StoreMigrationResult:
    source_database: Path
    target_database: Path
    target_token: Path
    token_rotated: bool
    integrity: str


def _integrity_check(path: Path) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return [tuple(row) for row in connection.execute("PRAGMA integrity_check")]
    finally:
        connection.close()


def _backup(source_db: Path, target_db: Path) -> None:
    source_connection = sqlite3.connect(f"{source_db.as_uri()}?mode=ro", uri=True)
    try:
        target_connection = sqlite3.connect(target_db)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
    finally:
        source_connection.close()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_created(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def migrate_store(
    *, source: Path, target: Path, logger: logging.Logger | None = None
) -> StoreMigrationResult:
    """Copy an evidence store's database to a new location with a fresh API token.

    Never writes to, moves, or deletes the source, and never reads or copies
    the source token. Never overwrites an existing target database or token.
    On failure (including a token that cannot be restricted to the current
    user) only the files this call created are removed. Every failure is a
    stable `AppError`: file-system errors (`OSError`, or `ValueError` for an
    unusable path) become EVIDENCE_STORE_MIGRATION_IO_FAILED.
    """

    try:
        return _migrate_store(source=source, target=target, logger=logger)
    except (OSError, ValueError) as error:
        path = getattr(error, "filename", None)
        raise evidence_store_migration_io_failed(
            type(error).__name__, None if path is None else str(path)
        ) from None


def _migrate_store(
    *, source: Path, target: Path, logger: logging.Logger | None
) -> StoreMigrationResult:
    log = logger or logging.getLogger(__name__)
    source_db = Path(source).resolve()
    if not source_db.is_file():
        raise evidence_store_migration_source_missing(str(source))

    target_db = Path(os.path.abspath(target))
    target_token = target_db.parent / TOKEN_FILENAME
    sidecars = [Path(f"{target_db}{suffix}") for suffix in _SQLITE_SIDECARS]
    if _exists(target_db) or target_db.resolve() == source_db:
        raise evidence_store_migration_target_exists(str(target_db))
    if _exists(target_token):
        raise evidence_store_migration_target_exists(str(target_token))
    # A leftover or planted -wal/-shm/-journal would be replayed onto the copy
    # by the next connection, so any of them makes the target "existing".
    for sidecar in sidecars:
        if _exists(sidecar):
            raise evidence_store_migration_target_exists(str(sidecar))
    ensure_store_outside_repository(target_db)

    parent = target_db.parent
    if _is_link(parent):
        raise evidence_store_unsafe_location(str(parent))
    if parent.resolve() == default_store_directory().resolve():
        try:
            prepare_store_directory(parent, logger=log)
        except ValueError:
            # Resolves to the default directory under another name: redirected.
            raise evidence_store_unsafe_location(str(parent)) from None
    else:
        parent.mkdir(parents=True, exist_ok=True)
    if _is_link(parent):
        raise evidence_store_unsafe_location(str(parent))
    ensure_store_outside_repository(target_db)

    for sidecar in sidecars:
        if _exists(sidecar):
            raise evidence_store_migration_target_exists(str(sidecar))
    try:
        descriptor = os.open(
            target_db, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY, 0o600
        )
    except FileExistsError:
        raise evidence_store_migration_target_exists(str(target_db)) from None
    os.close(descriptor)
    created: list[Path] = [target_db]

    def rollback() -> None:
        # No sidecar existed before this call (checked above), so every one is ours.
        _remove_created(created + sidecars)

    try:
        try:
            _backup(source_db, target_db)
            rows = _integrity_check(target_db)
        except sqlite3.Error as error:
            raise evidence_store_migration_integrity_failed(
                f"SQLite error while copying: {type(error).__name__}"
            ) from None
        if rows != [("ok",)]:
            raise evidence_store_migration_integrity_failed(
                f"PRAGMA integrity_check returned {rows[:3]!r}"
            )

        try:
            descriptor = os.open(
                target_token, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY, 0o600
            )
        except FileExistsError:
            raise evidence_store_migration_target_exists(str(target_token)) from None
        created.append(target_token)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(new_api_token().encode("ascii"))
        if not restrict_to_current_user(target_token):
            raise evidence_store_migration_token_unprotected(str(target_token))
    except BaseException:
        rollback()
        raise

    log.info("Migrated evidence store %s to %s with a new API token", source_db, target_db)
    log.warning(
        "The API token was rotated: clients that used the token from %s must re-read "
        "%s. Delete the old store directory %s (it still holds the stale token) after "
        "verifying the new store.",
        source_db.parent, target_token, source_db.parent,
    )
    return StoreMigrationResult(
        source_database=source_db,
        target_database=target_db,
        target_token=target_token,
        token_rotated=True,
        integrity="ok",
    )
