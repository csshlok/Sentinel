"""Fail-closed Windows AppContainer profiles and lowbox process launch.

This module launches a process in a Windows AppContainer whose live token is
verified before it runs, inside a mandatory kill-on-close Job Object, with an
explicit inherited-handle whitelist; it does not by itself prove that any
particular resource is denied.

Launch sequence (``spawn_appcontainer_supervised``): the child is created
suspended with ``PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`` and
``PROC_THREAD_ATTRIBUTE_HANDLE_LIST``; it is assigned to a new kill-on-close
Job Object; its live token is re-queried (AppContainer flag, package SID,
integrity level, capability SIDs) and its Job membership is checked; only then
is its thread resumed. Any failure terminates the never-resumed process and
raises a stable ``APPCONTAINER_*`` error. This module never falls back to the
restricted-token launcher.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import subprocess
import types
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Sequence

from backend.app.core.errors import AppError
from backend.app.execution.process_supervisor import (
    IS_WINDOWS,
    JobSession,
    SupervisedProcess,
    close_job,
    create_job,
    list_pids,
)

# Process creation.
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
# ProcThreadAttributeValue(number, thread=FALSE, input=TRUE, additive=FALSE).
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009  # verified: spike 001
# Verified by backend/tests/execution/test_appcontainer.py (concurrent-run EOF test).
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
SE_GROUP_ENABLED = 0x00000004

# Token information classes (TOKEN_INFORMATION_CLASS).
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25
TokenIsAppContainer = 29
# Verified by the capability positive control in test_appcontainer.py.
TokenCapabilities = 30
TokenAppContainerSid = 31
LOW_INTEGRITY_RID = 0x1000

# HRESULT / Win32 results.
S_OK = 0
HRESULT_ALREADY_EXISTS = ctypes.c_long(0x800700B7).value
_HRESULT_FILE_NOT_FOUND = ctypes.c_long(0x80070002).value
_HRESULT_NOT_FOUND = ctypes.c_long(0x80070490).value
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_BAD_LENGTH = 24
_WAIT_FAILED = 0xFFFFFFFF
_RESUME_FAILED = 0xFFFFFFFF
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ_WRITE = 0x00000001 | 0x00000002
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80

FOLDERID_LocalAppData = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"
FOLDERID_Windows = "{F38BF404-1D43-42F2-9305-67DE0B28FC23}"

MAPPINGS_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppContainer\Mappings"
)

# Only capabilities Sentinel has tested; anything else is refused.
CAPABILITY_SIDS: Mapping[str, str] = types.MappingProxyType({"internetClient": "S-1-15-3-1"})

_PROFILE_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPVOID),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", wintypes.LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class TOKEN_GROUPS(ctypes.Structure):
    """Header of TOKEN_GROUPS; ``Groups`` is really ``GroupCount`` entries long."""

    _fields_ = [("GroupCount", wintypes.DWORD), ("Groups", SID_AND_ATTRIBUTES * 1)]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_text(cls, text: str) -> GUID:
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32")
    _shell32 = ctypes.WinDLL("shell32")
else:  # pragma: no cover - exercised by platform-guard tests
    _kernel32 = _advapi32 = _userenv = _ole32 = _shell32 = None


def _configure_bindings() -> None:
    if not IS_WINDOWS:
        return
    _userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        ctypes.POINTER(SID_AND_ATTRIBUTES), wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID),
    ]
    _userenv.CreateAppContainerProfile.restype = ctypes.c_long
    _userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID),
    ]
    _userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    _userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    _userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    _userenv.GetAppContainerFolderPath.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR),
    ]
    _userenv.GetAppContainerFolderPath.restype = ctypes.c_long

    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    _advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.FreeSid.argtypes = [wintypes.LPVOID]
    _advapi32.FreeSid.restype = wintypes.LPVOID
    _advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _advapi32.GetSidSubAuthorityCount.argtypes = [wintypes.LPVOID]
    _advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    _advapi32.GetSidSubAuthority.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    _advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)

    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID, ctypes.c_size_t,
        wintypes.LPVOID, wintypes.LPVOID,
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL,
        wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD,
    ]
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES),
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.IsProcessInJob.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL),
    ]
    _kernel32.IsProcessInJob.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    _kernel32.LocalFree.restype = wintypes.LPVOID
    _kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
    _kernel32.GetProcessId.restype = wintypes.DWORD
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    _ole32.CoTaskMemFree.argtypes = [wintypes.LPVOID]
    _ole32.CoTaskMemFree.restype = None
    _shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(wintypes.LPWSTR),
    ]
    _shell32.SHGetKnownFolderPath.restype = ctypes.c_long


_configure_bindings()


# --------------------------------------------------------------------------- errors


def appcontainer_unsupported() -> AppError:
    return AppError(
        "APPCONTAINER_UNSUPPORTED",
        "AppContainer launch is only supported on Windows.",
        status_code=501,
    )


def profile_failed(operation: str, hresult: int) -> AppError:
    return AppError(
        "APPCONTAINER_PROFILE_FAILED",
        f"The AppContainer profile operation '{operation}' failed.",
        status_code=500,
        details={"operation": operation, "hresult": f"{hresult & 0xFFFFFFFF:#010x}"},
    )


def launch_failed(reason: str) -> AppError:
    return AppError(
        "APPCONTAINER_LAUNCH_FAILED",
        "The AppContainer process could not be launched.",
        status_code=500,
        details={"reason": reason},
    )


def verification_failed(check: str) -> AppError:
    return AppError(
        "APPCONTAINER_VERIFICATION_FAILED",
        "The launched process did not have the required AppContainer boundary; it was "
        "terminated before it ran.",
        status_code=500,
        details={"check": check},
    )


def job_required(operation: str) -> AppError:
    return AppError(
        "APPCONTAINER_JOB_REQUIRED",
        "An AppContainer process must run inside a Sentinel Job Object; it was terminated "
        "before it ran.",
        status_code=500,
        details={"operation": operation},
    )


# --------------------------------------------------------------------------- helpers


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise appcontainer_unsupported()


def _last_error() -> int:
    return ctypes.get_last_error()


def _handle_value(handle: object) -> int:
    value = getattr(handle, "value", handle)
    return int(value or 0)


def _close(handle: int) -> None:
    if handle and handle != _INVALID_HANDLE_VALUE:
        _kernel32.CloseHandle(handle)


def validate_profile_name(name: str) -> str:
    """Require a lowercase profile name (Windows lowercases the folder and Moniker)."""

    if (not isinstance(name, str) or not 1 <= len(name) <= 64
            or not ("a" <= name[0] <= "z" or "0" <= name[0] <= "9")
            or any(char not in _PROFILE_NAME_CHARS for char in name)):
        raise ValueError("An AppContainer profile name must match ^[a-z0-9][a-z0-9._-]{0,63}$.")
    return name


def _sid_to_string(sid: int | wintypes.LPVOID) -> str:
    text = wintypes.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise OSError(_last_error(), "ConvertSidToStringSidW failed")
    try:
        return text.value or ""
    finally:
        _kernel32.LocalFree(ctypes.cast(text, wintypes.LPVOID))


def _string_to_sid(text: str) -> wintypes.LPVOID:
    """A LocalAlloc'd SID; the caller must ``LocalFree`` it."""

    sid = wintypes.LPVOID()
    if not _advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)):
        raise OSError(_last_error(), "ConvertStringSidToSidW failed")
    return sid


