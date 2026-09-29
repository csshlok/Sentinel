"""The Check API exposes only typed, DB-owned publication results."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.contracts.models import (ProviderOperation, ProviderOperationRequest,
                                          ProviderOperationStatus)
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.providers.github_check import CheckPublication
from backend.app.core.runtime_repositories import ProviderOperationRepository
from backend.tests.passport.test_builder import _seed_change


def _change(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    change = _seed_change(database)
    now = datetime.now(UTC)
    ProviderOperationRepository(database).create(ProviderOperation(
        id=uuid4(), status=ProviderOperationStatus.SUCCEEDED,
        request=ProviderOperationRequest(
            provider="github", operation="github.pr.create", change_id=change.id,
            actor_id=uuid4(), idempotency_key="recorded-pr",
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

    monkeypatch.setattr("backend.app.core.router.GitHubCheckPublisher", FakePublisher)
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

    monkeypatch.setattr("backend.app.core.router.GitHubCheckPublisher", FailingPublisher)
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
            raise AssertionError("Publisher must not be constructed")

    def deny(*args, **kwargs):
        raise AppError("POLICY_DENIED", "Current delegation is missing.", status_code=403)

    monkeypatch.setattr("backend.app.core.router.GitHubCheckPublisher", ForbiddenPublisher)
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
