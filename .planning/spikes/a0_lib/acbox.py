"""A0 spike helper: launch a process inside a Windows AppContainer (documented API).

CreateAppContainerProfile / DeriveAppContainerSidFromAppContainerName (userenv),
STARTUPINFOEXW + PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, CREATE_SUSPENDED,
Job Object assignment before ResumeThread, and an independent re-query of the
live child token. Spike code only: not product code.
"""

from __future__ import annotations

import ctypes
import msvcrt
import os
import time
from ctypes import wintypes
from dataclasses import dataclass, field

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x1
SE_GROUP_ENABLED = 0x4
TOKEN_QUERY = 0x8
TokenIntegrityLevel = 25
TokenIsAppContainer = 29
TokenAppContainerSid = 31
JobObjectExtendedLimitInformation = 9
JobObjectBasicProcessIdList = 3
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
HRESULT_ALREADY_EXISTS = ctypes.c_long(0x800700B7).value
WAIT_TIMEOUT = 0x102

CAPABILITY_SIDS = {
    "internetClient": "S-1-15-3-1",
    "internetClientServer": "S-1-15-3-2",
    "privateNetworkClientServer": "S-1-15-3-3",
}


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
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPVOID), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", wintypes.LPVOID)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _bind() -> None:
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        ctypes.POINTER(SID_AND_ATTRIBUTES), wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID)]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    userenv.GetAppContainerFolderPath.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPWSTR)]
    userenv.GetAppContainerFolderPath.restype = ctypes.c_long
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSidSubAuthorityCount.argtypes = [wintypes.LPVOID]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthority.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID, ctypes.c_size_t,
        wintypes.LPVOID, wintypes.LPVOID]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL,
        wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR, ctypes.POINTER(STARTUPINFOEXW),
        ctypes.POINTER(PROCESS_INFORMATION)]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]
    kernel32.CreatePipe.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID


_bind()


def _check(ok: object, what: str) -> None:
    if not ok:
        raise OSError(ctypes.get_last_error(), f"{what} failed: {ctypes.FormatError(ctypes.get_last_error())}")


def _sid_from_string(text: str) -> wintypes.LPVOID:
    sid = wintypes.LPVOID()
    _check(advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)), "ConvertStringSidToSidW")
    return sid


def sid_to_string(sid: wintypes.LPVOID | int) -> str:
    text = wintypes.LPWSTR()
    _check(advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)), "ConvertSidToStringSidW")
    try:
        return text.value or ""
    finally:
        kernel32.LocalFree(text)


def ensure_profile(name: str, capabilities: tuple[str, ...] = ()) -> tuple[wintypes.LPVOID, bool]:
    """Create (or derive) the AppContainer profile; returns (sid, created)."""

    sid = wintypes.LPVOID()
    caps = (SID_AND_ATTRIBUTES * max(1, len(capabilities)))()
    for index, cap in enumerate(capabilities):
        caps[index].Sid = _sid_from_string(CAPABILITY_SIDS[cap])
        caps[index].Attributes = SE_GROUP_ENABLED
    hr = userenv.CreateAppContainerProfile(name, name, "Sentinel A0 spike", caps if capabilities else None,
                                           len(capabilities), ctypes.byref(sid))
    if hr == 0:
        return sid, True
    if hr != HRESULT_ALREADY_EXISTS:
        raise OSError(hr, f"CreateAppContainerProfile HRESULT {hr & 0xFFFFFFFF:#010x}")
    hr = userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    if hr != 0:
        raise OSError(hr, f"DeriveAppContainerSidFromAppContainerName HRESULT {hr & 0xFFFFFFFF:#010x}")
    return sid, False


def delete_profile(name: str) -> int:
    return userenv.DeleteAppContainerProfile(name)


def container_folder(sid: wintypes.LPVOID) -> str:
    path = wintypes.LPWSTR()
    hr = userenv.GetAppContainerFolderPath(sid_to_string(sid), ctypes.byref(path))
    if hr != 0:
        raise OSError(hr, f"GetAppContainerFolderPath HRESULT {hr & 0xFFFFFFFF:#010x}")
    return path.value or ""


def _token_facts(process: int) -> dict[str, object]:
    token = wintypes.HANDLE()
    _check(advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)), "OpenProcessToken")
    try:
        is_ac = wintypes.DWORD()
        size = wintypes.DWORD()
        _check(advapi32.GetTokenInformation(token, TokenIsAppContainer, ctypes.byref(is_ac),
                                            ctypes.sizeof(is_ac), ctypes.byref(size)), "TokenIsAppContainer")
        buf = ctypes.create_string_buffer(256)
        _check(advapi32.GetTokenInformation(token, TokenIntegrityLevel, buf, 256, ctypes.byref(size)),
               "TokenIntegrityLevel")
        label_sid = ctypes.cast(buf, ctypes.POINTER(wintypes.LPVOID))[0]
        count = advapi32.GetSidSubAuthorityCount(label_sid)[0]
        rid = advapi32.GetSidSubAuthority(label_sid, count - 1)[0]
        package_sid = ""
        if is_ac.value:
            buf2 = ctypes.create_string_buffer(256)
            _check(advapi32.GetTokenInformation(token, TokenAppContainerSid, buf2, 256, ctypes.byref(size)),
                   "TokenAppContainerSid")
            package_sid = sid_to_string(ctypes.cast(buf2, ctypes.POINTER(wintypes.LPVOID))[0])
        return {"is_appcontainer": bool(is_ac.value), "integrity_rid": hex(rid), "package_sid": package_sid}
    finally:
        kernel32.CloseHandle(token)


