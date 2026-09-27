"""Where Sentinel's evidence store lives, and the rule that keeps it out of repositories.

The SQLite evidence database and the API bearer token (stored beside it by
`core.auth`) are Sentinel's own state. If they sit inside a Git working tree,
an agent working in that tree can read the token that drives Sentinel's API
and read or alter the evidence that is supposed to describe the agent. So the
default store is a per-user directory, `%LOCALAPPDATA%\\Sentinel` (falling back
to `~/AppData/Local/Sentinel`), and startup refuses any database path that a
Git working tree encloses. That check walks the path and every parent for a
`.git` file or directory, on both the lexical path and the junction/symlink
resolved path.

The default directory's DACL is restricted to the current user and SYSTEM with
inheritance removed (`prepare_store_directory`). That call refuses any
directory not named `Sentinel`, so it can never re-ACL LOCALAPPDATA, the home
directory, or a directory an operator chose with CHANGE_ASSURANCE_DB_PATH. The
restriction keeps other local accounts out; it does not keep out processes
running as the same user.

Moving an existing store is explicit (`sentinel migrate-store`, `migrate_store`
below). Startup never copies a legacy `.change-assurance` store on its own. It
only logs a warning that one exists. The migration reads the source through a
read-only SQLite connection, copies it with the online backup API, requires
`PRAGMA integrity_check` to return exactly `ok` on the copy, never overwrites
an existing target database or token, and leaves the source in place.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.auth import TOKEN_FILENAME
from backend.app.core.errors import (
    evidence_store_inside_repository,
    evidence_store_migration_integrity_failed,
    evidence_store_migration_source_missing,
    evidence_store_migration_target_exists,
    evidence_store_unsafe_location,
)
from backend.app.execution.acl import restrict_to_current_user

STORE_DIRECTORY_NAME = "Sentinel"
DATABASE_FILENAME = "change_assurance.sqlite3"
LEGACY_STORE_DIRECTORY = ".change-assurance"


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


def _has_git_entry(directory: Path) -> bool:
    entry = directory / ".git"
    try:
        return entry.is_dir() or entry.is_file() or entry.is_symlink()
    except OSError:
        return False


def enclosing_git_worktree(path: Path) -> Path | None:
    """Return the first directory at or above `path` holding a `.git` entry.

    Both the lexical absolute path and the resolved path are walked, so a
    junction or symlink that points into a repository is caught as well.
    The path itself does not need to exist.
    """

    candidates = [Path(os.path.abspath(path))]
    resolved = Path(path).resolve(strict=False)
    if resolved != candidates[0]:
        candidates.append(resolved)
    for candidate in candidates:
        for directory in (candidate, *candidate.parents):
            if _has_git_entry(directory):
                return directory
    return None


def ensure_store_outside_repository(database_path: Path) -> None:
    root = enclosing_git_worktree(database_path)
    if root is not None:
        raise evidence_store_inside_repository(str(database_path), str(root))


def warn_if_legacy_store_present(
    database_path: Path, *, cwd: Path | None = None, logger: logging.Logger
) -> None:
    """Log (never copy, never refuse) when a legacy in-repository store is left behind."""

    legacy = legacy_database_path(cwd)
    try:
        if not legacy.is_file():
            return
        if legacy.resolve() == Path(database_path).resolve():
            return
    except OSError:
        return
    logger.warning(
        "A legacy evidence store exists at %s but Sentinel now uses %s. "
        "Run `sentinel migrate-store` to copy it, then delete the old store.",
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
    token_copied: bool
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
    """Copy an evidence store (database + api_token) to a new location.

    Never writes to, moves, or deletes the source. Never overwrites an
    existing target database or token. On failure only the files this call
    created are removed.
    """

    log = logger or logging.getLogger(__name__)
    source_db = Path(source).resolve()
    if not source_db.is_file():
        raise evidence_store_migration_source_missing(str(source))

    target_db = Path(os.path.abspath(target))
    target_token = target_db.parent / TOKEN_FILENAME
    if _exists(target_db) or target_db.resolve() == source_db:
        raise evidence_store_migration_target_exists(str(target_db))
    if _exists(target_token):
        raise evidence_store_migration_target_exists(str(target_token))
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

    sidecars = [Path(f"{target_db}{suffix}") for suffix in _SQLITE_SIDECARS]
    pre_existing_sidecars = {path for path in sidecars if _exists(path)}
    try:
        descriptor = os.open(
            target_db, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY, 0o600
        )
    except FileExistsError:
        raise evidence_store_migration_target_exists(str(target_db)) from None
    os.close(descriptor)
    created: list[Path] = [target_db]

    def rollback() -> None:
        _remove_created(
            created + [path for path in sidecars if path not in pre_existing_sidecars]
        )

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

        token_copied = False
        source_token = source_db.parent / TOKEN_FILENAME
        if source_token.is_file():
            data = source_token.read_bytes()
            try:
                descriptor = os.open(
                    target_token, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY, 0o600
                )
            except FileExistsError:
                raise evidence_store_migration_target_exists(str(target_token)) from None
            created.append(target_token)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            restrict_to_current_user(target_token)
            token_copied = True
    except BaseException:
        rollback()
        raise

    log.info("Migrated evidence store %s to %s", source_db, target_db)
    return StoreMigrationResult(
        source_database=source_db,
        target_database=target_db,
        token_copied=token_copied,
        integrity="ok",
    )
