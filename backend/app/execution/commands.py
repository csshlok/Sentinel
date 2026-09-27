"""Process start for explicit, allowlisted verification commands.

This is the ``execution/`` entry point used by
``verification.runner.SubprocessVerificationRunner``: the same bounded pipe
capture (``execution._process.capture``) and the same minimal environment the
runner used before, moved here so every process Sentinel starts lives under
``execution/`` or ``git/safe_exec.py`` (enforced by
``backend/tests/core/test_subprocess_boundary.py``).

Not a sandbox: the command runs at the user's authority with the repository as
its working directory, exactly as before.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from backend.app.execution._process import CapturedProcess, capture, minimal_environment


def run_verification_command(
    argv: Sequence[str], *, cwd: str | Path, timeout: float, limit: int,
) -> CapturedProcess:
    """Run one verification command with bounded output; ``OSError`` propagates."""

    env = minimal_environment()
    # Same rationale as BoundedVerificationRunner: without APPDATA,
    # Python cannot resolve a per-user `pip install --user` site-packages
    # directory on Windows, so an allowlisted tool like pytest would
    # falsely report itself missing. Neither variable is a credential.
    for key in ("APPDATA", "USERPROFILE"):
        if key in os.environ:
            env[key] = os.environ[key]
    return capture(argv, cwd=cwd, env=env, timeout=timeout, limit=limit)
