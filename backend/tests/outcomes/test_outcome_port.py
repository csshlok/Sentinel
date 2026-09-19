from datetime import UTC, datetime
from uuid import uuid4

from backend.app.contracts.models import (
    ChangeView,
    GitSummary,
    OutcomeStatus,
    ReviewState,
)
from backend.app.contracts.ports import OutcomePort
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.outcomes.outcome_port import GitHubOutcomeTracker
from backend.app.outcomes.tracker import OutcomeTracker
from backend.app.providers.github import GitHubProvider
from backend.tests.providers.fakes import FakeHttpTransport, json_response

HEAD_SHA = "a" * 40


def _change(*, with_git_summary: bool = True) -> ChangeView:
    now = datetime.now(UTC)
    git_summary = (
        GitSummary(
            repository_root="C:\\work\\repo",
            branch="main",
            head_sha=HEAD_SHA,
            is_clean=False,
            total_additions=1,
            total_deletions=0,
            patch="",
            refreshed_at=now,
        )
        if with_git_summary
        else None
    )
    return ChangeView(
        id=uuid4(),
        title="Test change",
        intent="Exercise outcome port",
        repository_path="C:\\work\\repo",
        created_at=now,
        updated_at=now,
        review_state=ReviewState.NO_CHANGES,
        git_summary=git_summary,
    )


def _tracker_with_checks(check_runs: list[dict], *, grant_scope="github.repo.read"):
    transport = FakeHttpTransport([json_response(200, {"check_runs": check_runs})])
    provider = GitHubProvider(transport)
    broker = CredentialBroker(InMemoryCredentialStore())
    broker.store_provider_secret("github", "ghp_token")
    grant = broker.issue_grant(uuid4(), uuid4(), [grant_scope], 3600)
    tracker = GitHubOutcomeTracker(
        OutcomeTracker(provider),
        broker,
        read_grant_id=grant.id,
        required_check_names=["pytest"],
    )
    return tracker


def test_tracker_satisfies_the_frozen_port(monkeypatch) -> None:
    tracker = _tracker_with_checks([])
    assert isinstance(tracker, OutcomePort)


def test_no_git_summary_returns_no_outcomes() -> None:
    tracker = _tracker_with_checks([])
    result = tracker.refresh(_change(with_git_summary=False))
    assert result == []


def test_no_github_remote_reports_unavailable(monkeypatch) -> None:
    tracker = _tracker_with_checks([])
    monkeypatch.setattr(
        "backend.app.outcomes.outcome_port.resolve_github_repository_slug",
        lambda _path: None,
    )

    outcomes = tracker.refresh(_change())

    assert outcomes[0].status is OutcomeStatus.UNAVAILABLE
    assert outcomes[0].details["reason"] == "no GitHub remote configured"


def test_invalid_read_grant_reports_unavailable(monkeypatch) -> None:
    tracker = _tracker_with_checks([])
    monkeypatch.setattr(
        "backend.app.outcomes.outcome_port.resolve_github_repository_slug",
        lambda _path: "acme/repo",
    )
    tracker.broker.revoke(tracker.read_grant_id)

    outcomes = tracker.refresh(_change())

    assert outcomes[0].status is OutcomeStatus.UNAVAILABLE
    assert outcomes[0].details["reason"] == "no valid read grant"


def test_all_required_checks_passing_reports_passed(monkeypatch) -> None:
    tracker = _tracker_with_checks(
        [
            {
                "name": "pytest",
                "status": "completed",
                "conclusion": "success",
                "head_sha": HEAD_SHA,
            }
        ]
    )
    monkeypatch.setattr(
        "backend.app.outcomes.outcome_port.resolve_github_repository_slug",
        lambda _path: "acme/repo",
    )

    outcomes = tracker.refresh(_change())

    assert outcomes[0].status is OutcomeStatus.PASSED
    assert outcomes[0].repository == "acme/repo"
    assert outcomes[0].head_sha == HEAD_SHA


def test_missing_required_check_reports_pending_not_passed(monkeypatch) -> None:
    tracker = _tracker_with_checks([])
    monkeypatch.setattr(
        "backend.app.outcomes.outcome_port.resolve_github_repository_slug",
        lambda _path: "acme/repo",
    )

    outcomes = tracker.refresh(_change())

    assert outcomes[0].status is OutcomeStatus.PENDING