def _derive_sid_pointer(name: str) -> wintypes.LPVOID:
    """The package SID for ``name``; the caller must ``FreeSid`` it."""

    sid = wintypes.LPVOID()
    hresult = _userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    if hresult != S_OK:
        raise profile_failed("derive", hresult)
    return sid


def derive_package_sid(name: str) -> str:
    """String form of the package SID Windows derives from ``name``."""

    _require_windows()
    validate_profile_name(name)
    sid = _derive_sid_pointer(name)
    try:
        return _sid_to_string(sid)
    finally:
        _advapi32.FreeSid(sid)


@dataclass(frozen=True, slots=True)
class AppContainerProfile:
    name: str
    package_sid: str
    container_path: Path


def container_folder(package_sid: str) -> Path:
    """``%LOCALAPPDATA%\\Packages\\<profile>\\AC`` as Windows reports it."""

    _require_windows()
    path = wintypes.LPWSTR()
    hresult = _userenv.GetAppContainerFolderPath(package_sid, ctypes.byref(path))
    if hresult != S_OK:
        raise profile_failed("folder", hresult)
    try:
        return Path(path.value or "")
    finally:
        _ole32.CoTaskMemFree(ctypes.cast(path, wintypes.LPVOID))


def ensure_profile(name: str, *, display_name: str) -> tuple[AppContainerProfile, bool]:
    """Create the zero-capability profile ``name`` (or reuse it); returns (profile, created)."""

    _require_windows()
    validate_profile_name(name)
    sid = wintypes.LPVOID()
    created = True
    hresult = _userenv.CreateAppContainerProfile(
        name, display_name, display_name, None, 0, ctypes.byref(sid),
    )
    try:
        if hresult == HRESULT_ALREADY_EXISTS:
            created = False
            hresult = _userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
            if hresult != S_OK:
                raise profile_failed("derive", hresult)
        elif hresult != S_OK:
            raise profile_failed("create", hresult)
        package_sid = _sid_to_string(sid)
    finally:
        if sid:
            _advapi32.FreeSid(sid)
    return AppContainerProfile(name, package_sid, container_folder(package_sid)), created


