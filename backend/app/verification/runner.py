"""One-shot verification command execution with bounded duration and output.

Phase 5: a verification command runs in a disposable confined check box
(``execution.commands.run_confined_check``): a per-run AppContainer profile over
a copy of the repository's tracked and untracked files, a cached runtime
snapshot, no network, and the box's own environment (no host variable is
copied). The run belongs to a Change and is journaled as ``check.confined_run``.
A toolchain with no confined runtime is refused with
``CHECK_TOOLCHAIN_UNCONFINED`` unless the caller passes ``allow_unconfined``
after authorizing the actor's ``checks.unconfined`` delegation; that run uses
the restricted unconfined path and is journaled as ``check.unconfined_run``
with boundary ``UNCONFINED``.

Output is bounded during the read (``execution._process.capture``), never only
in the stored result.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from backend.app.contracts.models import (
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from backend.app.execution.check_box import CheckBoxes
from backend.app.execution.check_toolchains import (
    check_toolchain_unconfined,
    is_unconfined_toolchain,
)
from backend.app.execution.commands import (
    CheckCommandResult,
    CheckedVerification,
    Resolver,
    run_confined_check,
    run_unconfined_check,
)
from backend.app.verification.validation import resolve_executable, validate_executable


class SubprocessVerificationRunner:
    """Concrete ``VerificationPort``: every command runs in a confined check box."""

    def __init__(
        self, checks: CheckBoxes | None = None, *, resolve: Resolver | None = None,
    ) -> None:
        self._checks = checks
        self._resolve = resolve

    def run(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
        *,
        change_id: UUID | None = None,
        allow_unconfined: bool = False,
    ) -> VerificationResult:
        return self.run_checked(
            repository_path, request, output_limit_bytes,
            change_id=change_id, allow_unconfined=allow_unconfined,
        ).result

    def run_checked(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
        *,
        change_id: UUID | None = None,
        allow_unconfined: bool = False,
    ) -> CheckedVerification:
        validate_executable(request)
        limit = max(0, output_limit_bytes)
        started_at = datetime.now(UTC)
        try:
            if is_unconfined_toolchain(request.executable):
                if not allow_unconfined:
                    raise check_toolchain_unconfined(request.executable)
                argv = [resolve_executable(request), *request.args]
                outcome = run_unconfined_check(
                    self._checks, change_id=change_id, cwd=repository_path, argv=argv,
                    executable=request.executable, timeout=request.timeout_seconds,
                    limit=limit,
                )
            else:
                outcome = run_confined_check(
                    self._checks, change_id=change_id, source_root=repository_path,
                    executable=request.executable, args=request.args,
                    timeout=request.timeout_seconds, limit=limit, resolve=self._resolve,
                )
        except OSError:
            result = self._build_result(
                request=request, started_at=started_at, duration_ms=0,
                status=VerificationStatus.ERROR, exit_code=None,
                stdout=b"", stderr=b"The verification command could not be started.",
                truncated=False,
            )
            return CheckedVerification(result, None, None)
        result = self._from_outcome(request, started_at, outcome).model_copy(update={
            "check_run_id": outcome.check_run_id, "boundary": outcome.boundary})
        return CheckedVerification(result, outcome.boundary, outcome.check_run_id)

    def _from_outcome(
        self, request: VerificationRequest, started_at: datetime, outcome: CheckCommandResult,
    ) -> VerificationResult:
        status = (
            VerificationStatus.TIMED_OUT if outcome.timed_out else
            VerificationStatus.ERROR if outcome.incomplete else
            VerificationStatus.PASSED if outcome.returncode == 0 else
            VerificationStatus.FAILED
        )
        return self._build_result(
            request=request, started_at=started_at, duration_ms=outcome.duration_ms,
            status=status,
            exit_code=None if outcome.incomplete or outcome.timed_out else outcome.returncode,
            stdout=outcome.stdout, stderr=outcome.stderr, truncated=outcome.truncated,
        )

    @staticmethod
    def _build_result(
        *,
        request: VerificationRequest,
        started_at: datetime,
        duration_ms: int,
        status: VerificationStatus,
        exit_code: int | None,
        stdout: bytes,
        stderr: bytes,
        truncated: bool,
    ) -> VerificationResult:
        stdout_text = stdout.decode("utf-8", errors="ignore")
        stderr_text = stderr.decode("utf-8", errors="ignore")
        output_truncated = (
            truncated
            or stdout_text.encode("utf-8") != stdout
            or stderr_text.encode("utf-8") != stderr
        )
        return VerificationResult(
            executable=request.executable,
            args=request.args,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout_text,
            stderr=stderr_text,
            output_truncated=output_truncated,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
