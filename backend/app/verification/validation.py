"""Verification-command validation: allowlist and executable resolution.

Argument count/length and timeout bounds are already enforced by the
``VerificationRequest`` contract itself; this module only validates and
resolves the executable, which the contract cannot do on its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.app.contracts.models import VerificationRequest
# Single-sourced with the confined toolchain mapping (Phase 5).
from backend.app.execution.check_toolchains import ALLOWED_EXECUTABLES
from backend.app.execution.commands import unconfined_environment
from backend.app.execution.resolve import find_executable
from backend.app.verification.errors import executable_not_allowed, executable_not_found


def validate_executable(request: VerificationRequest) -> str:
    """The allowlisted executable name; ``VERIFICATION_EXECUTABLE_NOT_ALLOWED`` otherwise.

    A path-qualified or unlisted name is refused. Nothing is looked up.
    """

    executable = request.executable
    if "/" in executable or "\\" in executable:
        raise executable_not_allowed(executable)
    if executable not in ALLOWED_EXECUTABLES:
        raise executable_not_allowed(executable)
    return executable


def resolve_executable(request: VerificationRequest, *, root: str | Path) -> str:
    """Validate the requested executable and return its resolved host path.

    Used only by the delegated unconfined path; confined checks resolve to a
    runtime snapshot instead. Raises ``VERIFICATION_EXECUTABLE_NOT_ALLOWED``
    for a disallowed or path-qualified executable, and
    ``VERIFICATION_EXECUTABLE_NOT_FOUND`` for an allowlisted executable that
    is not on PATH.

    WR-07: the lookup uses the unconfined path's own reduced environment and
    only absolute PATH directories outside the repository ``root``, and the
    result is never inside ``root`` (the same rule as ``execution/runner.py``):
    an agent-added ``tools/cargo.cmd`` on a repository PATH entry, or in the
    current directory, is never what a ``checks.unconfined`` run executes.
    """

    executable = validate_executable(request)

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

    repository = Path(root).resolve()
    resolved = find_executable(executable, unconfined_environment(repository), repository)
    if resolved is None:
        raise executable_not_found(executable)
    return str(resolved)
