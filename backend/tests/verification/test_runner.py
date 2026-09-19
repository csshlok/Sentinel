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


def test_stdout_and_stderr_share_one_byte_budget() -> None:
    """The combined budget bounds total retained bytes; it is not necessarily

    split evenly between the two streams (execution._process.capture's own
    documented behavior -- without a separate stderr_limit, one stream can
    take the whole shared budget before the other is drained). The actual
    safety property this guards is the total bound, matching
    BoundedVerificationRunner's use of the same primitive.
    """

    runner = SubprocessVerificationRunner()
    request = VerificationRequest(
        executable="python",
        args=[
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write(bytes([195, 169]) * 500); "
                "sys.stderr.buffer.write(b'x' * 500)"
            ),
        ],
    )

    result = runner.run(".", request, output_limit_bytes=101)

    total = len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
    assert total <= 101
    assert result.output_truncated is True


def test_missing_working_directory_returns_error(tmp_path) -> None:
    runner = SubprocessVerificationRunner()
    request = VerificationRequest(executable="python", args=["-c", "print('no')"])

    result = runner.run(
        str(tmp_path / "does-not-exist"),
        request,
        output_limit_bytes=262_144,
    )

    assert result.status is VerificationStatus.ERROR
    assert result.exit_code is None
    assert "could not be started" in result.stderr


def test_invalid_utf8_cannot_expand_past_output_budget() -> None:
    runner = SubprocessVerificationRunner()
    request = VerificationRequest(
        executable="python",
        args=[
            "-c",
            "import sys; sys.stdout.buffer.write(bytes([255]) * 100)",
        ],
    )

    result = runner.run(".", request, output_limit_bytes=100)

    assert len(result.stdout.encode("utf-8")) <= 100
    assert result.output_truncated is True


def test_the_daemon_process_environment_does_not_reach_the_child() -> None:
    """Reproduces the audit finding: the prior `subprocess.run(...)` call had

    no `env=` argument, so the child inherited this process's entire
    environment -- any secret present there was reachable by an arbitrary
    allowlisted command run through the legacy /verify route.
    """

    import os

    runner = SubprocessVerificationRunner()
    os.environ["VERIFICATION_RUNNER_ENV_LEAK_CANARY"] = "must-not-leak"
    try:
        result = _run(
            runner,
            "import os; print(os.environ.get('VERIFICATION_RUNNER_ENV_LEAK_CANARY', 'ABSENT'))",
        )
    finally:
        del os.environ["VERIFICATION_RUNNER_ENV_LEAK_CANARY"]
    assert "must-not-leak" not in result.stdout
    assert "ABSENT" in result.stdout


def test_output_is_bounded_during_capture_not_only_in_the_stored_result() -> None:
    """A command that writes far more than the limit must not force this

    process to buffer the full amount before truncating -- capture() drains
    and discards past the retained budget as it reads, unlike the prior
    `subprocess.run(capture_output=True)` which bordered on unbounded
    buffering for a sufficiently verbose command.
    """

    runner = SubprocessVerificationRunner()
    request = VerificationRequest(
        executable="python",
        args=["-c", "import sys; sys.stdout.write('x' * 20_000_000)"],
    )
    result = runner.run(".", request, output_limit_bytes=1024)
    assert len(result.stdout.encode("utf-8")) <= 1024
    assert result.output_truncated is True


def test_disallowed_executable_raises_before_running() -> None:
    runner = SubprocessVerificationRunner()
    request = VerificationRequest(executable="rm", args=["-rf", "."])
    with pytest.raises(AppError) as excinfo:
        runner.run(".", request, output_limit_bytes=262_144)
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"
