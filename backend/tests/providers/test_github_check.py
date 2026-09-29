"""GitHub App authentication is per-request and uses only fake HTTP."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.providers.github_app import app_provider_name
from backend.app.providers.github_check import GitHubAppClient
from backend.tests.providers.fakes import FakeHttpTransport, json_response


def _setup(queue, *, now: datetime):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode("ascii")
    broker = CredentialBroker(InMemoryCredentialStore(), clock=lambda: now)
    broker.store_provider_secret(app_provider_name("Lab"), json.dumps({
        "id": 42, "slug": "sentinel-lab", "pem": pem, "webhook_secret": "CANARY",
    }))
    transport = FakeHttpTransport(queue)
    return GitHubAppClient(broker, transport, clock=lambda: now), broker, transport, private


def _jwt_parts(token: str):
    def decode(part: str) -> bytes:
        return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    header, claims, signature = token.split(".")
    return json.loads(decode(header)), json.loads(decode(claims)), decode(signature), (
        header + "." + claims).encode("ascii")


def test_missing_installation_returns_url_then_succeeds_without_restart() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    client, broker, transport, private = _setup([
        json_response(404, {"message": "not found"}),
        json_response(200, {"id": 777}),
        json_response(201, {"token": "short-lived-token",
                            "expires_at": (now + timedelta(minutes=50)).isoformat()}),
    ], now=now)
    actor, change = uuid4(), uuid4()
    missing, token = client.installation_token(
        owner="Lab", repository="Lab/repo", actor_id=actor, change_id=change)
    assert missing.state == "GITHUB_APP_NOT_INSTALLED"
    assert missing.installation_url == "https://github.com/apps/sentinel-lab/installations/new"
    assert token is None
    found, token = client.installation_token(
        owner="Lab", repository="Lab/repo", actor_id=actor, change_id=change)
    assert found.state == "INSTALLED" and found.installation_id == 777
    assert token == "short-lived-token"
    assert len(transport.calls) == 3
    assert all("CANARY" not in str(call) and "PRIVATE KEY" not in str(call)
               for call in transport.calls)
    for call in transport.calls[:2]:
        header, claims, signature, message = _jwt_parts(
            call["headers"]["Authorization"].removeprefix("Bearer "))
        assert header == {"alg": "RS256", "typ": "JWT"}
        assert claims == {"iat": int(now.timestamp()) - 60,
                          "exp": int(now.timestamp()) + 480, "iss": "42"}
        private.public_key().verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    assert transport.calls[2]["url"] == (
        "https://api.github.com/app/installations/777/access_tokens")
    assert json.loads(transport.calls[2]["body"])["repositories"] == ["repo"]
    assert all(grant.revoked_at is not None for grant in broker._grants.values())
    assert "short-lived-token" not in str(broker.store)


def test_installation_token_is_minted_again_for_each_request() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    client, _, transport, _ = _setup([
        json_response(200, {"id": 7}),
        json_response(201, {"token": "first", "expires_at":
                            (now + timedelta(minutes=30)).isoformat()}),
        json_response(200, {"id": 7}),
        json_response(201, {"token": "second", "expires_at":
                            (now + timedelta(minutes=30)).isoformat()}),
    ], now=now)
    tokens = [client.installation_token(owner="Lab", repository="Lab/repo",
                                        actor_id=uuid4(), change_id=uuid4())[1]
              for _ in range(2)]
    assert tokens == ["first", "second"]
    assert [call["method"] for call in transport.calls] == ["GET", "POST", "GET", "POST"]


@pytest.mark.parametrize("repository", ["Lab/../repo", "Lab/.", "Lab/other/repo",
                                                "Other/repo", "Lab/%2e%2e"])
def test_bad_repository_never_reaches_http(repository: str) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    client, _, transport, _ = _setup([], now=now)
    with pytest.raises(ValueError):
        client.installation_token(owner="Lab", repository=repository,
                                  actor_id=uuid4(), change_id=uuid4())
    assert not transport.calls
