"""Containerized agent isolation (Docker-backed).

A second isolation mode alongside ``process_supervisor.py``'s restricted-token
+ Job Object supervision, not a replacement for it. The two give genuinely
different guarantees:

- ``process_supervisor.py``: real Windows process-tree attribution and
  privilege reduction, explicitly **not** a sandbox -- no filesystem or
  network isolation.
- This module: real filesystem isolation (only the repository is bind-mounted
  into the container; nothing else on the host is visible) and real network
  isolation (``--network none`` by default), at the cost of losing Windows
  process-tree attribution -- the container's own process list is visible via
  ``docker top``, but those are container-namespace PIDs, not host PIDs, and
  are not cross-referenced with ``DescendantProcess`` evidence from the other
  module.

Honesty boundary, stated up front: this only exists for executables with a
configured Linux container image (``_CONTAINER_IMAGES`` below). The
Windows-native ``claude``/``codex`` CLIs as installed on a real host have no
Linux equivalent here and cannot be launched this way -- requesting container
isolation for them fails with a clear, stable error rather than silently
falling back to an unisolated launch. Requires Docker installed and reachable;
the same "never silently fall back" rule applies if it isn't.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.errors import AppError

DOCKER_TIMEOUT_SECONDS = 10
_WORKDIR = "/workspace"

# Deliberately small: only executables with a real, maintained Linux image
# are eligible. Adding one here is a real claim that this image is safe and
# suitable to run arbitrary agent-supplied arguments in -- not a place to
# list every "generic" adapter executable just because the Windows path
# allows it.
_CONTAINER_IMAGES: dict[str, str] = {
    "python": "python:3.12-slim",
    "python3": "python:3.12-slim",
    "node": "node:20-slim",
    "npm": "node:20-slim",
    "npx": "node:20-slim",
}


def is_available() -> bool:
    """Whether the docker CLI is present and a daemon actually answers.

    Checking only ``shutil.which`` would report "available" for a machine
    with the CLI installed but the daemon stopped -- a fabricated success by
    this codebase's own standard. This calls the daemon and requires a real
    reply.
    """

    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, timeout=DOCKER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _require_docker() -> None:
    if not is_available():
        raise AppError(
            "CONTAINER_ISOLATION_UNAVAILABLE",
            "Docker is not installed or its daemon is not reachable; "
            "containerized isolation is unavailable. This never silently "
            "falls back to an unisolated launch.",
            status_code=501,
        )


def image_for(executable: str) -> str:
    """The configured image for ``executable``, or a stable error.

    Never guesses a plausible-looking image for an unconfigured executable --
    an unconfigured mapping is refused, not defaulted.
    """

    image = _CONTAINER_IMAGES.get(executable.lower())
    if image is None:
        raise AppError(
            "CONTAINER_IMAGE_NOT_CONFIGURED",
            f"No container image is configured for '{executable}'.",
            status_code=422,
        )
    return image


@dataclass(frozen=True)
class ContainerProcessInfo:
    """One process observed inside the container's own PID namespace.

    These PIDs are meaningful only inside the container -- they are not
    comparable to, or a substitute for, ``DescendantProcess`` (host PIDs from
    ``process_supervisor.py``'s Job Object attribution).
    """

    pid: int
    parent_pid: int | None
    command: str


class ContainerizedProcess:
    """A running (or finished) Docker container, Popen-adjacent but not
    Popen-compatible -- callers must not assume ``.stdout``/``.stderr`` pipe
    semantics; use ``logs()`` after the container has exited instead. There
    is no incremental/live output for this isolation mode yet -- a real,
    stated limitation, not an oversight.
    """

    def __init__(self, container_id: str, image: str) -> None:
        self.container_id = container_id
        self.image = image
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}} {{.State.ExitCode}}",
                 self.container_id],
                capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        running, _, exit_code = result.stdout.strip().partition(" ")
        if running == "true":
            return None
        self.returncode = int(exit_code) if exit_code.strip().lstrip("-").isdigit() else 0
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        result = subprocess.run(
            ["docker", "wait", self.container_id],
            capture_output=True, text=True, timeout=timeout,
        )
        code = result.stdout.strip()
        self.returncode = int(code) if code.lstrip("-").isdigit() else 1
        return self.returncode

    def processes(self) -> list[ContainerProcessInfo]:
        """Best-effort: still-running processes inside the container, via
        ``docker top``. Returns an empty list (never raises) once the
        container has already exited -- there is nothing left to list, and
        that is not itself an error."""

        try:
            result = subprocess.run(
                ["docker", "top", self.container_id, "-eo", "pid,ppid,comm"],
                capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().splitlines()[1:]
        out: list[ContainerProcessInfo] = []
        for line in lines:
            parts = line.split(None, 2)
            if len(parts) < 3 or not parts[0].isdigit():
                continue
            pid_s, ppid_s, comm = parts
            out.append(ContainerProcessInfo(
                pid=int(pid_s), parent_pid=int(ppid_s) if ppid_s.isdigit() and int(ppid_s) else None,
                command=comm,
            ))
        return out

    def logs(self) -> tuple[bytes, bytes]:
        result = subprocess.run(
            ["docker", "logs", self.container_id],
            capture_output=True, timeout=DOCKER_TIMEOUT_SECONDS,
        )
        return result.stdout, result.stderr

    def kill(self) -> None:
        subprocess.run(["docker", "kill", self.container_id],
                       capture_output=True, timeout=DOCKER_TIMEOUT_SECONDS)

    def remove(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.container_id],
                       capture_output=True, timeout=DOCKER_TIMEOUT_SECONDS)


def run_containerized(
    argv: list[str], *, cwd: Path, network_isolated: bool = True,
) -> ContainerizedProcess:
    """Start a real, detached Docker container running ``argv``.

    The repository at ``cwd`` is bind-mounted read-write at ``/workspace`` --
    the container's *only* view of the host filesystem; nothing else is
    reachable, unlike the restricted-token path which explicitly keeps the
    caller's full filesystem visibility for repository writes. With
    ``network_isolated`` (the default), the container has no network access
    at all -- real isolation the other module cannot provide.

    ``argv[0]`` is passed as-is, not resolved against any host PATH: the
    image's own installed toolchain is what runs, since a host filesystem
    path (e.g. a Windows venv's ``python.exe``) has no meaning inside the
    container.
    """

    _require_docker()
    if not argv:
        raise AppError("INVALID_EXECUTION_ARGUMENT", "No executable was given.")
    image = image_for(argv[0])
    command = [
        "docker", "run", "-d", "--rm",
        "-v", f"{cwd}:{_WORKDIR}",
        "-w", _WORKDIR,
    ]
    if network_isolated:
        command += ["--network", "none"]
    command += [image, *argv]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError("CONTAINER_LAUNCH_FAILED",
                       "Starting the container timed out.") from exc
    if result.returncode != 0:
        raise AppError(
            "CONTAINER_LAUNCH_FAILED",
            f"Failed to start the container: {result.stderr.strip()[:500]}",
        )
    container_id = result.stdout.strip()
    if not container_id:
        raise AppError("CONTAINER_LAUNCH_FAILED", "Docker reported success but returned no container id.")
    return ContainerizedProcess(container_id, image)
