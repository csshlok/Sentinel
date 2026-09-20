"""Verification-command validation: allowlist and executable resolution.

Argument count/length and timeout bounds are already enforced by the
``VerificationRequest`` contract itself; this module only validates and
resolves the executable, which the contract cannot do on its own.
"""

from __future__ import annotations

import shutil
import sys

from backend.app.contracts.models import VerificationRequest
from backend.app.verification.errors import executable_not_allowed, executable_not_found

ALLOWED_EXECUTABLES = frozenset(
    {
        "python",
        "python3",
        "pytest",
        "uv",
        "node",
        "npm",
        "npm.cmd",
        "pnpm",
        "pnpm.cmd",
        "yarn",
        "yarn.cmd",
        "cargo",
        "go",
        "dotnet",
    }
)


def resolve_executable(request: VerificationRequest) -> str:
    """Validate the requested executable and return its resolved path.

    Raises ``VERIFICATION_EXECUTABLE_NOT_ALLOWED`` for a disallowed or
    path-qualified executable, and ``VERIFICATION_EXECUTABLE_NOT_FOUND``
    for an allowlisted executable that is not on PATH.
    """

    executable = request.executable
    if "/" in executable or "\\" in executable:
        raise executable_not_allowed(executable)
    if executable not in ALLOWED_EXECUTABLES:
        raise executable_not_allowed(executable)

    # Same reasoning as execution/resolve.py::find_executable: a plain PATH
    # lookup for "python"/"python3" can resolve to the Windows Store's
    # python.exe app-execution-alias stub instead of a real interpreter,
    # which -- when no Store-installed Python is actually present -- opens
    # an interactive install prompt or starts downloading one, hanging (or
    # timing out) the verification command instead of running it. Using this
    # process's own interpreter is also strictly more correct: it is
    # guaranteed to exist and matches the interpreter this backend itself
    # runs under, not whichever "python" happens to be first on PATH.
    if executable in {"python", "python3"}:
        return sys.executable

    resolved = shutil.which(executable)
    if resolved is None:
        raise executable_not_found(executable)
    return resolved
