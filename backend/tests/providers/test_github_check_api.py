"""The Check API exposes only typed, DB-owned publication results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.contracts.models import (Actor, ActorKind, Delegation, ProviderOperation,
                                          ProviderOperationRequest, ProviderOperationStatus)
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.identity.repository import ActorRepository, DelegationRepository
from backend.app.providers.github_check import CheckPublication, GitHubCheckPublisher
from backend.app.providers.http_transport import HttpResponse
from backend.app.core.runtime_repositories import ProviderOperationRepository
from backend.tests.passport.test_builder import _seed_change


def _change(tmp_path, actor_id=None):
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    change = _seed_change(database)
    now = datetime.now(UTC)
    ProviderOperationRepository(database).create(ProviderOperation(
        id=uuid4(), status=ProviderOperationStatus.SUCCEEDED,
        request=ProviderOperationRequest(
            provider="github", operation="github.pr.create", change_id=change.id,
            actor_id=actor_id or uuid4(), idempotency_key="recorded-pr",
            parameters={"repository": "Lab/repo"}),
        safe_metadata={"number": 7, "head_sha": "a" * 40},
        started_at=now, completed_at=now,
    ))
    return change


def _authorized(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.core.runtime_service.CredentialAdminService.issue_grant",
                        lambda *args, **kwargs: SimpleNamespace(id=uuid4()))
    monkeypatch.setattr("backend.app.core.runtime_service.CredentialAdminService.revoke_grant",
                        lambda *args, **kwargs: None)


def test_check_api_forbids_caller_payload_and_preserves_typed_install_prompt(
    tmp_path, monkeypatch,
) -> None:
    class FakePublisher:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def publish(self, change_id, *, decline_app=False, fallback_token=None):
            return CheckPublication(
                "GITHUB_APP_NOT_INSTALLED",
                installation_url="https://github.com/apps/sentinel-lab/installations/new",
                repository="Lab/repo", pr_number=7,
            )

    monkeypatch.setattr("backend.app.main.GitHubCheckPublisher", FakePublisher)
    _authorized(monkeypatch)
    change = _change(tmp_path)
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        path = f"/api/v1/changes/{change.id}/providers/github/checks"
        forged = client.post(path, json={"freshness": "CURRENT", "checks_passed": True})
        assert forged.status_code == 422
        assert forged.json()["error"]["code"] == "GITHUB_CHECK_PAYLOAD_FORBIDDEN"
        result = client.post(path)
        assert result.status_code == 200
        assert result.json()["state"] == "GITHUB_APP_NOT_INSTALLED"
        assert result.json()["installation_url"].startswith("https://github.com/apps/")


def test_check_api_errors_do_not_reflect_provider_secrets(tmp_path, monkeypatch) -> None:
    class FailingPublisher:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def publish(self, change_id, *, decline_app=False, fallback_token=None):
            raise ValueError("PRIVATE KEY CANARY")

    monkeypatch.setattr("backend.app.main.GitHubCheckPublisher", FailingPublisher)
    _authorized(monkeypatch)
    change = _change(tmp_path)
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        path = f"/api/v1/changes/{change.id}/providers/github/checks"
        result = client.post(path)
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "GITHUB_CHECK_UNAVAILABLE"
        assert "CANARY" not in result.text


def test_declined_app_denied_authority_never_reaches_publisher(tmp_path, monkeypatch) -> None:
    class ForbiddenPublisher:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def publish(self, *args, **kwargs):
            raise AssertionError("Publisher must not be reached")

    def deny(*args, **kwargs):
        raise AppError("POLICY_DENIED", "Current delegation is missing.", status_code=403)

    monkeypatch.setattr("backend.app.main.GitHubCheckPublisher", ForbiddenPublisher)
    monkeypatch.setattr("backend.app.core.runtime_service.CredentialAdminService.issue_grant",
                        deny)
    change = _change(tmp_path)
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        result = client.post(
            f"/api/v1/changes/{change.id}/providers/github/checks?decline_app=true")
        assert result.status_code == 403
        assert result.json()["error"]["code"] == "POLICY_DENIED"


class _RecordingTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def request(self, method, url, *args, **kwargs) -> HttpResponse:
        self.requests.append((method, url))
        raise OSError("no network in tests")


def test_check_publisher_is_composed_once_with_the_injected_transport(
    tmp_path, monkeypatch,
) -> None:
    """09 IN-01: the router builds no adapters; the composition root owns the publisher."""

    _change(tmp_path)
    transport = _RecordingTransport()
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore(), http_transport=transport)
    publisher = app.state.runtime_services.github_checks
    assert isinstance(publisher, GitHubCheckPublisher)
    assert publisher._client._transport is transport
    assert publisher._client._broker is app.state.runtime_services.credentials.broker


def test_check_api_runs_the_real_delegation_check(tmp_path) -> None:
    """No monkeypatched policy: the recorded PR actor's real delegation decides."""

    now = datetime.now(UTC)
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    actor = ActorRepository(database).create(Actor(
        id=uuid4(), kind=ActorKind.HUMAN, display_name="Reviewer",
        created_at=now, updated_at=now))
    change = _change(tmp_path, actor_id=actor.id)
    transport = _RecordingTransport()
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore(), http_transport=transport)
    path = f"/api/v1/changes/{change.id}/providers/github/checks"
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        denied = client.post(path)
        assert denied.status_code == 403, denied.text
        assert denied.json()["error"]["code"] == "POLICY_DENIED"
        assert transport.requests == []

        DelegationRepository(database).create(Delegation(
            id=uuid4(), grantor_id=uuid4(), grantee_id=actor.id, change_id=change.id,
            repository_path=change.repository_path, scopes=["github.pr.create"],
            issued_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1)))
        # Authority passed, so the composed publisher ran and stopped at the
        # missing App credential, before any request left the process.
        allowed = client.post(path)
        assert allowed.status_code == 409, allowed.text
        assert allowed.json()["error"]["code"] == "PROVIDER_SECRET_NOT_CONFIGURED"
        assert transport.requests == []
