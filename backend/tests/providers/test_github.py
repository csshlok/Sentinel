from datetime import UTC, datetime

import pytest

from backend.app.core.errors import AppError
from backend.app.providers.github import GitHubProvider
from backend.app.providers.http_transport import TransportTimeout
from backend.tests.providers.fakes import FakeHttpTransport, json_response

CANARY_TOKEN = "ghp_canary_do_not_leak"
HEAD_SHA = "a" * 40


def _provider(transport: FakeHttpTransport, **kwargs) -> GitHubProvider:
    sleeps: list[float] = []
    kwargs.setdefault("retry_sleep", sleeps.append)
    kwargs.setdefault("clock", lambda: datetime.now(UTC))
    provider = GitHubProvider(transport, **kwargs)
    provider._test_sleeps = sleeps  # type: ignore[attr-defined]
    return provider


def _pr_payload(sha: str = HEAD_SHA, draft: bool = True) -> dict:
    return {
        "number": 42,
        "html_url": "https://github.com/acme/repo/pull/42",
        "draft": draft,
        "head": {"sha": sha},
    }


def test_create_pull_request_sends_bearer_token_and_returns_outcome() -> None:
    transport = FakeHttpTransport([json_response(201, _pr_payload())])
    provider = _provider(transport)

    outcome = provider.create_or_refresh_pull_request(
        token=CANARY_TOKEN,
        repository="acme/repo",
        base_branch="main",
        head_branch="change/1048",
        title="Rotating refresh tokens",
        idempotency_key="change-1048",
    )

    assert outcome.number == 42
    assert outcome.head_sha == HEAD_SHA
    assert transport.calls[0]["headers"]["Authorization"] == f"Bearer {CANARY_TOKEN}"


def test_duplicate_idempotency_key_does_not_issue_a_second_request() -> None:
    transport = FakeHttpTransport([json_response(201, _pr_payload())])
    provider = _provider(transport)

    first = provider.create_or_refresh_pull_request(
        token=CANARY_TOKEN,
        repository="acme/repo",
        base_branch="main",
        head_branch="change/1048",
        title="Rotating refresh tokens",
        idempotency_key="change-1048",
    )
    second = provider.create_or_refresh_pull_request(
        token=CANARY_TOKEN,
        repository="acme/repo",
        base_branch="main",
        head_branch="change/1048",
        title="Rotating refresh tokens",
        idempotency_key="change-1048",
    )

    assert first == second
    assert len(transport.calls) == 1


def test_list_check_runs_paginates() -> None:
    page_one_runs = [
        {"name": f"check-{i}", "status": "completed", "conclusion": "success", "head_sha": HEAD_SHA}
        for i in range(50)
    ]
    page_two_runs = [
        {"name": "check-final", "status": "completed", "conclusion": "success", "head_sha": HEAD_SHA}
    ]
    transport = FakeHttpTransport(
        [
            json_response(200, {"check_runs": page_one_runs}),
            json_response(200, {"check_runs": page_two_runs}),
        ]
    )
    provider = _provider(transport)

    results = provider.list_check_runs_for_sha(
        token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
    )

    assert len(results) == 51
    assert len(transport.calls) == 2
    assert "page=1" in transport.calls[0]["url"]
    assert "page=2" in transport.calls[1]["url"]


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "PROVIDER_AUTH_FAILED"),
        (403, "PROVIDER_AUTH_FAILED"),
        (404, "PROVIDER_NOT_FOUND"),
        (409, "PROVIDER_CONFLICT"),
    ],
)
def test_non_retryable_status_codes_raise_immediately(status_code, expected_code) -> None:
    transport = FakeHttpTransport([json_response(status_code, {"message": "nope"})])
    provider = _provider(transport)

    with pytest.raises(AppError) as excinfo:
        provider.list_check_runs_for_sha(
            token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
        )

    assert excinfo.value.code == expected_code
    assert len(transport.calls) == 1


def test_422_carries_provider_message_without_leaking_token() -> None:
    transport = FakeHttpTransport(
        [json_response(422, {"message": "Validation failed: head sha unknown"})]
    )
    provider = _provider(transport)

    with pytest.raises(AppError) as excinfo:
        provider.list_check_runs_for_sha(
            token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
        )

    assert excinfo.value.code == "PROVIDER_VALIDATION_FAILED"
    assert excinfo.value.details["provider_message"] == "Validation failed: head sha unknown"
    assert CANARY_TOKEN not in str(excinfo.value)
    assert CANARY_TOKEN not in str(excinfo.value.details)


def test_429_retries_then_succeeds() -> None:
    transport = FakeHttpTransport(
        [
            json_response(429, {"message": "rate limited"}, {"Retry-After": "0"}),
            json_response(200, {"check_runs": []}),
        ]
    )
    provider = _provider(transport)

    results = provider.list_check_runs_for_sha(
        token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
    )

    assert results == []
    assert len(transport.calls) == 2
    assert provider._test_sleeps == [0.0]  # type: ignore[attr-defined]


def test_429_exceeding_retries_raises_rate_limited() -> None:
    transport = FakeHttpTransport(
        [json_response(429, {}, {"Retry-After": "0"}) for _ in range(4)]
    )
    provider = _provider(transport, max_retries=3)

    with pytest.raises(AppError) as excinfo:
        provider.list_check_runs_for_sha(
            token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
        )

    assert excinfo.value.code == "PROVIDER_RATE_LIMITED"
    assert len(transport.calls) == 4


def test_5xx_retries_then_exhausts_to_unavailable() -> None:
    transport = FakeHttpTransport([json_response(503, {}) for _ in range(4)])
    provider = _provider(transport, max_retries=3)

    with pytest.raises(AppError) as excinfo:
        provider.list_check_runs_for_sha(
            token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
        )

    assert excinfo.value.code == "PROVIDER_UNAVAILABLE"
    assert len(transport.calls) == 4


def test_timeout_retries_then_raises_provider_timeout() -> None:
    transport = FakeHttpTransport([TransportTimeout("boom") for _ in range(4)])
    provider = _provider(transport, max_retries=3)

    with pytest.raises(AppError) as excinfo:
        provider.list_check_runs_for_sha(
            token=CANARY_TOKEN, repository="acme/repo", head_sha=HEAD_SHA
        )

    assert excinfo.value.code == "PROVIDER_TIMEOUT"
    assert len(transport.calls) == 4
