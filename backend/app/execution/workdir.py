"""Sentinel-owned temporary directories that are never inside a repository.

Tool-probe working directories, the Git harness's runtime directory and
recovery worktrees are created under the system temporary directory so that
repository-local configuration never applies to them. That only holds while
the temporary directory is outside every repository Sentinel is pointed at.
When a supervised repository encloses ``%TEMP%`` (a dotfiles repository at
``%USERPROFILE%``, for example), a "temporary" directory would sit inside the
agent-writable working tree: tools would find repository configuration by
walking up again, and recovery worktrees would land inside the main worktree.

``ensure_outside`` and ``temporary_base`` refuse that case with
``WorkdirInsideRepositoryError`` (an ``OSError``) instead of silently running
inside the repository. The fix for the user is to point ``TEMP``/``TMP`` at a
directory outside the repository.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path


class WorkdirInsideRepositoryError(OSError):
    """A Sentinel temporary directory would be inside a repository."""


def _forms(path: str | Path) -> set[Path]:
    """The lexical absolute form and the junction/symlink-resolved form."""

    return {Path(os.path.abspath(path)), Path(path).resolve(strict=False)}


def is_inside(path: str | Path, roots: Iterable[str | Path]) -> bool:
    """True when ``path`` is one of ``roots`` or below one (lexically or resolved)."""

    candidates = _forms(path)
    for root in roots:
        for root_form in _forms(root):
            for candidate in candidates:
                if candidate == root_form or root_form in candidate.parents:
                    return True
    return False


def ensure_outside(path: str | Path, roots: Iterable[str | Path]) -> Path:
    """Return ``path`` resolved; raise when it is inside any of ``roots``."""

    roots = tuple(roots)
    if is_inside(path, roots):
        raise WorkdirInsideRepositoryError(
            f"Sentinel's temporary directory {path} is inside a repository it supervises; "
            "set TEMP and TMP to a directory outside the repository."
        )
    return Path(path).resolve(strict=False)


def temporary_base(roots: Iterable[str | Path]) -> Path:
    """The system temporary directory, refused when a repository encloses it."""

    return ensure_outside(tempfile.gettempdir(), roots)
