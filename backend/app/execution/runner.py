"""Bounded VerificationPort implementation for Person 2 assurance integration.

Commands execute with the current user's OS privileges. An executable allowlist
and reduced environment are not a sandbox; callers must authorize each command.
The legacy port cannot represent launch/attach/cancel authority or idempotency.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from backend.app.contracts.models import (
    VerificationRequest, VerificationResult, VerificationStatus, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.execution._process import capture, minimal_environment


ALLOWED_EXECUTABLES = frozenset({
    "python", "python3", "pytest", "uv", "node", "npm", "npm.cmd",
    "pnpm", "pnpm.cmd", "yarn", "yarn.cmd", "cargo", "go", "dotnet",
})
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
    """Satisfies the existing VerificationPort without changing shared wiring."""

    def run(self, repository_path: str, request: VerificationRequest,
            output_limit_bytes: int) -> VerificationResult:
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
        env = minimal_environment()
        # Do not expose relative or repository-owned PATH entries to children.
        paths = []
        for value in env.get("PATH", "").split(os.pathsep):
            path = Path(value)
            if value and path.is_absolute():
                path = path.resolve()
                if path != root and root not in path.parents:
                    paths.append(str(path))
        env["PATH"] = os.pathsep.join(paths)
        executable = _resolve(request.executable, root, env)
        started_at = utc_now()
        clock = time.monotonic()
        try:
            result = capture(
                [executable, *request.args], cwd=root, env=env,
                timeout=request.timeout_seconds, limit=output_limit_bytes,
            )
        except OSError:
            status = VerificationStatus.ERROR
            exit_code = None
            stdout, stderr, truncated = "", "", False
        else:
            status = (
                VerificationStatus.TIMED_OUT if result.timed_out else
                VerificationStatus.ERROR if result.incomplete else
                VerificationStatus.PASSED if result.returncode == 0 else
                VerificationStatus.FAILED
            )
            exit_code = None if result.incomplete else result.returncode
            stdout = result.stdout.decode("utf-8", errors="ignore")
            stderr = result.stderr.decode("utf-8", errors="ignore")
            truncated = (result.truncated or stdout.encode("utf-8") != result.stdout
                         or stderr.encode("utf-8") != result.stderr)
        return VerificationResult(
            executable=request.executable, args=request.args, status=status,
            exit_code=exit_code, duration_ms=int((time.monotonic() - clock) * 1000),
            stdout=stdout, stderr=stderr, output_truncated=truncated,
            started_at=started_at, completed_at=utc_now(),
        )
