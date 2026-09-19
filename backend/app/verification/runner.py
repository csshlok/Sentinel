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
        except OSError:
            return self._build_result(
                request=request,
                started_at=started_at,
                duration_ms=self._elapsed_ms(clock_start),
                status=VerificationStatus.ERROR,
                exit_code=None,
                raw_stdout=None,
                raw_stderr=b"The verification command could not be started.",
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
        stdout, stderr, output_truncated = _decode_and_bound_outputs(
            raw_stdout,
            raw_stderr,
            output_limit_bytes,
        )
        return VerificationResult(
            executable=request.executable,
            args=request.args,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            output_truncated=output_truncated,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )


def _decode_and_bound_outputs(
    raw_stdout: bytes | None,
    raw_stderr: bytes | None,
    limit_bytes: int,
) -> tuple[str, str, bool]:
    """Bound stdout and stderr to one shared, UTF-8-safe byte budget."""

    stdout_data = raw_stdout or b""
    stderr_data = raw_stderr or b""
    limit = max(0, limit_bytes)
    truncated = len(stdout_data) + len(stderr_data) > limit

    if not truncated:
        stdout = stdout_data.decode("utf-8", errors="ignore")
        stderr = stderr_data.decode("utf-8", errors="ignore")
        decoding_was_lossy = (
            stdout.encode("utf-8") != stdout_data
            or stderr.encode("utf-8") != stderr_data
        )
        return (
            stdout,
            stderr,
            decoding_was_lossy,
        )

    if stdout_data and stderr_data:
        stdout_budget = min(len(stdout_data), limit // 2)
        stderr_budget = min(len(stderr_data), limit - stdout_budget)
        remaining = limit - stdout_budget - stderr_budget
        if remaining:
            stdout_extra = min(len(stdout_data) - stdout_budget, remaining)
            stdout_budget += stdout_extra
            remaining -= stdout_extra
            stderr_budget += min(len(stderr_data) - stderr_budget, remaining)
    else:
        stdout_budget = min(len(stdout_data), limit)
        stderr_budget = min(len(stderr_data), limit - stdout_budget)

    stdout = stdout_data[:stdout_budget].decode("utf-8", errors="ignore")
    stderr = stderr_data[:stderr_budget].decode("utf-8", errors="ignore")
    return stdout, stderr, True
