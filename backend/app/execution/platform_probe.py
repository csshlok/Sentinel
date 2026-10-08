"""Whether this Windows installation can run Sentinel's AppContainer boxes (plan 02-02, D3).

Evidence, not assumption: once per process a throwaway box opens the ``NUL``
device and starts a System32 child. Hosted Windows Server runners deny both
(CI, 2026-09-30), and every agent and check box needs them. Sentinel only
claims Windows workstation SKUs: a Server or domain-controller product type
is refused even when the probe passes, because nothing beyond this probe has
been demonstrated there. A refusal is loud (``APPCONTAINER_PLATFORM_UNSUPPORTED``)
and never a fallback to a weaker boundary.
"""

from __future__ import annotations

import ctypes
import os
import threading
import uuid
from ctypes import wintypes
from dataclasses import dataclass

from backend.app.core.errors import AppError

IS_WINDOWS = os.name == "nt"
PROBE_PREFIX = "sentinel.probe."
VER_NT_WORKSTATION = 1
_PROBE_EXIT = 7


@dataclass(frozen=True, slots=True)
class PlatformSupport:
    supported: bool
    reason: str | None = None
    product_type: int | None = None


_lock = threading.Lock()
_cached: PlatformSupport | None = None


class _OSVERSIONINFOEXW(ctypes.Structure):
    _fields_ = [("dwOSVersionInfoSize", wintypes.DWORD), ("dwMajorVersion", wintypes.DWORD),
                ("dwMinorVersion", wintypes.DWORD), ("dwBuildNumber", wintypes.DWORD),
                ("dwPlatformId", wintypes.DWORD), ("szCSDVersion", wintypes.WCHAR * 128),
                ("wServicePackMajor", wintypes.WORD), ("wServicePackMinor", wintypes.WORD),
                ("wSuiteMask", wintypes.WORD), ("wProductType", ctypes.c_ubyte),
                ("wReserved", ctypes.c_ubyte)]


def product_type() -> int | None:
    """``wProductType`` (1 workstation, 2 domain controller, 3 server); None if unknown."""

    if not IS_WINDOWS:
        return None
    info = _OSVERSIONINFOEXW()
    info.dwOSVersionInfoSize = ctypes.sizeof(info)
    if ctypes.WinDLL("ntdll").RtlGetVersion(ctypes.byref(info)) != 0:
        return None
    return int(info.wProductType)


def _run_probe() -> PlatformSupport:
    from backend.app.execution.appcontainer import (base_environment, delete_profile,
                                                    ensure_profile, remove_tree_retrying,
                                                    spawn_appcontainer_supervised)

    kind = product_type()
    name = PROBE_PREFIX + uuid.uuid4().hex
    try:
        profile, _created = ensure_profile(name, display_name="Sentinel platform probe")
    except AppError as exc:
        return PlatformSupport(False, f"profile creation failed ({exc.code})", kind)
    try:
        env = base_environment(profile.container_path)
        system32 = os.path.join(env["SystemRoot"], "System32")
        cmd = os.path.join(system32, "cmd.exe")
        powershell = os.path.join(system32, "WindowsPowerShell", "v1.0", "powershell.exe")
        # cmd's own process launch is refused inside any box (a cmd quirk), so
        # the child spawn uses .NET's CreateProcess, as node and git do.
        probes = {
            "open the NUL device": [cmd, "/d", "/c", f"echo x>NUL && exit {_PROBE_EXIT}"],
            "start a System32 program": [
                powershell, "-NoProfile", "-NonInteractive", "-Command",
                f"$p = [Diagnostics.Process]::Start('{cmd}', '/d /c exit {_PROBE_EXIT}'); "
                "$p.WaitForExit(); exit $p.ExitCode"],
        }
        for what, argv in probes.items():
            try:
                process = spawn_appcontainer_supervised(
                    argv, cwd=profile.container_path, env=env, redact=lambda text: text,
                    profile_name=name, expected_package_sid=profile.package_sid,
                    capabilities=())
            except AppError as exc:
                return PlatformSupport(False, f"the probe box could not start ({exc.code})",
                                       kind)
            try:
                code = process.wait(timeout=60)
            except Exception:
                process.kill()
                code = None
            finally:
                for stream in (process.stdout, process.stderr):
                    stream.close()
                process.close()
            if code != _PROBE_EXIT:
                return PlatformSupport(False, f"a box could not {what} (exit {code})", kind)
        if kind != VER_NT_WORKSTATION:
            return PlatformSupport(
                False, f"Windows product type {kind} is not a workstation SKU; Sentinel's "
                "AppContainer boundary is only demonstrated on Windows workstation editions",
                kind)
        return PlatformSupport(True, None, kind)
    finally:
        try:
            remove_tree_retrying(profile.container_path.parent)
        except OSError:
            pass
        try:
            delete_profile(name)
        except AppError:
            pass


def platform_support(*, refresh: bool = False) -> PlatformSupport:
    """The cached probe result for this process (computed on first use)."""

    global _cached
    if not IS_WINDOWS:
        return PlatformSupport(False, "AppContainers exist only on Windows", None)
    with _lock:
        if _cached is None or refresh:
            _cached = _run_probe()
        return _cached


def platform_unsupported(support: PlatformSupport) -> AppError:
    return AppError(
        "APPCONTAINER_PLATFORM_UNSUPPORTED",
        "This Windows installation cannot run Sentinel's AppContainer boundary: "
        f"{support.reason}.",
        status_code=503,
        details={"reason": support.reason, "product_type": support.product_type},
    )


def require_appcontainer_platform() -> None:
    """Raise ``APPCONTAINER_PLATFORM_UNSUPPORTED`` unless the probe passed."""

    support = platform_support()
    if not support.supported:
        raise platform_unsupported(support)
