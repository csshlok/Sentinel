"""Hash-verified tool snapshots and per-run staged homes inside an AppContainer folder.

Everything under ``AC`` is writable by the package SID (spike 002), so the
agent can replace ``AC\\tools\\<tool>.exe`` or plant ``.claude/settings.json``
hooks for the next run (research Pitfall 9). The snapshot is therefore re-hashed
against its source (and the Tool Registry digest) before every launch, and a
mismatch fails closed; the staged home is deleted without following links and
rebuilt for every run. File operations only: nothing here starts a process.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.app.core.errors import AppError
from backend.app.execution.appcontainer import remove_tree_no_follow, remove_tree_retrying

_CHUNK = 1 << 20


def tool_snapshot_tampered() -> AppError:
    return AppError(
        "AGENT_TOOL_SNAPSHOT_TAMPERED",
        "The agent's tool snapshot no longer matches its source executable; the workspace "
        "tool folder is agent-writable, so Sentinel refuses to run it.",
        status_code=409,
    )


def tool_snapshot_failed(reason: str) -> AppError:
    return AppError(
        "AGENT_TOOL_SNAPSHOT_FAILED",
        "The agent's tool snapshot could not be prepared.",
        status_code=500,
        details={"reason": reason},
    )


def staged_home_failed(reason: str) -> AppError:
    return AppError(
        "AGENT_STAGED_HOME_FAILED",
        "The agent's staged home could not be prepared.",
        status_code=500,
        details={"reason": reason},
    )


def _is_reparse(path: Path) -> bool:
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(info.st_mode)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ToolSnapshot:
    source: Path
    path: Path
    sha256: str


def _real_directory(path: Path, what: str, error=tool_snapshot_failed) -> None:
    if _is_reparse(path):
        raise error(f"the {what} is a link or reparse point")
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise error(f"the {what} is not a directory")


def ensure_tool_snapshot(
    source: str | Path, tools_dir: str | Path, *, trusted_digest: str | None,
) -> ToolSnapshot:
    """Copy ``source`` into ``tools_dir`` once, then re-verify it on every call.

    Returns the snapshot only when its SHA-256 equals the source's (and
    ``trusted_digest`` when given). An existing snapshot that differs is
    ``AGENT_TOOL_SNAPSHOT_TAMPERED``: Sentinel holds no other record of what it
    copied, so a changed snapshot and a changed host tool are indistinguishable
    and both fail closed.
    """

    source_path = Path(source)
    tools = Path(tools_dir)
    try:
        source_digest = sha256_file(source_path)
        if trusted_digest is not None and trusted_digest.lower() != source_digest:
            raise tool_snapshot_failed("the source does not match the Tool Registry digest")
        if os.path.lexists(tools):
            _real_directory(tools, "tool folder")
        else:
            tools.mkdir(parents=False)
            _real_directory(tools, "tool folder")
        snapshot = tools / source_path.name
        if os.path.lexists(snapshot):
            if _is_reparse(snapshot):
                raise tool_snapshot_failed("the snapshot is a link or reparse point")
            if not stat.S_ISREG(os.lstat(snapshot).st_mode):
                raise tool_snapshot_failed("the snapshot is not a regular file")
            if sha256_file(snapshot) != source_digest:
                raise tool_snapshot_tampered()
            return ToolSnapshot(source_path, snapshot, source_digest)
        partial = tools / f".{source_path.name}.{uuid4().hex}.partial"
        copied = hashlib.sha256()
        try:
            with open(source_path, "rb") as reader, open(partial, "xb") as writer:
                for chunk in iter(lambda: reader.read(_CHUNK), b""):
                    copied.update(chunk)
                    writer.write(chunk)
            # A swap of the source during the copy is caught here.
            if copied.hexdigest() != source_digest or sha256_file(source_path) != source_digest:
                raise tool_snapshot_failed("the source changed while it was copied")
            os.replace(partial, snapshot)
        finally:
            if os.path.lexists(partial):
                remove_tree_no_follow(partial)
        if sha256_file(snapshot) != source_digest:
            raise tool_snapshot_tampered()
        return ToolSnapshot(source_path, snapshot, source_digest)
    except AppError:
        raise
    except OSError as exc:
        raise tool_snapshot_failed(type(exc).__name__) from exc


@dataclass(frozen=True, slots=True)
class StagedHome:
    root: Path
    claude_dir: Path
    roaming: Path
    local: Path


def rebuild_staged_home(home: str | Path) -> StagedHome:
    """Delete ``home`` (never following a link) and recreate an empty staged home."""

    root = Path(home)
    try:
        # The previous run's agent may have synced hundreds of files here, some
        # still pending delete when the next run starts (ERROR_DIR_NOT_EMPTY).
        remove_tree_retrying(root)
        if os.path.lexists(root):
            raise staged_home_failed("the previous staged home could not be removed")
        root.mkdir(parents=False)
        staged = StagedHome(
            root=root, claude_dir=root / ".claude",
            roaming=root / "AppData" / "Roaming", local=root / "AppData" / "Local",
        )
        for directory in (staged.claude_dir, root / "AppData", staged.roaming, staged.local):
            directory.mkdir(parents=False)
        for directory in (root, staged.claude_dir, root / "AppData", staged.roaming, staged.local):
            _real_directory(directory, "staged home", staged_home_failed)
        return staged
    except AppError:
        raise
    except OSError as exc:
        raise staged_home_failed(type(exc).__name__) from exc