def delete_profile(name: str) -> None:
    """Delete profile ``name``; an already-absent profile counts as success."""

    _require_windows()
    validate_profile_name(name)
    hresult = _userenv.DeleteAppContainerProfile(name)
    if hresult not in (S_OK, _HRESULT_FILE_NOT_FOUND, _HRESULT_NOT_FOUND):
        raise profile_failed("delete", hresult)


def profile_exists(name: str) -> bool:
    """Whether the per-user AppContainer Mappings key for ``name`` exists (read-only)."""

    _require_windows()
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, MAPPINGS_KEY + "\\" + derive_package_sid(name))
    except FileNotFoundError:
        return False
    winreg.CloseKey(key)
    return True


def _known_folder(folder_id: str) -> Path:
    _require_windows()
    guid = GUID.from_text(folder_id)
    path = wintypes.LPWSTR()
    hresult = _shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
    try:
        if hresult != S_OK or not path.value:
            raise launch_failed("known folder lookup failed")
        return Path(path.value)
    finally:
        if path:
            _ole32.CoTaskMemFree(ctypes.cast(path, wintypes.LPVOID))


def local_appdata_known_folder() -> Path:
    """The real per-user LocalAppData folder (never taken from ``os.environ``)."""

    return _known_folder(FOLDERID_LocalAppData)


def base_environment(
    container_path: str | Path, *, path_entries: Sequence[str | Path] = (),
) -> dict[str, str]:
    """The complete environment for an AppContainer child; no host variable is copied."""

    windows = _known_folder(FOLDERID_Windows)
    system32 = windows / "System32"
    temp = Path(container_path) / "Temp"
    temp.mkdir(parents=True, exist_ok=True)
    path = [str(entry) for entry in path_entries] + [str(system32)]
    return {
        "SystemRoot": str(windows),
        "windir": str(windows),
        "COMSPEC": str(system32 / "cmd.exe"),
        "PATH": os.pathsep.join(dict.fromkeys(path)),
        "LOCALAPPDATA": str(local_appdata_known_folder()),
        "TEMP": str(temp),
        "TMP": str(temp),
    }


