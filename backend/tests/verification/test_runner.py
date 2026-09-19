import shutil
import sys

import pytest

from backend.app.contracts.models import VerificationRequest, VerificationStatus
from backend.app.core.errors import AppError
from backend.app.verification.runner import SubprocessVerificationRunner

PYTHON = shutil.which("python") or shutil.which("python3") or sys.executable


def _run(runner: SubprocessVerificationRunner, code: str, *, timeout: int = 30):
    request = VerificationRequest(
        executable="python",
        args=["-c", code],
        timeout_seconds=timeout,
    )
    return runner.run(".", request, output_limit_bytes=262_144)


def test_passing_command_returns_passed(tmp_path) -> None:
    runner = SubprocessVerificationRunner()
    result = _run(runner, "print('ok')")
    assert result.status is VerificationStatus.PASSED
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_failing_command_returns_failed() -> None:
    runner = SubprocessVerificationRunner()
    result = _run(runner, "import sys; sys.exit(1)")
    assert result.status is VerificationStatus.FAILED
    assert result.exit_code == 1


def test_repository_path_is_used_as_cwd(tmp_path) -> None:
    runner = SubprocessVerificationRunner()
    request = VerificationRequest(
        executable="python",
        args=["-c", "import os; print(os.getcwd())"],
    )
    result = runner.run(str(tmp_path), request, output_limit_bytes=262_144)
    assert str(tmp_path) in result.stdout


def test_timeout_returns_timed_out_with_null_exit_code() -> None:
    runner = SubprocessVerificationRunner()
    result = _run(runner, "import time; time.sleep(5)", timeout=1)
    assert result.status is VerificationStatus.TIMED_OUT
    assert result.exit_code is None


def test_high_output_is_bounded_and_marked_truncated() -> None:
    runner = SubprocessVerificationRunner()
    request = VerificationRequest(
        executable="python",
        args=["-c", "print('x' * 5000)"],
    )
    result = runner.run(".", request, output_limit_bytes=100)
    assert len(result.stdout.encode("utf-8")) <= 100
    assert result.output_truncated is True


def test_disallowed_executable_raises_before_running() -> None:
    runner = SubprocessVerificationRunner()
    request = VerificationRequest(executable="rm", args=["-rf", "."])
    with pytest.raises(AppError) as excinfo:
        runner.run(".", request, output_limit_bytes=262_144)
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"
