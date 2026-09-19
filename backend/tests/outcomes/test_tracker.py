from backend.app.outcomes.tracker import OutcomeTracker
from backend.app.providers.github import GitHubProvider
from backend.tests.providers.fakes import FakeHttpTransport, json_response

TOKEN = "ghp_canary"
HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _tracker(check_runs: list[dict]) -> OutcomeTracker:
    transport = FakeHttpTransport([json_response(200, {"check_runs": check_runs})])
    provider = GitHubProvider(transport)
    return OutcomeTracker(provider)


def test_all_required_checks_passing_is_all_passed() -> None:
    tracker = _tracker(
        [
            {"name": "pytest", "status": "completed", "conclusion": "success", "head_sha": HEAD_SHA},
            {"name": "lint", "status": "completed", "conclusion": "success", "head_sha": HEAD_SHA},
        ]
    )

    result = tracker.verify_required_checks(
        token=TOKEN,
        repository="acme/repo",
        expected_head_sha=HEAD_SHA,
        required_check_names=["pytest", "lint"],
    )

    assert result.all_passed is True
    assert result.evidence_complete is True
    assert result.mismatched_sha_discarded == 0


def test_a_failing_required_check_is_not_all_passed() -> None:
    tracker = _tracker(
        [
            {"name": "pytest", "status": "completed", "conclusion": "failure", "head_sha": HEAD_SHA},
        ]
    )

    result = tracker.verify_required_checks(
        token=TOKEN,
        repository="acme/repo",
        expected_head_sha=HEAD_SHA,
        required_check_names=["pytest"],
    )

    assert result.all_passed is False


def test_missing_required_check_is_incomplete_evidence_not_success() -> None:
    tracker = _tracker(
        [
            {"name": "lint", "status": "completed", "conclusion": "success", "head_sha": HEAD_SHA},
        ]
    )

    result = tracker.verify_required_checks(
        token=TOKEN,
        repository="acme/repo",
        expected_head_sha=HEAD_SHA,
        required_check_names=["pytest", "lint"],
    )

    assert result.evidence_complete is False
    assert result.all_passed is False


def test_check_run_for_a_different_sha_cannot_verify_the_requested_sha() -> None:
    """CI for SHA A must never verify SHA B, even if the provider returns it."""

    tracker = _tracker(
        [
            {"name": "pytest", "status": "completed", "conclusion": "success", "head_sha": OTHER_SHA},
        ]
    )

    result = tracker.verify_required_checks(
        token=TOKEN,
        repository="acme/repo",
        expected_head_sha=HEAD_SHA,
        required_check_names=["pytest"],
    )

    assert result.mismatched_sha_discarded == 1
    assert result.evidence_complete is False
    assert result.all_passed is False
    assert result.checks == []


def test_pending_check_is_not_treated_as_passing() -> None:
    tracker = _tracker(
        [
            {"name": "pytest", "status": "in_progress", "conclusion": None, "head_sha": HEAD_SHA},
        ]
    )

    result = tracker.verify_required_checks(
        token=TOKEN,
        repository="acme/repo",
        expected_head_sha=HEAD_SHA,
        required_check_names=["pytest"],
    )

    assert result.all_passed is False
    assert result.checks[0].conclusion.value == "PENDING"
