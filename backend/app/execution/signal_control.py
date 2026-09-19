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

from backend.app.core.errors import AppError

# PROCESS_SUSPEND_RESUME only -- the least-privilege handle for this
# operation, not PROCESS_ALL_ACCESS, matching this codebase's established
# least-privilege convention for subprocess execution (shell=False, argument
# arrays, minimal environment).
_PROCESS_SUSPEND_RESUME = 0x0800

_is_windows = sys.platform == "win32"
_ntdll = ctypes.WinDLL("ntdll") if _is_windows else None
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if _is_windows else None

if _kernel32 is not None:
    _kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_int

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


def _open_process(pid: int) -> int:
    handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, 0, pid)
    if not handle:
        error = ctypes.get_last_error()
        raise AppError(
            "AGENT_PAUSE_FAILED",
            f"Could not open the process for suspend/resume (error {error}).",
        )
    return handle


def suspend_process(pid: int) -> None:
    """Suspend the top-level process's threads.

    Raises ``AppError`` on failure, never silently no-ops. Descendants are
    not suspended: no process-tree enumeration is performed here.
    """

    _require_windows()
    handle = _open_process(pid)
    try:
        status = _ntdll.NtSuspendProcess(handle)
        if status != 0:
            raise AppError("AGENT_PAUSE_FAILED", f"NtSuspendProcess returned {status:#x}.")
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