def _is_reparse_point(path: str | Path) -> tuple[bool, bool]:
    """(is reparse point, is directory-type entry) for ``path`` without following it."""

    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(info.st_mode)
    return reparse, bool(attributes & stat.FILE_ATTRIBUTE_DIRECTORY)


def _remove_link(path: str | Path, is_directory: bool) -> None:
    if is_directory:
        os.rmdir(path)
    else:
        os.unlink(path)


def remove_tree_no_follow(path: str | Path) -> None:
    """Delete ``path`` without ever descending into a junction or symbolic link.

    A reparse point (at the top or anywhere below) is removed as a link only.
    Read-only entries (Git object files) get the write bit and one retry.
    """

    try:
        reparse, is_directory = _is_reparse_point(path)
    except FileNotFoundError:
        return
    if reparse:
        _remove_link(path, is_directory)
        return
    if not is_directory:
        try:
            os.unlink(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.unlink(path)
        return

    def handler(function: Callable[..., Any], target: str, error: BaseException) -> None:
        if isinstance(error, FileNotFoundError):
            return
        try:
            target_reparse, target_is_directory = _is_reparse_point(target)
        except FileNotFoundError:
            return
        if target_reparse:
            _remove_link(target, target_is_directory)
            return
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onexc=handler)


# --------------------------------------------------------------------------- token facts


@dataclass(frozen=True, slots=True)
class TokenFacts:
    is_appcontainer: bool
    integrity_rid: int
    package_sid: str
    capability_sids: tuple[str, ...]


def _token_information(token: int, information_class: int) -> ctypes.Array:
    needed = wintypes.DWORD()
    if _advapi32.GetTokenInformation(token, information_class, None, 0, ctypes.byref(needed)):
        size = max(needed.value, ctypes.sizeof(TOKEN_GROUPS))
    else:
        error = _last_error()
        if error not in (_ERROR_INSUFFICIENT_BUFFER, _ERROR_BAD_LENGTH):
            raise OSError(error, f"GetTokenInformation({information_class}) sizing failed")
        size = max(needed.value, ctypes.sizeof(TOKEN_GROUPS))
    buffer = ctypes.create_string_buffer(size)
    if not _advapi32.GetTokenInformation(
        token, information_class, buffer, size, ctypes.byref(needed)
    ):
        raise OSError(_last_error(), f"GetTokenInformation({information_class}) failed")
    return buffer


def _sid_last_rid(sid: int) -> int:
    count = _advapi32.GetSidSubAuthorityCount(sid)[0]
    return int(_advapi32.GetSidSubAuthority(sid, count - 1)[0])


def query_token_facts(process_handle: int) -> TokenFacts:
    """Re-query the live primary token of ``process_handle``."""

    _require_windows()
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
        raise OSError(_last_error(), "OpenProcessToken failed")
    try:
        is_appcontainer = wintypes.DWORD()
        returned = wintypes.DWORD()
        if not _advapi32.GetTokenInformation(
            token, TokenIsAppContainer, ctypes.byref(is_appcontainer),
            ctypes.sizeof(is_appcontainer), ctypes.byref(returned),
        ):
            raise OSError(_last_error(), "GetTokenInformation(TokenIsAppContainer) failed")
        # TOKEN_MANDATORY_LABEL: { SID_AND_ATTRIBUTES Label } followed by the SID.
        label = _token_information(token.value, TokenIntegrityLevel)
        integrity_rid = _sid_last_rid(ctypes.cast(label, ctypes.POINTER(wintypes.LPVOID))[0])
        package_sid = ""
        if is_appcontainer.value:
            # TOKEN_APPCONTAINER_INFORMATION: { PSID TokenAppContainer } followed by the SID.
            container = _token_information(token.value, TokenAppContainerSid)
            pointer = ctypes.cast(container, ctypes.POINTER(wintypes.LPVOID))[0]
            package_sid = _sid_to_string(pointer) if pointer else ""
        groups = _token_information(token.value, TokenCapabilities)
        count = ctypes.cast(groups, ctypes.POINTER(wintypes.DWORD))[0]
        capabilities: list[str] = []
        if count:
            entries = (SID_AND_ATTRIBUTES * count).from_buffer(groups, TOKEN_GROUPS.Groups.offset)
            capabilities = [_sid_to_string(entry.Sid) for entry in entries]
        return TokenFacts(
            is_appcontainer=bool(is_appcontainer.value),
            integrity_rid=integrity_rid,
            package_sid=package_sid,
            capability_sids=tuple(capabilities),
        )
    finally:
        _kernel32.CloseHandle(token)


