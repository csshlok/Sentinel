"""Best-effort owner-only access restriction for Sentinel's own files and directories.

On Windows this runs `icacls` to strip inherited ACEs (`/inheritance:r`) and
grant full control to the current user only. The user is named by the SID of
this process's token (`*S-1-5-21-...`), never by the `USERNAME` environment
variable: an unqualified name can resolve to a same-named local account on a
domain-joined machine (granting the wrong principal and locking the real
user out once inheritance is removed), and the environment is caller
controlled. For a directory it also grants
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
import re
import stat
import subprocess
from pathlib import Path

ICACLS_TIMEOUT_SECONDS = 10
SYSTEM_SID = "*S-1-5-18"
_SID_PATTERN = re.compile(r"S-1-\d+(?:-\d+)+")
_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1


def current_user_sid() -> str | None:
    """The string SID of this process token's user; None if it cannot be read."""

    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD)]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
                kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            needed = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(needed))
            if not needed.value:
                return None
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi32.GetTokenInformation(
                    token, _TOKEN_USER_CLASS, buffer, needed, ctypes.byref(needed)):
                return None
            # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first field is the PSID.
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            text = wintypes.LPWSTR()
            if not sid or not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                return None
            try:
                value = text.value
            finally:
                kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            kernel32.CloseHandle(token)
    except (AttributeError, OSError, ValueError):
        return None
    return value if value and _SID_PATTERN.fullmatch(value) else None


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
    icacls: Path, path: Path, user_sid: str, *, directory: bool
) -> list[str]:
    user = f"*{user_sid}"
    if directory:
        return [
            str(icacls), str(path), "/inheritance:r",
            "/grant:r", f"{user}:(OI)(CI)F",
            "/grant:r", f"{SYSTEM_SID}:(OI)(CI)F",
        ]
    return [str(icacls), str(path), "/inheritance:r", "/grant:r", f"{user}:F"]


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

    user_sid = current_user_sid()
    if not user_sid:
        return False
    icacls = icacls_executable()
    if icacls is None:
        return False
    try:
        completed = subprocess.run(
            _icacls_arguments(icacls, Path(path).absolute(), user_sid, directory=directory),
            capture_output=True,
            shell=False,
            timeout=ICACLS_TIMEOUT_SECONDS,
            cwd=icacls.parent,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


# ---- per-run package-SID read grants (Phase 5, spike 006 B) -----------------------

PACKAGE_GRANT_TIMEOUT_SECONDS = 300
_PACKAGE_SID_PATTERN = re.compile(r"S-1-15-2(?:-\d{1,10}){7}")


def _grant_refused(reason: str):
    from backend.app.core.errors import AppError

    return AppError(
        "CHECK_RUNTIME_GRANT_REFUSED",
        "Sentinel refused to change the access list of a check runtime directory.",
        status_code=409,
        details={"reason": reason},
    )


def _grant_failed(reason: str):
    from backend.app.core.errors import AppError

    return AppError(
        "CHECK_RUNTIME_GRANT_FAILED",
        "The access list of a check runtime directory could not be changed.",
        status_code=500,
        details={"reason": reason},
    )


def _is_link(path: Path) -> bool:
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(info.st_mode)


def _package_grant_target(path: str | Path, package_sid: str, allowed_root: str | Path | None) -> Path:
    if not isinstance(package_sid, str) or not _PACKAGE_SID_PATTERN.fullmatch(package_sid):
        raise _grant_refused("the SID is not an AppContainer package SID")
    if allowed_root is None:
        from backend.app.execution.check_runtime import check_runtime_root

        allowed_root = check_runtime_root(create=False)
    root = Path(os.path.abspath(allowed_root))
    target = Path(os.path.abspath(path))
    if root not in target.parents:
        raise _grant_refused("the directory is not inside the allowed root")
    # The allowed root and every component below it down to the target must be real
    # directories: a junction anywhere would redirect the grant elsewhere.
    chain = [root, *reversed([parent for parent in target.parents if root in parent.parents]), target]
    for component in chain:
        try:
            if _is_link(component):
                raise _grant_refused("the directory or one of its parents is a link or reparse point")
            if not stat.S_ISDIR(os.lstat(component).st_mode):
                raise _grant_refused("the target is not a directory")
        except FileNotFoundError as exc:
            raise _grant_refused("the directory does not exist") from exc
    return target


def _run_icacls_change(target: Path, arguments: list[str]) -> None:
    if os.name != "nt":
        raise _grant_failed("package-SID grants are Windows-only")
    icacls = icacls_executable()
    if icacls is None:
        raise _grant_failed("icacls.exe is unavailable")
    try:
        completed = subprocess.run(
            [str(icacls), str(target), *arguments],
            capture_output=True,
            shell=False,
            timeout=PACKAGE_GRANT_TIMEOUT_SECONDS,
            cwd=icacls.parent,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _grant_failed(type(exc).__name__) from exc
    if completed.returncode != 0:
        raise _grant_failed(f"icacls exited with {completed.returncode}")


def grant_package_read(
    path: str | Path, package_sid: str, *, allowed_root: str | Path | None = None,
) -> None:
    """Add one inheritable read/execute ACE for ``package_sid`` on ``path``.

    ``path`` must be a real directory strictly inside ``allowed_root`` (by
    default the check runtime cache). No other ACE is changed.
    """

    target = _package_grant_target(path, package_sid, allowed_root)
    _run_icacls_change(target, ["/grant", f"*{package_sid}:(OI)(CI)(RX)"])


def revoke_package_read(
    path: str | Path, package_sid: str, *, allowed_root: str | Path | None = None,
) -> None:
    """Remove every granted ACE for ``package_sid`` on ``path`` (the inverse of the grant)."""

    target = _package_grant_target(path, package_sid, allowed_root)
    _run_icacls_change(target, ["/remove:g", f"*{package_sid}"])
