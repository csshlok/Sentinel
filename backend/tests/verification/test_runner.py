"""SubprocessVerificationRunner logic through the HOST check-box harness.

Every command runs through ``run_confined_check`` (a box row, a tree copy of the
repository, the box environment, journal, cleanup); the harness's "box" is a
host child, so these tests prove result mapping and bounds, not containment
(see ``test_confined_runner.py`` for the real boundary).
"""

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import VerificationRequest, VerificationStatus
from backend.app.core.errors import AppError
from backend.app.verification.runner import SubprocessVerificationRunner
from backend.tests.support_checks import host_check_boxes
from backend.tests.support_kb import make_repo

REPO: Path
BOXES: object


@pytest.fixture(autouse=True)
def _repo_and_boxes(tmp_path):
    """A fresh Git repository and host-harness box manager per test."""

    global REPO, BOXES
    REPO = make_repo(tmp_path / "repo", {"README.md": "hello\n"})
    BOXES, _ = host_check_boxes(tmp_path / "boxes")
    yield


def SubprocessVerificationRunner_():  # noqa: N802 - mirrors the class under test
    return SubprocessVerificationRunner(BOXES)


def _run(runner: SubprocessVerificationRunner, code: str, *, timeout: int = 30):
    request = VerificationRequest(
        executable="python",
        args=["-c", code],
        timeout_seconds=timeout,
    )
    return runner.run(str(REPO), request, output_limit_bytes=262_144, change_id=uuid4())


def test_passing_command_returns_passed(tmp_path) -> None:
    runner = SubprocessVerificationRunner_()
    result = _run(runner, "print('ok')")
    assert result.status is VerificationStatus.PASSED
    assert result.exit_code == 0
    assert "ok" in result.stdout


def test_failing_command_returns_failed() -> None:
    runner = SubprocessVerificationRunner_()
    result = _run(runner, "import sys; sys.exit(1)")
    assert result.status is VerificationStatus.FAILED
    assert result.exit_code == 1


def test_cwd_is_the_box_tree_copy_not_the_repository(tmp_path) -> None:
    runner = SubprocessVerificationRunner_()
    request = VerificationRequest(
        executable="python",
        args=["-c", "import os; print(os.getcwd()); print(open('README.md').read())"],
    )
    result = runner.run(str(REPO), request, output_limit_bytes=262_144, change_id=uuid4())
    cwd = Path(result.stdout.splitlines()[0])
    assert cwd.name == "tree" and cwd.parent.name == "AC"
    assert cwd.resolve() != REPO.resolve()
    assert "hello" in result.stdout


def test_timeout_returns_timed_out_with_null_exit_code() -> None:
    runner = SubprocessVerificationRunner_()
    result = _run(runner, "import time; time.sleep(5)", timeout=1)
    assert result.status is VerificationStatus.TIMED_OUT
    assert result.exit_code is None


def test_high_output_is_bounded_and_marked_truncated() -> None:
    runner = SubprocessVerificationRunner_()
    request = VerificationRequest(
        executable="python",
        args=["-c", "print('x' * 5000)"],
    )
    result = runner.run(str(REPO), request, output_limit_bytes=100, change_id=uuid4())
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

    runner = SubprocessVerificationRunner_()
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

    result = runner.run(str(REPO), request, output_limit_bytes=101, change_id=uuid4())

    total = len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8"))
    assert total <= 101
    assert result.output_truncated is True


def test_missing_working_directory_is_refused_before_any_box(tmp_path) -> None:
    runner = SubprocessVerificationRunner_()
    request = VerificationRequest(executable="python", args=["-c", "print('no')"])

    with pytest.raises(AppError) as error:
        runner.run(str(tmp_path / "does-not-exist"), request,
                   output_limit_bytes=262_144, change_id=uuid4())

    assert error.value.code == "CHECK_TREE_FAILED"
    assert BOXES.repository.list_unclean() == []


def test_invalid_utf8_cannot_expand_past_output_budget() -> None:
    runner = SubprocessVerificationRunner_()
    request = VerificationRequest(
        executable="python",
        args=[
            "-c",
            "import sys; sys.stdout.buffer.write(bytes([255]) * 100)",
        ],
    )

    result = runner.run(str(REPO), request, output_limit_bytes=100, change_id=uuid4())

    assert len(result.stdout.encode("utf-8")) <= 100
    assert result.output_truncated is True


def test_the_daemon_process_environment_does_not_reach_the_child() -> None:
    """Reproduces the audit finding: the prior `subprocess.run(...)` call had

    no `env=` argument, so the child inherited this process's entire
    environment -- any secret present there was reachable by an arbitrary
    allowlisted command run through the legacy /verify route.
    """

    import os

    runner = SubprocessVerificationRunner_()
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

    runner = SubprocessVerificationRunner_()
    request = VerificationRequest(
        executable="python",
        args=["-c", "import sys; sys.stdout.write('x' * 20_000_000)"],
    )
    result = runner.run(str(REPO), request, output_limit_bytes=1024, change_id=uuid4())
    assert len(result.stdout.encode("utf-8")) <= 1024
    assert result.output_truncated is True


def test_disallowed_executable_raises_before_running() -> None:
    runner = SubprocessVerificationRunner_()
    request = VerificationRequest(executable="rm", args=["-rf", "."])
    with pytest.raises(AppError) as excinfo:
        runner.run(str(REPO), request, output_limit_bytes=262_144, change_id=uuid4())
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"
