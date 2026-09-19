from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.contracts.models import ProviderOperationRequest, ProviderOperationStatus
from backend.app.contracts.ports import ProviderPort
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.providers.github import GitHubProvider
from backend.app.providers.provider_port import GitHubProviderAdapter
from backend.tests.providers.fakes import FakeHttpTransport, json_response

HEAD_SHA = "a" * 40


def _adapter_and_broker() -> tuple[GitHubProviderAdapter, CredentialBroker, FakeHttpTransport]:
    transport = FakeHttpTransport([])
    github = GitHubProvider(transport)
    broker = CredentialBroker(InMemoryCredentialStore())
    return GitHubProviderAdapter(github, broker), broker, transport


def _request(operation: str, parameters: dict | None = None) -> ProviderOperationRequest:
    return ProviderOperationRequest(
        provider="github",
        operation=operation,
        change_id=uuid4(),
        actor_id=uuid4(),
        idempotency_key="idem-1",
        parameters=parameters or {},
    )


def test_adapter_satisfies_the_frozen_port() -> None:
    adapter, _, _ = _adapter_and_broker()
    assert isinstance(adapter, ProviderPort)


def test_execute_denied_when_grant_has_no_matching_scope() -> None:
    adapter, broker, _ = _adapter_and_broker()
    broker.store_provider_secret("github", "ghp_token")
    grant = broker.issue_grant(uuid4(), uuid4(), ["github.repo.read"], 3600)

    result = adapter.execute(_request("github.pr.create"), grant)

    assert result.status is ProviderOperationStatus.DENIED
    assert result.safe_metadata["error_code"] == "CREDENTIAL_GRANT_DENIED"


def test_execute_creates_pull_request_on_success() -> None:
    adapter, broker, transport = _adapter_and_broker()
    broker.store_provider_secret("github", "ghp_token")
    grant = broker.issue_grant(uuid4(), uuid4(), ["github.pr.create"], 3600)
    transport._queue.append(
        json_response(
            201,
            {
                "number": 7,
                "html_url": "https://github.com/acme/repo/pull/7",
                "draft": True,
                "head": {"sha": HEAD_SHA},
            },
        )
    )

    result = adapter.execute(
        _request(
            "github.pr.create",
            {"repository": "acme/repo", "base_branch": "main", "head_branch": "change/1"},
        ),
        grant,
    )

    assert result.status is ProviderOperationStatus.SUCCEEDED
    assert result.provider_reference == "https://github.com/acme/repo/pull/7"
    assert result.safe_metadata["head_sha"] == HEAD_SHA


def test_execute_fails_safely_on_missing_parameter() -> None:
    adapter, broker, _ = _adapter_and_broker()
    broker.store_provider_secret("github", "ghp_token")
    grant = broker.issue_grant(uuid4(), uuid4(), ["github.pr.create"], 3600)

    result = adapter.execute(_request("github.pr.create", {"repository": "acme/repo"}), grant)

    assert result.status is ProviderOperationStatus.FAILED
    assert result.safe_metadata["error_code"] == "PROVIDER_VALIDATION_FAILED"


def test_execute_denies_unsupported_operation() -> None:
    adapter, broker, _ = _adapter_and_broker()
    broker.store_provider_secret("github", "ghp_token")
    grant = broker.issue_grant(uuid4(), uuid4(), ["github.unsupported.op"], 3600)

    result = adapter.execute(_request("github.unsupported.op"), grant)

    assert result.status is ProviderOperationStatus.DENIED
    assert "unsupported operation" in result.safe_metadata["reason"]