def _job_pids(job: int) -> list[int]:
    class _List(ctypes.Structure):
        _fields_ = [("Assigned", wintypes.DWORD), ("Listed", wintypes.DWORD),
                    ("Ids", ctypes.c_size_t * 64)]
    data = _List()
    _check(kernel32.QueryInformationJobObject(job, JobObjectBasicProcessIdList, ctypes.byref(data),
                                              ctypes.sizeof(data), None), "QueryInformationJobObject")
    return [int(data.Ids[i]) for i in range(data.Listed)]


def _env_block(env: dict[str, str]) -> ctypes.Array:
    text = "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
    return ctypes.create_unicode_buffer(text, len(text))


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    token: dict[str, object]
    job_pids_before_resume: list[int]
    child_pid: int
    timed_out: bool = False
    notes: list[str] = field(default_factory=list)


def run(command_line: str, *, cwd: str, sid: wintypes.LPVOID | None,
        capabilities: tuple[str, ...] = (), env: dict[str, str] | None = None,
        timeout: float = 60.0) -> RunResult:
    """Run `command_line`; inside the AppContainer `sid` when given, else normally (control)."""

    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    read_end, write_end = wintypes.HANDLE(), wintypes.HANDLE()
    _check(kernel32.CreatePipe(ctypes.byref(read_end), ctypes.byref(write_end), ctypes.byref(sa), 0), "CreatePipe")
    _check(kernel32.SetHandleInformation(read_end, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation")

    info = STARTUPINFOEXW()
    info.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    info.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    info.StartupInfo.hStdOutput = write_end
    info.StartupInfo.hStdError = write_end
    flags = CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT
    attr_buf = None
    caps_array = None
    security = None
    if sid is not None:
        size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attr_buf = ctypes.create_string_buffer(size.value)
        _check(kernel32.InitializeProcThreadAttributeList(attr_buf, 1, 0, ctypes.byref(size)),
               "InitializeProcThreadAttributeList")
        caps_array = (SID_AND_ATTRIBUTES * max(1, len(capabilities)))()
        for index, cap in enumerate(capabilities):
            caps_array[index].Sid = _sid_from_string(CAPABILITY_SIDS[cap])
            caps_array[index].Attributes = SE_GROUP_ENABLED
        security = SECURITY_CAPABILITIES(sid, caps_array if capabilities else None, len(capabilities), 0)
        _check(kernel32.UpdateProcThreadAttribute(attr_buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                                  ctypes.byref(security), ctypes.sizeof(security), None, None),
               "UpdateProcThreadAttribute")
        info.lpAttributeList = ctypes.cast(attr_buf, wintypes.LPVOID)
        flags |= EXTENDED_STARTUPINFO_PRESENT

    block = _env_block(env if env is not None else dict(os.environ))
    cmd = ctypes.create_unicode_buffer(command_line)
    pi = PROCESS_INFORMATION()
    ok = kernel32.CreateProcessW(None, cmd, None, None, True, flags, block, cwd,
                                 ctypes.byref(info), ctypes.byref(pi))
    err = ctypes.get_last_error()
    kernel32.CloseHandle(write_end)
    if attr_buf is not None:
        kernel32.DeleteProcThreadAttributeList(attr_buf)
    if not ok:
        kernel32.CloseHandle(read_end)
        raise OSError(err, f"CreateProcessW failed: {ctypes.FormatError(err)}")

    job = kernel32.CreateJobObjectW(None, None)
    _check(job, "CreateJobObjectW")
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _check(kernel32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(limits),
                                            ctypes.sizeof(limits)), "SetInformationJobObject")
    _check(kernel32.AssignProcessToJobObject(job, pi.hProcess), "AssignProcessToJobObject")
    token = _token_facts(pi.hProcess)
    before = _job_pids(job)
    if sid is not None and not token["is_appcontainer"]:
        kernel32.TerminateJobObject(job, 1)
        raise RuntimeError("child token is not an AppContainer token; refusing to resume")
    kernel32.ResumeThread(pi.hThread)

    reader = os.fdopen(msvcrt.open_osfhandle(read_end.value, os.O_RDONLY), "rb")
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    import threading
    thread = threading.Thread(target=lambda: chunks.append(reader.read()), daemon=True)
    thread.start()
    timed_out = kernel32.WaitForSingleObject(pi.hProcess, int(timeout * 1000)) == WAIT_TIMEOUT
    if timed_out:
        kernel32.TerminateJobObject(job, 1)
    thread.join(max(0.0, deadline - time.monotonic()) + 5)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
    kernel32.TerminateJobObject(job, 0)
    for handle in (pi.hThread, pi.hProcess, job):
        kernel32.CloseHandle(handle)
    output = b"".join(chunks).decode("utf-8", errors="replace")
    return RunResult(code.value, output, token, before, pi.dwProcessId, timed_out)