def verify_boundary(
    facts: TokenFacts, *, expected_package_sid: str,
    expected_capability_sids: Sequence[str], job_member: bool,
) -> None:
    """Raise ``verification_failed(<check>)`` for the first unmet boundary fact."""

    if not facts.is_appcontainer:
        raise verification_failed("is_appcontainer")
    if not facts.package_sid or facts.package_sid.upper() != expected_package_sid.upper():
        raise verification_failed("package_sid")
    if facts.integrity_rid != LOW_INTEGRITY_RID:
        raise verification_failed("integrity")
    if ({sid.upper() for sid in facts.capability_sids}
            != {sid.upper() for sid in expected_capability_sids}):
        raise verification_failed("capabilities")
    if not job_member:
        raise verification_failed("job")


@dataclass(frozen=True, slots=True)
class AppContainerFacts:
    """Verified facts about one AppContainer launch, observed before resume."""

    profile_name: str
    package_sid: str
    is_appcontainer: bool
    integrity_rid: int
    capability_sids: tuple[str, ...]
    job_verified: bool
    verified_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "package_sid": self.package_sid,
            "is_appcontainer": self.is_appcontainer,
            "integrity_rid": f"{self.integrity_rid:#06x}",
            "capability_sids": list(self.capability_sids),
            "job_verified": self.job_verified,
            "verified_at": self.verified_at.isoformat(),
        }


class AppContainerProcess(SupervisedProcess):
    """A supervised process whose AppContainer boundary was verified before it ran."""

    def __init__(
        self, *, process_handle: int, pid: int, stdout: BinaryIO, stderr: BinaryIO,
        session: JobSession, appcontainer: AppContainerFacts,
    ) -> None:
        super().__init__(
            process_handle=process_handle, pid=pid, stdout=stdout, stderr=stderr,
            session=session, restricted_token_applied=False,
        )
        self.appcontainer = appcontainer


# --------------------------------------------------------------------------- launch seams


def _assign_to_job(job: int, process_handle: int) -> None:
    """Assign by the creation process handle (never a reopened pid)."""

    if not _kernel32.AssignProcessToJobObject(job, process_handle):
        raise job_required("assign")


def _process_in_job(process_handle: int, job: int) -> bool:
    result = wintypes.BOOL()
    if _kernel32.IsProcessInJob(process_handle, job, ctypes.byref(result)):
        return bool(result.value)
    # Only when the API call itself fails: fall back to the Job's pid list.
    pid = int(_kernel32.GetProcessId(process_handle))
    return bool(pid) and pid in list_pids(job)


def _pipe() -> tuple[int, int]:
    """(read, write): the write end is inheritable, the read end is not."""

    security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    read = wintypes.HANDLE()
    write = wintypes.HANDLE()
    if not _kernel32.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0):
        raise OSError(_last_error(), "CreatePipe failed")
    if not _kernel32.SetHandleInformation(read, HANDLE_FLAG_INHERIT, 0):
        error = _last_error()
        _kernel32.CloseHandle(read)
        _kernel32.CloseHandle(write)
        raise OSError(error, "SetHandleInformation failed")
    return _handle_value(read), _handle_value(write)


