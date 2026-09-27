"""Tool version probes that never run inside the repository.

Environment capture asks installed tools for their version (``node --version``,
``cargo --version``, ``git --version`` ...). Many of those tools honor
repository-local configuration found by walking up from their working
directory: ``.npmrc``, ``global.json``, ``rust-toolchain.toml``, a ``go.mod``
``toolchain`` line, ``.yarnrc.yml`` ``yarnPath`` or a corepack
``packageManager`` field. In an agent-written repository that configuration can
steer a probe or make it execute repository-chosen code.

``run_tool_probe`` therefore starts the (already resolved) executable with a
fresh Sentinel-owned temporary working directory, created for this one probe
and removed afterwards, so no repository-local tool configuration applies.
Executable resolution stays in ``backend.app.execution.resolve`` and is
unchanged: repository directories never contribute executables. PATH for the
probe is likewise restricted to absolute directories outside the repository.

User-level configuration (``HOME``/``USERPROFILE``: ``~/.npmrc``, ``~/.cargo``,
rustup/dotnet shims) is still visible on purpose; it lies outside the
repository and at the user's own authority. This is not a sandbox: the probed
tool runs with the user's token.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.resolve import safe_path_entries

PROBE_TIMEOUT_SECONDS = 10
PROBE_OUTPUT_LIMIT = 4096
PROBE_DIRECTORY_PREFIX = "sentinel-probe-"


def run_tool_probe(argv: Sequence[str], *, exclude_root: Path) -> tuple[int | None, str]:
    """Run ``argv`` in a fresh temporary directory; ``(None, "")`` on timeout.

    ``exclude_root`` (the repository) is used only to drop repository
    directories from PATH; it is never the working directory.
    """

    env = minimal_environment()
    env["PATH"] = os.pathsep.join(str(p) for p in safe_path_entries(env, Path(exclude_root).resolve()))
    for key in ("HOME", "USERPROFILE"):  # user-level tool config lives outside the repository
        if key in os.environ:
            env[key] = os.environ[key]
    with tempfile.TemporaryDirectory(prefix=PROBE_DIRECTORY_PREFIX,
                                     ignore_cleanup_errors=True) as workdir:
        result = capture(list(argv), cwd=workdir, env=env, timeout=PROBE_TIMEOUT_SECONDS,
                         limit=PROBE_OUTPUT_LIMIT)
    if result.timed_out or result.incomplete:
        return None, ""
    return result.returncode, result.stdout.decode("utf-8", errors="replace")
