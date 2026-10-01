"""Process start for allowlisted check commands (verification, assurance, diff coverage).

Phase 5: an agent-influenced check runs in a disposable confined check box by
default. ``run_confined_check`` resolves the toolchain to its cached runtime
snapshot (``check_toolchains``), opens a ``sentinel.check.<run-id>`` box over a
copy of the repository's tracked and untracked files, runs the command there
(``cwd`` = the box's tree, no network unless declared) and closes the box. The
run is journaled by the box as ``check.confined_run``.

``run_verification_command`` is the restricted, unconfined path: the same
bounded pipe capture (``execution._process.capture``) and minimal environment
the runners used before Phase 5, at the user's authority with the repository as
its working directory. It is not a sandbox. Only the delegated
``checks.unconfined`` opt-in (``run_unconfined_check``) and Sentinel's own
non-agent tool probes may use it; ``backend/tests/core/test_subprocess_boundary.py``
enforces that no other module calls it.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.contracts.models import VerificationResult
from backend.app.core.errors import AppError
from backend.app.execution._process import CapturedProcess, capture, minimal_environment
from backend.app.execution.check_box import CheckBoxes, verified_boundary
from backend.app.execution.check_toolchains import (
    BOUNDARY_APPCONTAINER,
    BOUNDARY_UNCONFINED,
    ResolvedCheckRuntime,
)


def check_change_required() -> AppError:
    return AppError(
        "CHECK_CHANGE_REQUIRED",
        "A check run must belong to a Change; Sentinel does not journal checks anonymously.",
        status_code=400,
    )


def check_boxes_unavailable() -> AppError:
    return AppError(
        "CHECK_RUNTIME_UNAVAILABLE",
        "Confined check execution is not configured; Sentinel does not fall back to running "
        "the check at the user's authority.",
        status_code=503,
        details={"reason": "no check box manager is configured"},
    )


@dataclass(frozen=True, slots=True)
class CheckCommandResult:
    """One check command's bounded outcome plus the boundary it actually ran under."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    truncated: bool
    timed_out: bool
    incomplete: bool
    duration_ms: int
    boundary: str | None
    check_run_id: UUID


@dataclass(frozen=True, slots=True)
class CheckedVerification:
    """A verification result plus the boundary its command actually ran under.

    ``boundary`` and ``check_run_id`` are None only for a command that never
    started (an ERROR result).
    """

    result: VerificationResult
    boundary: str | None
    check_run_id: UUID | None


Resolver = Callable[..., ResolvedCheckRuntime]

# ``check.unconfined_run`` phases: the intent (journaled before the command runs)
# and its outcome. An intent with no outcome is a run that may have executed.
UNCONFINED_PHASE_STARTED = "started"
UNCONFINED_PHASE_FINISHED = "finished"
UNCONFINED_PHASE_NOT_STARTED = "not_started"


def run_confined_check(
    boxes: CheckBoxes | None, *, change_id: UUID | None, source_root: str | Path,
    executable: str, args: Sequence[str], timeout: float, limit: int,
    interpreter: str | Path | None = None, network: bool = False,
    resolve: Resolver | None = None,
) -> CheckCommandResult:
    """Run ``executable args`` in a fresh confined box over ``source_root``.

    Refuses (never falls back to the host) when there is no Change, no box
    manager, no confined runtime for the toolchain (``CHECK_TOOLCHAIN_UNCONFINED``)
    or a check-tree refusal. A launch failure propagates; the box is closed in
    every case.
    """

    if change_id is None:
        raise check_change_required()
    if boxes is None:
        raise check_boxes_unavailable()
    resolver = resolve or boxes.resolve_runtime
    resolved = resolver(executable, interpreter=interpreter, source_root=source_root)
    with boxes.open(change_id, source_root, resolved.runtime, network=network) as box:
        facts = box.run([*resolved.argv_prefix, *args], timeout=timeout, limit=limit)
    return CheckCommandResult(
        returncode=facts.exit_code, stdout=facts.stdout, stderr=facts.stderr,
        truncated=facts.truncated, timed_out=facts.timed_out, incomplete=facts.incomplete,
        duration_ms=facts.duration_ms, boundary=verified_boundary(facts),
        check_run_id=facts.check_run_id,
    )


