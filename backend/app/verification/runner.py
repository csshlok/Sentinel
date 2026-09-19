"""One-shot verification command execution with bounded duration and output.

Only the direct child process is supervised. Descendant-process
attribution and orphan cleanup are out of scope for this runner, per the
project's documented recovery/environment non-goals.

Uses the same bounded-subprocess primitive as
``execution.runner.BoundedVerificationRunner`` (``execution._process.capture``)
rather than ``subprocess.run(capture_output=True)``: the prior implementation
inherited this process's *entire* environment into the child (any secret or
token present in the daemon's own environment was reachable by an arbitrary
allowlisted command run through the legacy ``/verify`` route) and buffered
stdout/stderr fully in memory before truncating to the configured limit, so
the limit bounded the stored result but not actual memory use. ``capture``
drains both pipes with a shared byte budget enforced *during* the read loop
and takes an explicit, minimal environment.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from backend.app.contracts.models import (
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)
from backend.app.execution._process import capture, minimal_environment
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
        env = minimal_environment()
        # Same rationale as BoundedVerificationRunner: without APPDATA,
        # Python cannot resolve a per-user `pip install --user` site-packages
        # directory on Windows, so an allowlisted tool like pytest would
        # falsely report itself missing. Neither variable is a credential.
        for key in ("APPDATA", "USERPROFILE"):
            if key in os.environ:
                env[key] = os.environ[key]

        started_at = datetime.now(UTC)
        clock_start = time.monotonic()
        try:
            result = capture(
                argv, cwd=repository_path, env=env,
                timeout=request.timeout_seconds, limit=max(0, output_limit_bytes),
            )
        except OSError:
            return self._build_result(
                request=request, started_at=started_at,
                duration_ms=self._elapsed_ms(clock_start),
                status=VerificationStatus.ERROR, exit_code=None,
                stdout=b"", stderr=b"The verification command could not be started.",
                truncated=False,
            )

        status = (
            VerificationStatus.TIMED_OUT if result.timed_out else
            VerificationStatus.ERROR if result.incomplete else
            VerificationStatus.PASSED if result.returncode == 0 else
            VerificationStatus.FAILED
        )
        return self._build_result(
            request=request, started_at=started_at,
            duration_ms=self._elapsed_ms(clock_start),
            status=status,
            exit_code=None if result.incomplete else result.returncode,
            stdout=result.stdout, stderr=result.stderr, truncated=result.truncated,
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
