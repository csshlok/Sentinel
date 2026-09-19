"""One-shot verification command execution with bounded duration and output.

Only the direct child process is supervised. Descendant-process
attribution and orphan cleanup are out of scope for this runner, per the
project's documented recovery/environment non-goals.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime

from backend.app.contracts.models import (
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from backend.app.verification.validation import resolve_executable


class SubprocessVerificationRunner:
    """Concrete ``VerificationPort`` backed by a supervised subprocess."""

    def run(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
    ) -> VerificationResult:
        resolved_executable = resolve_executable(request)
        argv = [resolved_executable, *request.args]

        started_at = datetime.now(UTC)
        clock_start = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=repository_path,
                shell=False,
                capture_output=True,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            return self._build_result(
                request=request,
                started_at=started_at,
                duration_ms=self._elapsed_ms(clock_start),
                status=VerificationStatus.TIMED_OUT,
                exit_code=None,
                raw_stdout=error.stdout,
                raw_stderr=error.stderr,
                output_limit_bytes=output_limit_bytes,
            )

        status = (
            VerificationStatus.PASSED
            if completed.returncode == 0
            else VerificationStatus.FAILED
        )
        return self._build_result(
            request=request,
            started_at=started_at,
            duration_ms=self._elapsed_ms(clock_start),
            status=status,
            exit_code=completed.returncode,
            raw_stdout=completed.stdout,
            raw_stderr=completed.stderr,
            output_limit_bytes=output_limit_bytes,
        )

    @staticmethod
    def _elapsed_ms(clock_start: float) -> int:
        return int((time.monotonic() - clock_start) * 1000)

    @staticmethod
    def _build_result(
        *,
        request: VerificationRequest,
        started_at: datetime,
        duration_ms: int,
        status: VerificationStatus,
        exit_code: int | None,
        raw_stdout: bytes | None,
        raw_stderr: bytes | None,
        output_limit_bytes: int,
    ) -> VerificationResult:
        stdout, stdout_truncated = _decode_and_bound(raw_stdout, output_limit_bytes)
        stderr, stderr_truncated = _decode_and_bound(raw_stderr, output_limit_bytes)
        return VerificationResult(
            executable=request.executable,
            args=request.args,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            output_truncated=stdout_truncated or stderr_truncated,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )


def _decode_and_bound(raw: bytes | None, limit_bytes: int) -> tuple[str, bool]:
    data = raw or b""
    truncated = len(data) > limit_bytes
    if truncated:
        data = data[:limit_bytes]
    return data.decode("utf-8", errors="replace"), truncated
