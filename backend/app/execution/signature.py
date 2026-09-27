"""Windows-Authenticode signature check (bounded, best-effort).

See EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md B.4: because this product is
Windows-first, a real, bounded signature check is achievable by shelling out
to Windows' built-in `signtool.exe verify /pa <path>`, reusing the exact
bounded-subprocess pattern already proven in `execution/_process.py`
(`shell=False`, argument array, timeout, minimal environment) -- no new
subprocess primitive, no new dependency.

Non-Windows platforms and any case where `signtool` cannot be located or run
report `"unknown"`, never a fabricated `"unsigned"` or `"valid"` (B.10):
`"unsigned"` is reported only when `signtool` itself ran and definitively
said the file carries no signature, never as a default assumption for an
unreachable check.

`signtool.exe` is located only in absolute PATH directories, never through
`shutil.which` (which checks the current directory first on Windows) and never
as a `.cmd`/`.bat` wrapper, and it runs with the Windows system directory as
its working directory rather than the (possibly repository-owned) directory
of the file being checked. A `signtool.exe` planted in the process's current
directory therefore never runs.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.acl import windows_system_directory

SIGNTOOL_TIMEOUT_SECONDS = 15
SIGNTOOL_OUTPUT_LIMIT = 8192
_UNSIGNED_MARKERS = ("no signature found", "is not signed")


def _locate_signtool() -> str | None:
    """First `signtool.exe` in an absolute PATH directory; None if there is none."""

    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        candidate = directory / "signtool.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def check_signature(executable_path: str) -> str:
    """Return one of `"valid"`, `"invalid"`, `"unsigned"`, `"unknown"`.

    Matches `backend.app.contracts.models.ToolSignatureState`'s values
    exactly (lower-case), so a caller can pass this straight into
    `ToolRegistryService(signature_checker=check_signature)`.
    """

    if platform.system() != "Windows":
        return "unknown"
    signtool = _locate_signtool()
    if signtool is None:
        return "unknown"
    target = Path(executable_path).absolute()
    if not target.is_file():
        return "unknown"
    workdir = windows_system_directory()
    if workdir is None:
        return "unknown"
    try:
        result = capture(
            [signtool, "verify", "/pa", str(target)],
            cwd=workdir, env=minimal_environment(),
            timeout=SIGNTOOL_TIMEOUT_SECONDS, limit=SIGNTOOL_OUTPUT_LIMIT,
        )
    except (OSError, ValueError):
        return "unknown"
    if result.timed_out or result.cancelled or result.returncode is None:
        return "unknown"
    if result.returncode == 0:
        return "valid"
    output = (result.stdout + result.stderr).decode("utf-8", errors="ignore").lower()
    if any(marker in output for marker in _UNSIGNED_MARKERS):
        return "unsigned"
    return "invalid"
