"""Top-level process suspend/resume (LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md Part A).

Windows-first, honestly bounded: binds ``ntdll.dll``'s undocumented but
stable ``NtSuspendProcess``/``NtResumeProcess`` -- the same load-bearing APIs
mainstream Windows tooling (Process Explorer, Visual Studio's "Break All")
uses for exactly this operation. This matches the ctypes-to-a-system-DLL
pattern this codebase already trusts elsewhere: ``credentials/windows_store.py``
binds ``advapi32.dll`` for Credential Manager, and ``execution/signature.py``
shells out to ``signtool.exe`` for Authenticode checks -- both "real but
platform-scoped" rather than a fabricated cross-platform claim.

Scope, deliberately narrow (see the plan's A.1): only the single top-level
process identified by a PID is suspended or resumed. No process-tree
enumeration is performed here and none is implied -- a descendant that has
already spawned its own children is not suspended along with its parent.
This module grants no attribution or cleanup capability over descendants and
makes no claim about them.

Non-Windows platforms raise ``AppError("AGENT_PAUSE_UNSUPPORTED", ...)``,
never a fabricated success -- the same honesty tier as
``execution/signature.py``'s ``"unknown"`` result on a check it cannot
perform.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from backend.app.core.errors import AppError

# PROCESS_SUSPEND_RESUME only -- the least-privilege handle for this
# operation, not PROCESS_ALL_ACCESS, matching this codebase's established
# least-privilege convention for subprocess execution (shell=False, argument
# arrays, minimal environment).
_PROCESS_SUSPEND_RESUME = 0x0800
# Added to the handle opened for suspend only, so the post-suspend check
# below can call GetProcessTimes. Still far short of PROCESS_ALL_ACCESS.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# A found-in-production gap (THREAT_MODEL_FINDINGS.md): on at least one
# machine, NtSuspendProcess returns STATUS_SUCCESS while the target keeps
# running unsuspended. The status code alone is not proof of effect, so
# suspend_process independently confirms the process stopped consuming CPU
# before returning -- this module's contract is to never report a
# fabricated success, the same bar signature.py holds for "unknown" checks.
_SUSPEND_VERIFY_WINDOW_SECONDS = 0.1
# Generous slack for the syscall's own tail end (in-flight instructions at
# the moment of suspension) -- 15ms of CPU time is well above that noise
# floor but far below what a genuinely still-running loop accrues in 100ms.
_SUSPEND_VERIFY_TOLERANCE_100NS = 150_000

_is_windows = sys.platform == "win32"
_ntdll = ctypes.WinDLL("ntdll") if _is_windows else None
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if _is_windows else None

if _kernel32 is not None:
    _kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_int
    _kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    _kernel32.GetProcessTimes.restype = ctypes.c_int

if _ntdll is not None:
    _ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
    _ntdll.NtSuspendProcess.restype = ctypes.c_uint32
    _ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    _ntdll.NtResumeProcess.restype = ctypes.c_uint32


def _require_windows() -> None:
    if _ntdll is None or _kernel32 is None:
        raise AppError(
            "AGENT_PAUSE_UNSUPPORTED",
            "Pausing or resuming a process is only supported on Windows.",
            status_code=501,
        )


def _open_process(pid: int, extra_access: int = 0) -> int:
    handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME | extra_access, 0, pid)
    if not handle:
        error = ctypes.get_last_error()
        raise AppError(
            "AGENT_PAUSE_FAILED",
            f"Could not open the process for suspend/resume (error {error}).",
        )
    return handle


def _cpu_time_100ns(handle: int) -> int:
    """Total kernel+user CPU time consumed so far, in 100ns units, or ``-1``
    if it cannot be read (missing query rights, or the process already
    exited) -- callers treat that as "cannot verify", not as a failure."""

    creation, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    ok = _kernel32.GetProcessTimes(
        handle, ctypes.byref(creation), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not ok:
        return -1
    def _as_int(ft: wintypes.FILETIME) -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return _as_int(kernel) + _as_int(user)


def _verify_actually_suspended(handle: int) -> None:
    before = _cpu_time_100ns(handle)
    if before < 0:
        return
    time.sleep(_SUSPEND_VERIFY_WINDOW_SECONDS)
    after = _cpu_time_100ns(handle)
    if after < 0:
        return
    if after - before > _SUSPEND_VERIFY_TOLERANCE_100NS:
        raise AppError(
            "AGENT_PAUSE_FAILED",
            "NtSuspendProcess reported success but the process kept consuming "
            "CPU; it was not actually suspended.",
        )


def suspend_process(pid: int) -> None:
    """Suspend the top-level process's threads.

    Raises ``AppError`` on failure, never silently no-ops -- including the
    case where ``NtSuspendProcess`` itself reports success but the process
    did not actually stop (see ``_verify_actually_suspended``). Descendants
    are not suspended: no process-tree enumeration is performed here.
    """

    _require_windows()
    handle = _open_process(pid, extra_access=_PROCESS_QUERY_LIMITED_INFORMATION)
    try:
        status = _ntdll.NtSuspendProcess(handle)
        if status != 0:
            raise AppError("AGENT_PAUSE_FAILED", f"NtSuspendProcess returned {status:#x}.")
        _verify_actually_suspended(handle)
    finally:
        _kernel32.CloseHandle(handle)


def resume_process(pid: int) -> None:
    """Resume a previously suspended top-level process.

    Raises ``AppError`` on failure, never silently no-ops.
    """

    _require_windows()
    handle = _open_process(pid)
    try:
        status = _ntdll.NtResumeProcess(handle)
        if status != 0:
            raise AppError("AGENT_PAUSE_FAILED", f"NtResumeProcess returned {status:#x}.")
    finally:
        _kernel32.CloseHandle(handle)
