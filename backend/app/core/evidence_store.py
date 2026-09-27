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

Moving an existing store is explicit (`sentinel migrate-store`). Startup never
copies a legacy `.change-assurance` store on its own. It only logs a warning
that one exists.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from backend.app.core.errors import evidence_store_inside_repository

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
