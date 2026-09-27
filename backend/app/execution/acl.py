"""Best-effort owner-only access restriction for Sentinel's own files and directories.

On Windows this runs `icacls` to strip inherited ACEs (`/inheritance:r`) and
grant full control to the current user only. For a directory it also grants
SYSTEM, by the well-known SID `*S-1-5-18` so the call does not depend on the
display language, and marks both grants as inherited by children
(`(OI)(CI)`), so files created in the directory afterwards get the same
restriction. On POSIX it sets mode 0o600 on files and 0o700 on directories.

This is defense in depth, not a boundary. The function never raises: a
failed restriction (icacls missing, no right to change the ACL, a sandbox)
must not break startup. It returns False instead, and callers log that
rather than claiming the restriction was applied. Every process spawn lives
under `backend/app/execution/` (D-04), so `core.auth` and
`core.evidence_store` call this helper instead of running `icacls` themselves.

`icacls` is started by its absolute path in the Windows system directory
(`GetSystemDirectoryW`, not the caller-controlled `SystemRoot` variable) with
that directory as the working directory. A bare `icacls` would let
CreateProcess pick up an `icacls.exe` planted in the backend or CLI process's
current directory (searched before System32 by default), which is the
agent-writable working tree when `sentinel migrate-store` runs from the
legacy store location.
"""

from __future__ import annotations

import ctypes
import os
import stat
import subprocess
from pathlib import Path

ICACLS_TIMEOUT_SECONDS = 10
SYSTEM_SID = "*S-1-5-18"


def windows_system_directory() -> Path | None:
    """The Windows system directory from `GetSystemDirectoryW`; None if unavailable."""

    if os.name != "nt":
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    except (AttributeError, OSError):
        return None
    if not length or length >= len(buffer):
        return None
    directory = Path(buffer.value)
    return directory if directory.is_absolute() and directory.is_dir() else None


def icacls_executable() -> Path | None:
    """Absolute path of System32's `icacls.exe`; None if it is missing."""

    system_directory = windows_system_directory()
    if system_directory is None:
        return None
    candidate = system_directory / "icacls.exe"
    return candidate if candidate.is_file() else None


def _icacls_arguments(
    icacls: Path, path: Path, username: str, *, directory: bool
) -> list[str]:
    if directory:
        return [
            str(icacls), str(path), "/inheritance:r",
            "/grant:r", f"{username}:(OI)(CI)F",
            "/grant:r", f"{SYSTEM_SID}:(OI)(CI)F",
        ]
    return [str(icacls), str(path), "/inheritance:r", "/grant:r", f"{username}:F"]


def restrict_to_current_user(path: Path, *, directory: bool = False) -> bool:
    """Restrict `path` to the current user (plus SYSTEM for directories).

    Returns True only when the restriction was applied.
    """

    if os.name != "nt":
        mode = stat.S_IRWXU if directory else stat.S_IRUSR | stat.S_IWUSR
        try:
            os.chmod(path, mode)
        except OSError:
            return False
        return True

    username = os.environ.get("USERNAME")
    if not username:
        return False
    icacls = icacls_executable()
    if icacls is None:
        return False
    try:
        completed = subprocess.run(
            _icacls_arguments(icacls, Path(path).absolute(), username, directory=directory),
            capture_output=True,
            shell=False,
            timeout=ICACLS_TIMEOUT_SECONDS,
            cwd=icacls.parent,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
