"""Windows process-tree supervision and reduced-authority process creation.

The implementation deliberately makes two bounded claims:

* a successful :class:`SupervisedProcess` launch is assigned to a Windows Job
  Object configured with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``; and
* the launched top-level process uses a restricted primary token with maximum
  privileges disabled. The caller's integrity level is retained because a Low
  token cannot write an ordinary Medium-integrity repository. This is reduced
  privilege, not filesystem/network isolation and not a sandbox.

No non-Windows fallback pretends to provide either property.  Callers may use
their existing unsupervised launcher there, but must surface that limitation.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, Sequence

from backend.app.contracts.models import DescendantProcess
from backend.app.core.errors import AppError


IS_WINDOWS = sys.platform == "win32"

# Process/job/token access and creation flags.
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_TOKEN_ASSIGN_PRIMARY = 0x0001
_TOKEN_DUPLICATE = 0x0002
_TOKEN_QUERY = 0x0008
_TOKEN_ADJUST_DEFAULT = 0x0080
_DISABLE_MAX_PRIVILEGE = 0x1
_SE_GROUP_INTEGRITY = 0x20
_TOKEN_INTEGRITY_LEVEL = 25
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_PROCESS_ID_LIST = 3
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_STILL_ACTIVE = 259
_WAIT_TIMEOUT = 258
_ERROR_MORE_DATA = 234
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
else:  # pragma: no cover - exercised by platform-guard tests
    _kernel32 = _advapi32 = _ntdll = None


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _STARTUPINFOW(ctypes.Structure):
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
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", _SID_AND_ATTRIBUTES)]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


def _configure_bindings() -> None:
    if not IS_WINDOWS:
        return
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.DWORD,
    ]
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(_SECURITY_ATTRIBUTES), wintypes.DWORD, wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL

    _advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.CreateRestrictedToken.restype = wintypes.BOOL
    _advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID),
    ]
    _advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi32.GetLengthSid.argtypes = [wintypes.LPVOID]
    _advapi32.GetLengthSid.restype = wintypes.DWORD
    _advapi32.SetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _advapi32.SetTokenInformation.restype = wintypes.BOOL
    _advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR,
        wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD,
        wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    _advapi32.CreateProcessAsUserW.restype = wintypes.BOOL
    _ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    _ntdll.NtQueryInformationProcess.restype = ctypes.c_long


_configure_bindings()


def _handle_value(handle: object) -> int:
    value = getattr(handle, "value", handle)
    return int(value)


def _windows_error(operation: str) -> AppError:
    return AppError(
        "PROCESS_SUPERVISION_FAILED",
        f"{operation} failed (Windows error {ctypes.get_last_error()}).",
    )


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise AppError(
            "PROCESS_SUPERVISION_UNSUPPORTED",
            "Process-tree supervision and reduced-authority launch are only supported on Windows.",
            status_code=501,
        )


def create_job() -> int:
    """Create a kill-on-close Job Object and return its owned handle."""

    _require_windows()
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise _windows_error("CreateJobObjectW")
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _kernel32.SetInformationJobObject(
        handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info), ctypes.sizeof(info),
    ):
        _kernel32.CloseHandle(handle)
        raise _windows_error("SetInformationJobObject")
    return _handle_value(handle)


def assign_process(job: int, pid: int) -> None:
    """Assign ``pid`` to ``job`` using only the rights Windows requires."""

    _require_windows()
    process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not process:
        raise _windows_error("OpenProcess for Job Object assignment")
    try:
        if not _kernel32.AssignProcessToJobObject(job, process):
            raise _windows_error("AssignProcessToJobObject")
    finally:
        _kernel32.CloseHandle(process)


def list_pids(job: int) -> list[int]:
    """Return the current PIDs assigned to ``job``."""

    _require_windows()
    size = 4096
    while size <= 1_048_576:
        buffer = ctypes.create_string_buffer(size)
        returned = wintypes.DWORD()
        if _kernel32.QueryInformationJobObject(
            job, _JOB_OBJECT_BASIC_PROCESS_ID_LIST, buffer, size, ctypes.byref(returned)
        ):
            assigned = ctypes.c_uint32.from_buffer(buffer, 0).value
            listed = ctypes.c_uint32.from_buffer(buffer, 4).value
            count = min(assigned, listed, (size - 8) // ctypes.sizeof(ctypes.c_size_t))
            array = (ctypes.c_size_t * count).from_buffer(buffer, 8)
            return [int(array[index]) for index in range(count)]
        if ctypes.get_last_error() != _ERROR_MORE_DATA:
            raise _windows_error("QueryInformationJobObject")
        size *= 2
    raise AppError("PROCESS_SUPERVISION_FAILED", "The Job Object process list was too large.")


def terminate_job(job: int) -> None:
    _require_windows()
    if not _kernel32.TerminateJobObject(job, 1):
        raise _windows_error("TerminateJobObject")


def close_job(job: int) -> None:
    if job and IS_WINDOWS:
        _kernel32.CloseHandle(job)


def is_process_running(pid: int) -> bool:
    """Return whether ``pid`` is still active, using a query-only handle."""

    _require_windows()
    process = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return False
    try:
        code = wintypes.DWORD()
        return bool(
            _kernel32.GetExitCodeProcess(process, ctypes.byref(code))
            and code.value == _STILL_ACTIVE
        )
    finally:
        _kernel32.CloseHandle(process)


def _parent_pids() -> dict[int, int]:
    parents: dict[int, int] = {}
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or _handle_value(snapshot) == _INVALID_HANDLE_VALUE:
        return parents
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return parents


def _image_path(process: int) -> str | None:
    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not _kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
        return None
    return buffer.value


def _command_line(process: int) -> str | None:
    # ProcessCommandLineInformation (60) returns a UNICODE_STRING followed by
    # its buffer on supported Windows versions. Failure is an honest unknown.
    size = 65536
    buffer = ctypes.create_string_buffer(size)
    returned = wintypes.ULONG()
    status = _ntdll.NtQueryInformationProcess(
        process, 60, buffer, size, ctypes.byref(returned)
    )
    if status != 0:
        return None
    value = ctypes.cast(buffer, ctypes.POINTER(_UNICODE_STRING)).contents
    if not value.Buffer or not value.Length:
        return None
    return ctypes.wstring_at(value.Buffer, value.Length // ctypes.sizeof(wintypes.WCHAR))


@dataclass
class _Observed:
    record: DescendantProcess
    handle: int | None


class JobSession:
    """One Job Object plus the descendant evidence observed while it is live."""

    def __init__(self, job: int, top_level_pid: int, *, redact: Callable[[str], str]) -> None:
        self.job = job
        self.top_level_pid = top_level_pid
        self._redact = redact
        self._observed: dict[int, _Observed] = {}

    def observe(self) -> list[DescendantProcess]:
        now = datetime.now(UTC)
        parents = _parent_pids()
        try:
            current = set(list_pids(self.job))
        except AppError:
            return self.records
        for pid in current:
            if pid == self.top_level_pid or pid in self._observed:
                continue
            handle = _kernel32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid
            )
            path = _image_path(handle) if handle else None
            raw_command_line = _command_line(handle) if handle else None
            command_line = self._redact(raw_command_line) if raw_command_line else None
            attributed = path is not None
            self._observed[pid] = _Observed(
                DescendantProcess(
                    pid=pid,
                    parent_pid=parents.get(pid),
                    executable_path=path,
                    command_line=command_line,
                    started_at=now,
                    attributed=attributed,
                    attribution_reason=None if attributed else (
                        "process exited before identity could be resolved"
                    ),
                ),
                _handle_value(handle) if handle else None,
            )
        for pid, observed in self._observed.items():
            if observed.record.terminated_at is not None or pid in current:
                continue
            code = wintypes.DWORD()
            exit_code = None
            if observed.handle and _kernel32.GetExitCodeProcess(observed.handle, ctypes.byref(code)):
                exit_code = None if code.value == _STILL_ACTIVE else int(code.value)
            observed.record = observed.record.model_copy(
                update={"terminated_at": now, "exit_code": exit_code}
            )
        return self.records

    @property
    def records(self) -> list[DescendantProcess]:
        return [self._observed[pid].record for pid in sorted(self._observed)]

    def terminate(self) -> int:
        self.observe()
        active = sum(item.record.terminated_at is None for item in self._observed.values())
        # Include the top-level process if it is still a member of the job.
        try:
            active += int(self.top_level_pid in list_pids(self.job))
        except AppError:
            pass
        terminate_job(self.job)
        self.observe()
        return active

    def close(self) -> None:
        now = datetime.now(UTC)
        for item in self._observed.values():
            if item.record.terminated_at is None:
                item.record = item.record.model_copy(update={"terminated_at": now})
        close_job(self.job)
        self.job = 0
        for item in self._observed.values():
            if item.handle:
                _kernel32.CloseHandle(item.handle)
                item.handle = None


def _create_restricted_token() -> int:
    current = wintypes.HANDLE()
    restricted = wintypes.HANDLE()
    desired = _TOKEN_ASSIGN_PRIMARY | _TOKEN_DUPLICATE | _TOKEN_QUERY | _TOKEN_ADJUST_DEFAULT
    if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), desired, ctypes.byref(current)):
        raise _windows_error("OpenProcessToken")
    try:
        if not _advapi32.CreateRestrictedToken(
            current, _DISABLE_MAX_PRIVILEGE, 0, None, 0, None, 0, None,
            ctypes.byref(restricted),
        ):
            raise _windows_error("CreateRestrictedToken")
    finally:
        _kernel32.CloseHandle(current)

    return _handle_value(restricted)


def _pipe() -> tuple[int, int]:
    security = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
    read = wintypes.HANDLE()
    write = wintypes.HANDLE()
    if not _kernel32.CreatePipe(ctypes.byref(read), ctypes.byref(write), ctypes.byref(security), 0):
        raise _windows_error("CreatePipe")
    if not _kernel32.SetHandleInformation(read, _HANDLE_FLAG_INHERIT, 0):
        _kernel32.CloseHandle(read)
        _kernel32.CloseHandle(write)
        raise _windows_error("SetHandleInformation")
    return _handle_value(read), _handle_value(write)


class SupervisedProcess:
    """Small ``subprocess.Popen``-compatible wrapper used by bounded capture."""

    def __init__(
        self, *, process_handle: int, pid: int, stdout: BinaryIO, stderr: BinaryIO,
        session: JobSession | None, restricted_token_applied: bool,
    ) -> None:
        self._handle = process_handle
        self.pid = pid
        self.stdout = stdout
        self.stderr = stderr
        self.session = session
        self.restricted_token_applied = restricted_token_applied
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise _windows_error("GetExitCodeProcess")
        if code.value == _STILL_ACTIVE:
            return None
        self.returncode = int(code.value)
        return self.returncode

    def kill(self) -> None:
        if self.session is not None and self.session.job:
            self.session.terminate()
        elif self.poll() is None and not _kernel32.TerminateProcess(self._handle, 1):
            raise _windows_error("TerminateProcess")

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        result = _kernel32.WaitForSingleObject(self._handle, milliseconds)
        if result == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("supervised process", timeout)
        return self.poll() or 0

    def close(self) -> None:
        if self.session is not None:
            self.session.observe()
            self.session.close()  # kill-on-close cleans any remaining descendants
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = 0


def spawn_restricted_supervised(
    argv: Sequence[str], *, cwd: str | Path, env: Mapping[str, str],
    redact: Callable[[str], str],
) -> SupervisedProcess:
    """Create a suspended restricted process, assign it to a Job, then resume it.

    Restricted-token creation or launch failure is fatal: this function never
    silently falls back to an unrestricted process.  Job creation/assignment is
    independently best-effort so the caller can honestly report
    ``descendant_control_available=False`` while retaining reduced authority.
    """

    _require_windows()
    import msvcrt

    token = _create_restricted_token()
    stdout_read = stdout_write = stderr_read = stderr_write = 0
    null_input = 0
    process_info = _PROCESS_INFORMATION()
    job: int | None = None
    transferred = False
    stdout_file: BinaryIO | None = None
    stderr_file: BinaryIO | None = None
    try:
        stdout_read, stdout_write = _pipe()
        stderr_read, stderr_write = _pipe()
        security = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
        null_input = _handle_value(_kernel32.CreateFileW(
            "NUL", 0x80000000, 0x00000001 | 0x00000002, ctypes.byref(security),
            3, 0x80, None,
        ))
        if not null_input or null_input == _INVALID_HANDLE_VALUE:
            raise _windows_error("CreateFileW(NUL)")
        startup = _STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = _STARTF_USESTDHANDLES
        startup.hStdInput = null_input
        startup.hStdOutput = stdout_write
        startup.hStdError = stderr_write
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
        environment = "\0".join(
            f"{key}={value}" for key, value in sorted(env.items(), key=lambda item: item[0].upper())
        ) + "\0\0"
        environment_buffer = ctypes.create_unicode_buffer(environment)
        if not _advapi32.CreateProcessAsUserW(
            token, str(argv[0]), command, None, None, True,
            _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT,
            environment_buffer, str(cwd), ctypes.byref(startup), ctypes.byref(process_info),
        ):
            raise _windows_error("CreateProcessAsUserW")
        try:
            job = create_job()
            assign_process(job, int(process_info.dwProcessId))
        except AppError:
            if job:
                close_job(job)
            job = None
        if _kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
            _kernel32.TerminateProcess(process_info.hProcess, 1)
            raise _windows_error("ResumeThread")
        _kernel32.CloseHandle(process_info.hThread)
        process_info.hThread = None
        _kernel32.CloseHandle(stdout_write)
        stdout_write = 0
        _kernel32.CloseHandle(stderr_write)
        stderr_write = 0
        stdout_file = os.fdopen(
            msvcrt.open_osfhandle(stdout_read, os.O_RDONLY | os.O_BINARY), "rb", 0
        )
        stdout_read = 0
        stderr_file = os.fdopen(
            msvcrt.open_osfhandle(stderr_read, os.O_RDONLY | os.O_BINARY), "rb", 0
        )
        stderr_read = 0
        session = JobSession(job, int(process_info.dwProcessId), redact=redact) if job else None
        result = SupervisedProcess(
            process_handle=_handle_value(process_info.hProcess), pid=int(process_info.dwProcessId),
            stdout=stdout_file, stderr=stderr_file, session=session,
            restricted_token_applied=True,
        )
        transferred = True
        return result
    finally:
        _kernel32.CloseHandle(token)
        for handle in (stdout_read, stdout_write, stderr_read, stderr_write, null_input):
            if handle and handle != _INVALID_HANDLE_VALUE:
                _kernel32.CloseHandle(handle)
        if process_info.hThread:
            _kernel32.CloseHandle(process_info.hThread)
        # Ownership of hProcess transfers to SupervisedProcess only on success.
        if process_info.hProcess and not transferred:
            _kernel32.TerminateProcess(process_info.hProcess, 1)
            _kernel32.CloseHandle(process_info.hProcess)
        if not transferred:
            if job:
                close_job(job)
            for stream in (stdout_file, stderr_file):
                if stream is not None:
                    stream.close()
