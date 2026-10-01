"""Bounded VerificationPort implementation used by the assurance engine.

Phase 5: every command runs in a disposable confined check box
(``execution.commands.run_confined_check``) and belongs to a Change. A
toolchain with no confined runtime is refused (``CHECK_TOOLCHAIN_UNCONFINED``)
unless the caller passes ``allow_unconfined`` after authorizing the actor's
``checks.unconfined`` delegation; that run executes on the restricted
unconfined path (allowlist, reduced environment, repository-free PATH; not a
sandbox) and is journaled with boundary ``UNCONFINED``. The legacy port cannot
represent launch/attach/cancel authority or idempotency.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from uuid import UUID

from backend.app.contracts.models import (
    VerificationRequest, VerificationResult, VerificationStatus, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.execution._process import minimal_environment
from backend.app.execution.check_box import CheckBoxes
from backend.app.execution.check_toolchains import (
    ALLOWED_EXECUTABLES,
    check_toolchain_unconfined,
    is_unconfined_toolchain,
)
from backend.app.execution.commands import (
    CheckCommandResult,
    CheckedVerification,
    Resolver,
    run_confined_check,
    run_unconfined_check,
    unconfined_environment,
)


MAX_OUTPUT_BYTES = 1_048_576


def _resolve(name: str, root: Path, environment: dict[str, str]) -> str:
    if name not in ALLOWED_EXECUTABLES:
        raise AppError("VERIFICATION_EXECUTABLE_NOT_ALLOWED", "The executable is not permitted.")
    # Bind Python to the daemon interpreter, avoiding repository/PATH shadowing.
    if name in {"python", "python3"}:
        return sys.executable
    for directory in environment.get("PATH", "").split(os.pathsep):
        candidate = Path(directory)
        if not directory or not candidate.is_absolute():
            continue
        candidate = candidate.resolve()
        if candidate == root or root in candidate.parents:
            continue
        resolved = shutil.which(str(candidate / name))
        if resolved:
            executable = Path(resolved).resolve()
            if executable == root or root in executable.parents:
                continue
            if executable.suffix.lower() in {".cmd", ".bat"}:
                raise AppError(
                    "VERIFICATION_EXECUTABLE_NOT_ALLOWED",
                    "Batch wrappers require a reviewed native executable adapter.",
                )
            return str(executable)
    raise AppError("VERIFICATION_EXECUTABLE_NOT_FOUND", "The executable could not be located.")


class BoundedVerificationRunner:
    """Satisfies ``VerificationPort``; every allowlisted command runs in a check box."""

    def __init__(
        self, checks: CheckBoxes | None = None, *, resolve: Resolver | None = None,
    ) -> None:
        self._checks = checks
        self._resolve = resolve

    def run(self, repository_path: str, request: VerificationRequest,
            output_limit_bytes: int, *, change_id: UUID | None = None,
            allow_unconfined: bool = False) -> VerificationResult:
        return self.run_checked(repository_path, request, output_limit_bytes,
                                change_id=change_id,
                                allow_unconfined=allow_unconfined).result

    def run_checked(self, repository_path: str, request: VerificationRequest,
                    output_limit_bytes: int, *, change_id: UUID | None = None,
                    allow_unconfined: bool = False) -> CheckedVerification:
        # Revalidate in case a caller used model_construct or mutated a model.
        request = VerificationRequest.model_validate(request.model_dump())
        if any("\0" in item for item in (request.executable, *request.args)):
            raise AppError("INVALID_EXECUTION_ARGUMENT", "Command arguments contain a NUL byte.")
        if type(output_limit_bytes) is not int or not 0 <= output_limit_bytes <= MAX_OUTPUT_BYTES:
            raise AppError("INVALID_OUTPUT_LIMIT", "Output limit must be between zero and one MiB.")
        try:
            if "\0" in repository_path:
                raise ValueError("Invalid directory encoding.")
            root = Path(repository_path).expanduser().resolve()
        except (OSError, ValueError, RuntimeError) as exc:
            raise AppError("INVALID_EXECUTION_DIRECTORY", "The execution directory is invalid.") from exc
        if request.executable not in ALLOWED_EXECUTABLES:
            raise AppError("VERIFICATION_EXECUTABLE_NOT_ALLOWED", "The executable is not permitted.")
        started_at = utc_now()
        try:
            if is_unconfined_toolchain(request.executable):
                if not allow_unconfined:
                    raise check_toolchain_unconfined(request.executable)
                executable = _resolve(request.executable, root, unconfined_environment(root))
                outcome = run_unconfined_check(
                    self._checks, change_id=change_id, cwd=root,
                    argv=[executable, *request.args], executable=request.executable,
                    timeout=request.timeout_seconds, limit=output_limit_bytes,
                )
            else:
                outcome = run_confined_check(
                    self._checks, change_id=change_id, source_root=root,
                    executable=request.executable, args=request.args,
                    timeout=request.timeout_seconds, limit=output_limit_bytes,
                    resolve=self._resolve,
                )
        except OSError:
            result = VerificationResult(
                executable=request.executable, args=request.args,
                status=VerificationStatus.ERROR, exit_code=None, duration_ms=0,
                stdout="", stderr="", output_truncated=False,
                started_at=started_at, completed_at=utc_now(),
            )
            return CheckedVerification(result, None, None)
        return CheckedVerification(_from_outcome(request, started_at, outcome),
                                   outcome.boundary, outcome.check_run_id)


def _from_outcome(request: VerificationRequest, started_at, outcome: CheckCommandResult,
                  ) -> VerificationResult:
    status = (
        VerificationStatus.TIMED_OUT if outcome.timed_out else
        VerificationStatus.ERROR if outcome.incomplete else
        VerificationStatus.PASSED if outcome.returncode == 0 else
        VerificationStatus.FAILED
    )
    stdout = outcome.stdout.decode("utf-8", errors="ignore")
    stderr = outcome.stderr.decode("utf-8", errors="ignore")
    truncated = (outcome.truncated or stdout.encode("utf-8") != outcome.stdout
                 or stderr.encode("utf-8") != outcome.stderr)
    return VerificationResult(
        executable=request.executable, args=request.args, status=status,
        exit_code=None if outcome.incomplete or outcome.timed_out else outcome.returncode,
        duration_ms=outcome.duration_ms, stdout=stdout, stderr=stderr,
        output_truncated=truncated, started_at=started_at, completed_at=utc_now(),
    )
