"""Bounded, read-only access to committed and working-tree files.

Never checks anything out, never applies filters or textconv, and never follows
symlinks out of the repository. Returns ``None`` for absent content rather than
guessing.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.app.git.adapter import METADATA_LIMIT, GitRepositoryInspector
from backend.app.git.errors import GitCommandError

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _paths(output: bytes) -> list[str]:
    try:
        text = output.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitCommandError("Git returned paths in an unsupported encoding.") from exc
    return [item for item in text.split("\0") if item]


def _run(root: str, args: list[str], limit: int):
    result = GitRepositoryInspector._capture_git(root, args, limit)
    if result.truncated:
        raise GitCommandError("Git metadata exceeded the reader limit.")
    return result


def head_sha(root: str) -> str:
    out = _run(root, ["rev-parse", "--verify", "HEAD"], 256).stdout.decode("utf-8").strip()
    if not _SHA.fullmatch(out):
        raise GitCommandError("The repository HEAD is unsupported.")
    return out


def list_paths(root: str, commit: str) -> list[str]:
    """Paths present at ``commit`` or visible in the index/working tree."""

    if not _SHA.fullmatch(commit):
        raise GitCommandError("A full commit identity is required.")
    committed = _paths(_run(root, ["ls-tree", "-r", "-z", "--name-only", commit],
                            METADATA_LIMIT).stdout)
    current = _paths(_run(root, ["ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], METADATA_LIMIT).stdout)
    return sorted(set(committed) | set(current))


def read_committed(root: str, commit: str, path: str, limit: int) -> bytes | None:
    """Blob bytes at ``commit:path`` or ``None`` when absent. Oversize raises."""

    if not _SHA.fullmatch(commit):
        raise GitCommandError("A full commit identity is required.")
    try:
        result = GitRepositoryInspector._capture_git(
            root, ["cat-file", "blob", f"{commit}:{path}"], limit)
    except GitCommandError as exc:
        if "exit_code" in exc.details:
            return None
        raise
    if result.truncated:
        raise GitCommandError("The committed file exceeds the reader limit.")
    return result.stdout


def read_working(root: str, path: str, limit: int) -> bytes | None:
    """Working-tree bytes or ``None`` when absent; symlinks and escapes are refused."""

    base = Path(root)
    target = base / path
    try:
        if target.is_symlink():
            raise GitCommandError("Symbolic links are not read as evidence.")
        resolved = target.resolve(strict=True)
        if base.resolve() not in resolved.parents or not resolved.is_file():
            return None
        if resolved.stat().st_size > limit:
            raise GitCommandError("The working file exceeds the reader limit.")
        return resolved.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise GitCommandError("The working file could not be read.") from exc