def run_unconfined_check(
    boxes: CheckBoxes | None, *, change_id: UUID | None, cwd: str | Path,
    argv: Sequence[str], executable: str, timeout: float, limit: int,
) -> CheckCommandResult:
    """The delegated ``checks.unconfined`` path: restricted, NOT confined, journaled.

    The caller must already hold the actor's ``checks.unconfined`` authority
    for ``change_id``. The intent is journaled and committed as
    ``check.unconfined_run`` (``phase=started``) BEFORE anything runs, so a
    crash, kill or failed append afterwards never leaves an unrecorded
    user-authority run; when that append fails nothing runs (WR-01). A second
    event records the outcome (``phase=finished``, or ``phase=not_started``
    when the command could not start, after which ``OSError`` propagates).
    Both carry boundary ``UNCONFINED`` and ids and digests only; either one
    makes the Change's ``confined_checks`` FAIL.
    """

    if change_id is None:
        raise check_change_required()
    if boxes is None or not boxes.journaled:
        raise check_boxes_unavailable()
    run_id = uuid4()
    base = {
        "check_run_id": str(run_id),
        "executable": executable,
        "argv_sha256": hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest(),
        "boundary": BOUNDARY_UNCONFINED,
    }
    # WR-01: the opt-in is on record (committed) before the command can do anything.
    boxes.record_unconfined_run(change_id, run_id, {
        **base, "phase": UNCONFINED_PHASE_STARTED, "exit_code": None, "timed_out": None})
    started = time.monotonic()
    try:
        result = run_verification_command(argv, cwd=cwd, timeout=timeout, limit=limit,
                                          exclude_root=Path(cwd).resolve())
    except OSError:
        boxes.record_unconfined_run(change_id, run_id, {
            **base, "phase": UNCONFINED_PHASE_NOT_STARTED, "exit_code": None,
            "timed_out": None})
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    boxes.record_unconfined_run(change_id, run_id, {
        **base, "phase": UNCONFINED_PHASE_FINISHED,
        "exit_code": None if result.incomplete else result.returncode,
        "timed_out": result.timed_out,
    })
    return CheckCommandResult(
        returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
        truncated=result.truncated, timed_out=result.timed_out, incomplete=result.incomplete,
        duration_ms=duration_ms, boundary=BOUNDARY_UNCONFINED, check_run_id=run_id,
    )


def unconfined_environment(exclude_root: str | Path | None = None) -> dict[str, str]:
    """The reduced environment of the unconfined path.

    Without APPDATA, Python cannot resolve a per-user ``pip install --user``
    site-packages directory on Windows, so an allowlisted tool like pytest would
    falsely report itself missing; neither APPDATA nor USERPROFILE is a
    credential. With ``exclude_root``, relative PATH entries and entries inside
    that repository are dropped.
    """

    env = minimal_environment()
    for key in ("APPDATA", "USERPROFILE"):
        if key in os.environ:
            env[key] = os.environ[key]
    if exclude_root is not None:
        root = Path(exclude_root).resolve()
        paths = []
        for value in env.get("PATH", "").split(os.pathsep):
            path = Path(value)
            if value and path.is_absolute():
                path = path.resolve()
                if path != root and root not in path.parents:
                    paths.append(str(path))
        env["PATH"] = os.pathsep.join(paths)
    return env


def run_verification_command(
    argv: Sequence[str], *, cwd: str | Path, timeout: float, limit: int,
    exclude_root: str | Path | None = None,
) -> CapturedProcess:
    """Run one command unconfined with bounded output; ``OSError`` propagates.

    Unconfined opt-in use only (see the module docstring).
    """

    env = unconfined_environment(exclude_root)
    return capture(argv, cwd=cwd, env=env, timeout=timeout, limit=limit)


__all__ = [
    "BOUNDARY_APPCONTAINER", "BOUNDARY_UNCONFINED", "CheckCommandResult", "CheckedVerification",
    "check_boxes_unavailable", "check_change_required", "run_confined_check",
    "run_unconfined_check", "run_verification_command", "unconfined_environment",
]