def _null_input() -> int:
    security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    handle = _handle_value(_kernel32.CreateFileW(
        "NUL", _GENERIC_READ, _FILE_SHARE_READ_WRITE, ctypes.byref(security),
        _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None,
    ))
    if not handle or handle == _INVALID_HANDLE_VALUE:
        raise OSError(_last_error(), "CreateFileW(NUL) failed")
    return handle


def _environment_block(env: Mapping[str, str]) -> ctypes.Array:
    text = "".join(
        f"{key}={value}\0" for key, value in sorted(env.items(), key=lambda item: item[0].upper())
    ) + "\0"
    return ctypes.create_unicode_buffer(text, len(text))


def _terminate_unresumed(job: int, process_handle: int) -> None:
    if job:
        _kernel32.TerminateJobObject(job, 1)
    if process_handle:
        _kernel32.TerminateProcess(process_handle, 1)
        _kernel32.WaitForSingleObject(process_handle, 5000)


def spawn_appcontainer_supervised(
    argv: Sequence[str], *, cwd: str | Path, env: Mapping[str, str],
    redact: Callable[[str], str], profile_name: str, expected_package_sid: str,
    capabilities: Sequence[str],
) -> AppContainerProcess:
    """Launch ``argv`` in AppContainer ``profile_name``; verify its live token before it runs."""

    if not IS_WINDOWS:
        raise appcontainer_unsupported()
    import msvcrt

    arguments = [str(item) for item in argv]
    if not arguments or not os.path.isabs(arguments[0]) or not Path(arguments[0]).drive:
        raise launch_failed("the executable must be an absolute path")
    if not any(key.upper() == "LOCALAPPDATA" for key in env):
        raise launch_failed("the environment must contain LOCALAPPDATA")
    unknown = [name for name in capabilities if name not in CAPABILITY_SIDS]
    if unknown:
        raise launch_failed("an unknown capability was requested")
    try:
        validate_profile_name(profile_name)
    except ValueError as exc:
        raise launch_failed("the profile name is invalid") from exc
    requested_sids = tuple(CAPABILITY_SIDS[name] for name in capabilities)

    package_sid = _derive_sid_pointer(profile_name)
    capability_pointers: list[wintypes.LPVOID] = []
    attribute_buffer: ctypes.Array | None = None
    attribute_list_ready = False
    stdout_read = stdout_write = stderr_read = stderr_write = null_input = 0
    process_info = PROCESS_INFORMATION()
    job = 0
    transferred = False
    try:
        if _sid_to_string(package_sid).upper() != expected_package_sid.upper():
            raise verification_failed("package_sid")
        try:
            job = create_job()
        except AppError as exc:
            raise job_required("create") from exc

        try:
            stdout_read, stdout_write = _pipe()
            stderr_read, stderr_write = _pipe()
            null_input = _null_input()

            capability_array = (SID_AND_ATTRIBUTES * max(1, len(requested_sids)))()
            for index, text in enumerate(requested_sids):
                pointer = _string_to_sid(text)
                capability_pointers.append(pointer)
                capability_array[index].Sid = pointer
                capability_array[index].Attributes = SE_GROUP_ENABLED
            security_capabilities = SECURITY_CAPABILITIES(
                package_sid,
                ctypes.cast(capability_array, ctypes.POINTER(SID_AND_ATTRIBUTES))
                if requested_sids else None,
                len(requested_sids), 0,
            )
            inherited = (wintypes.HANDLE * 3)(null_input, stdout_write, stderr_write)

            size = ctypes.c_size_t()
            _kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            attribute_buffer = ctypes.create_string_buffer(size.value)
            if not _kernel32.InitializeProcThreadAttributeList(
                attribute_buffer, 2, 0, ctypes.byref(size)
            ):
                raise OSError(_last_error(), "InitializeProcThreadAttributeList failed")
            attribute_list_ready = True
            if not _kernel32.UpdateProcThreadAttribute(
                attribute_buffer, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                ctypes.byref(security_capabilities), ctypes.sizeof(security_capabilities),
                None, None,
            ):
                raise OSError(_last_error(), "UpdateProcThreadAttribute(capabilities) failed")
            if not _kernel32.UpdateProcThreadAttribute(
                attribute_buffer, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                ctypes.byref(inherited), ctypes.sizeof(inherited), None, None,
            ):
                raise OSError(_last_error(), "UpdateProcThreadAttribute(handle list) failed")

            startup = STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
            startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
            startup.StartupInfo.hStdInput = null_input
            startup.StartupInfo.hStdOutput = stdout_write
            startup.StartupInfo.hStdError = stderr_write
            startup.lpAttributeList = ctypes.cast(attribute_buffer, wintypes.LPVOID)
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
            environment = _environment_block(env)
            flags = (EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED
                     | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW)
            # bInheritHandles=TRUE is only safe because the handle list restricts
            # inheritance to exactly NUL stdin and this launch's own pipe ends.
            if not _kernel32.CreateProcessW(
                arguments[0], command, None, None, True, flags, environment, str(cwd),
                ctypes.byref(startup), ctypes.byref(process_info),
            ):
                raise launch_failed(f"CreateProcessW failed (Windows error {_last_error()})")
        except OSError as exc:
            raise launch_failed(f"{exc.strerror or 'launch preparation failed'}") from exc

        process_handle = _handle_value(process_info.hProcess)
        try:
            _assign_to_job(job, process_handle)
            facts = query_token_facts(process_handle)
            job_member = _process_in_job(process_handle, job)
            verify_boundary(
                facts, expected_package_sid=expected_package_sid,
                expected_capability_sids=requested_sids, job_member=job_member,
            )
            verified_at = datetime.now(UTC)
            if _kernel32.ResumeThread(process_info.hThread) == _RESUME_FAILED:
                raise launch_failed(f"ResumeThread failed (Windows error {_last_error()})")
        except BaseException as exc:
            _terminate_unresumed(job, process_handle)
            if isinstance(exc, OSError):
                raise launch_failed(exc.strerror or "boundary verification failed") from exc
            raise

        _close(_handle_value(process_info.hThread))
        process_info.hThread = None
        _close(stdout_write)
        stdout_write = 0
        _close(stderr_write)
        stderr_write = 0
        stdout_file = os.fdopen(
            msvcrt.open_osfhandle(stdout_read, os.O_RDONLY | os.O_BINARY), "rb", 0
        )
        stdout_read = 0
        try:
            stderr_file = os.fdopen(
                msvcrt.open_osfhandle(stderr_read, os.O_RDONLY | os.O_BINARY), "rb", 0
            )
        except BaseException:
            stdout_file.close()
            raise
        stderr_read = 0
        pid = int(process_info.dwProcessId)
        result = AppContainerProcess(
            process_handle=process_handle, pid=pid, stdout=stdout_file, stderr=stderr_file,
            session=JobSession(job, pid, redact=redact),
            appcontainer=AppContainerFacts(
                profile_name=profile_name,
                package_sid=facts.package_sid,
                is_appcontainer=facts.is_appcontainer,
                integrity_rid=facts.integrity_rid,
                capability_sids=facts.capability_sids,
                job_verified=job_member,
                verified_at=verified_at,
            ),
        )
        transferred = True
        return result
    finally:
        if attribute_list_ready and attribute_buffer is not None:
            _kernel32.DeleteProcThreadAttributeList(attribute_buffer)
        for pointer in capability_pointers:
            _kernel32.LocalFree(pointer)
        _advapi32.FreeSid(package_sid)
        for handle in (stdout_read, stdout_write, stderr_read, stderr_write, null_input):
            _close(handle)
        if process_info.hThread:
            _close(_handle_value(process_info.hThread))
        if not transferred:
            if process_info.hProcess:
                _terminate_unresumed(job, _handle_value(process_info.hProcess))
                _close(_handle_value(process_info.hProcess))
            if job:
                close_job(job)
