"""Bounded pipe capture for owned collectors and explicit verification commands.

This is an implementation detail, not an AgentLauncherPort substitute. Python
3.12+ supports nonblocking anonymous pipes on Windows as well as POSIX.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence


@dataclass(frozen=True)
class CapturedProcess:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    truncated: bool
    timed_out: bool
    incomplete: bool
    stdout_digest: str
    cancelled: bool = False
    pid: int | None = None


def minimal_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Do not inherit credentials, Git overrides, or interpreter injection keys."""
    source = os.environ if source is None else source
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}
    result = {key.upper(): value for key, value in source.items() if key.upper() in allowed}
    result.update({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    return result


def capture(
    argv: Sequence[str], *, cwd: str | Path, env: Mapping[str, str],
    timeout: float, limit: int, max_timeout: float = 300,
    cancel: threading.Event | None = None,
    on_start: Callable[[int], None] | None = None,
    stderr_limit: int | None = None,
) -> CapturedProcess:
    """Drain both streams, retaining at most ``limit`` bytes across them.

    Hash all stdout bytes even after the retained prefix fills. No reader threads,
    temporary output files, inherited stdin or unbounded communicate() buffers.
    The deadline includes pipe draining: descendants holding handles open cannot
    keep this call waiting. Only the direct child can be terminated. ``cancel``
    lets another thread request termination of that direct child. By default
    ``limit`` is one budget shared by both streams; ``stderr_limit`` gives stderr
    its own budget so noisy diagnostics cannot starve the stdout evidence prefix.
    """
    if (type(timeout) not in {int, float} or not 0 < timeout <= max_timeout
            or type(limit) is not int or not 0 <= limit <= 8 * 1_048_576
            or (stderr_limit is not None and (
                type(stderr_limit) is not int or not 0 <= stderr_limit <= 8 * 1_048_576))):
        raise ValueError("Invalid process capture bounds.")
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(
        list(argv), cwd=cwd, env=dict(env), shell=False, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    if on_start is not None:
        on_start(process.pid)
    buffers = [bytearray(), bytearray()]
    streams = [process.stdout, process.stderr]
    retained = [0, 0]
    truncated = timed_out = incomplete = cancelled = False
    digest = hashlib.sha256()
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        active = {0, 1}
        while active or process.poll() is None:
            if cancel is not None and cancel.is_set() and process.poll() is None:
                cancelled = True
                incomplete = bool(active)
                break
            if time.monotonic() >= deadline:
                timed_out = process.poll() is None
                incomplete = bool(active)
                break
            received = False
            for index in tuple(active):
                try:
                    data = os.read(streams[index].fileno(), 65_536)
                except BlockingIOError:
                    continue
                if not data:
                    active.remove(index)
                    continue
                received = True
                if index == 0:
                    digest.update(data)
                slot = index if stderr_limit is not None else 0
                budget = stderr_limit if slot == 1 else limit
                keep = min(len(data), budget - retained[slot])
                buffers[index].extend(data[:keep])
                retained[slot] += keep
                truncated |= keep < len(data)
            if not received:
                time.sleep(min(0.005, max(0, deadline - time.monotonic())))
        return CapturedProcess(
            returncode=None if timed_out or cancelled else process.poll(),
            stdout=bytes(buffers[0]), stderr=bytes(buffers[1]),
            truncated=truncated or incomplete, timed_out=timed_out,
            incomplete=incomplete, stdout_digest=digest.hexdigest(),
            cancelled=cancelled, pid=process.pid,
        )
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
        finally:
            for stream in streams:
                stream.close()
