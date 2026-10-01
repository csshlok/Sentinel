"""GitHub App authentication is per-request and uses only fake HTTP."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.providers.github_app import app_provider_name
from backend.app.contracts.models import (PassportV2DiffClaim, ProviderOperation,
                                          ProviderOperationRequest, ProviderOperationStatus)
from backend.app.core.runtime_repositories import ProviderOperationRepository
from backend.app.passport.bundle import BundleArtifact
from backend.app.passport.jcs import canonicalize
from backend.app.passport.v2 import PassportV2Issuer
from backend.app.providers.github_check import GitHubAppClient, GitHubCheckPublisher
import backend.app.providers.github_check as github_check_module
from backend.tests.providers.fakes import FakeHttpTransport, json_response
from backend.tests.passport.test_builder import _database, _seed_change


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


def _publisher_fixture(tmp_path, queue, *, now: datetime,
                       on_export=None, freshness: str = "CURRENT"):
    database = _database(tmp_path)
    change = _seed_change(database)
    operation = ProviderOperation(
        id=uuid4(), status=ProviderOperationStatus.SUCCEEDED,
        request=ProviderOperationRequest(
            provider="github", operation="github.pr.create", change_id=change.id,
            actor_id=uuid4(), idempotency_key="pr-one",
            parameters={"repository": "Lab/repo"}),
        safe_metadata={"number": 7, "head_sha": "a" * 40},
        started_at=now, completed_at=now,
    )
    ProviderOperationRepository(database).create(operation)
    _, broker, transport, _ = _setup(queue, now=now)
    broker.store_provider_secret("github", "PAT-CANARY")

    def export(change_id):
        claims = PassportV2Issuer(database).snapshot(change_id)
        claims = claims.model_copy(update={"diff_coverage": PassportV2DiffClaim(
            checks_passed=True, diff_exercised="PASS", freshness=freshness,
            head_sha="a" * 40)})
        content = canonicalize({"claims": claims.model_dump(mode="json"),
                                "signer": {"fingerprint": "ABCDEF"}})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("passport.json", content)
        if on_export is not None:
            on_export(database, change_id)
        return BundleArtifact(f"change-{change_id}.sentinel", buffer.getvalue(),
                              "b" * 64, "ABCDEF")

    publisher = GitHubCheckPublisher(database, broker, transport,
                                     bundle_export=export, clock=lambda: now)
    return publisher, change, transport


def _check_queue(now: datetime, *, first_sha: str = "a" * 40,
                 final_sha: str = "a" * 40):
    return [
        json_response(200, {"id": 55}),
        json_response(201, {"token": "ephemeral",
                            "expires_at": (now + timedelta(minutes=30)).isoformat()}),
        json_response(200, {"head": {"sha": first_sha}}),
        json_response(200, {"head": {"sha": final_sha}}),
        json_response(201, {"id": 9, "head_sha": final_sha,
                            "html_url": "https://github.com/Lab/repo/runs/9"}),
    ]


def test_check_publishes_signed_claims_to_exact_pr_head(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, transport = _publisher_fixture(tmp_path, _check_queue(now), now=now)
    result = publisher.publish(change.id)
    assert result.state == "PUBLISHED"
    assert result.head_sha == "a" * 40
    assert result.freshness == "CURRENT"
    body = json.loads(transport.calls[-1]["body"])
    assert body["head_sha"] == "a" * 40
    assert body["conclusion"] == "neutral"  # UNKNOWN boundary cannot become success.
    summary = body["output"]["summary"]
    for expected in ("Checks passed: PASS", "Diff exercised: PASS",
                     "Freshness: CURRENT", "Execution boundary: UNKNOWN",
                     "Payload SHA-256: " + "b" * 64,
                     "Signer fingerprint: ABCDEF", "no preset selected",
                     "Policy decision: UNSELECTED", "fingerprint you already trust"):
        assert expected in summary
    assert "CANARY" not in str(transport.calls)


def test_signed_policy_deny_caps_otherwise_successful_check(tmp_path, monkeypatch) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, transport = _publisher_fixture(tmp_path, _check_queue(now), now=now)
    validate = github_check_module.PassportV2Payload.model_validate

    def with_boundary_and_deny(cls, value):
        return validate(value).model_copy(update={
            "execution_boundary": "APPCONTAINER",
            "policy_preset_name": "strict", "policy_preset_version": "1.1.0",
            "policy_decision": "DENY", "policy_denials": ["confined checks must be PASS"],
        })

    monkeypatch.setattr(github_check_module.PassportV2Payload, "model_validate",
                        classmethod(with_boundary_and_deny))
    publisher.publish(change.id)
    body = json.loads(transport.calls[-1]["body"])
    assert body["conclusion"] == "neutral"
    assert "Policy preset: strict" in body["output"]["summary"]
    assert "Policy decision: DENY" in body["output"]["summary"]
    assert "confined checks must be PASS" in body["output"]["summary"]


def test_head_moving_during_export_is_stale_on_new_exact_head(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, transport = _publisher_fixture(
        tmp_path, _check_queue(now, final_sha="c" * 40), now=now)
    result = publisher.publish(change.id)
    assert result.head_sha == "c" * 40
    assert result.freshness == "STALE" and result.signed_freshness == "CURRENT"
    body = json.loads(transport.calls[-1]["body"])
    assert body["head_sha"] == "c" * 40
    assert "Freshness: STALE" in body["output"]["summary"]
    assert body["conclusion"] == "neutral"


def test_policy_change_during_export_marks_check_stale(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)

    def change_policy(database, change_id):
        with database.connection() as connection:
            connection.execute("UPDATE changes SET revision = revision + 1, "
                               "contract_json = ? WHERE id = ?",
                               ('{"required":true}', str(change_id)))

    publisher, change, transport = _publisher_fixture(
        tmp_path, _check_queue(now), now=now, on_export=change_policy)
    result = publisher.publish(change.id)
    assert result.freshness == "STALE" and result.signed_freshness == "CURRENT"
    assert "Freshness: STALE" in json.loads(transport.calls[-1]["body"])["output"]["summary"]


def test_missing_installation_is_typed_and_can_retry(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, transport = _publisher_fixture(
        tmp_path, [json_response(404, {})] + _check_queue(now), now=now)
    first = publisher.publish(change.id)
    assert first.state == "GITHUB_APP_NOT_INSTALLED"
    assert first.installation_url == "https://github.com/apps/sentinel-lab/installations/new"
    assert len(transport.calls) == 1
    assert publisher.publish(change.id).state == "PUBLISHED"


def test_signed_stale_claim_is_preserved(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, transport = _publisher_fixture(
        tmp_path, _check_queue(now), now=now, freshness="STALE")
    result = publisher.publish(change.id)
    assert result.freshness == "STALE" and result.signed_freshness == "STALE"
    summary = json.loads(transport.calls[-1]["body"])["output"]["summary"]
    assert "Signed Passport freshness: STALE" in summary


def test_change_without_recorded_pr_cannot_publish(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    database = _database(tmp_path)
    change = _seed_change(database)
    _, broker, transport, _ = _setup([], now=now)
    publisher = GitHubCheckPublisher(database, broker, transport, clock=lambda: now)
    with pytest.raises(ValueError, match="no recorded GitHub pull request"):
        publisher.publish(change.id)
    assert not transport.calls


def test_declined_app_uses_lesser_statuses_with_all_claims(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    queue = [json_response(200, {"head": {"sha": "a" * 40}}),
             json_response(200, {"head": {"sha": "a" * 40}})]
    queue.extend(json_response(201, {"id": index}) for index in range(1, 15))
    publisher, change, transport = _publisher_fixture(tmp_path, queue, now=now)
    result = publisher.publish(change.id, decline_app=True,
                               fallback_token="PAT-CANARY")
    assert result.state == "PUBLISHED"
    assert result.presentation == "COMMIT_STATUS_LESSER"
    assert len(transport.calls) == 16
    statuses = transport.calls[2:]
    assert all(call["url"].endswith("/statuses/" + "a" * 40) for call in statuses)
    bodies = [json.loads(call["body"]) for call in statuses]
    assert {body["context"] for body in bodies if "policy-denials" in body["context"]} == {
        f"sentinel/passport/policy-denials-{slot}" for slot in range(1, 9)}
    assert all(body["description"] == "Policy denials: [end]"
               for body in bodies if body["context"].endswith(tuple(
                   f"policy-denials-{slot}" for slot in range(2, 9))))
    assert all(body["state"] == "error" for body in bodies)  # UNKNOWN boundary.
    joined = " ".join(body["description"] for body in bodies)
    for expected in ("checks PASS", "diff PASS", "freshness CURRENT", "boundary UNKNOWN",
                     "payload SHA-256 " + "b" * 64, "signer ABCDEF",
                     "no preset selected", "UNSELECTED", "Policy denials:"):
        assert expected in joined
    assert all(len(body["description"]) <= 140 for body in bodies)
    assert "PAT-CANARY" not in joined


def test_declined_app_stale_status_never_succeeds(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    queue = [json_response(200, {"head": {"sha": "c" * 40}}),
             json_response(200, {"head": {"sha": "c" * 40}})]
    queue.extend(json_response(201, {"id": index}) for index in range(1, 15))
    publisher, change, transport = _publisher_fixture(tmp_path, queue, now=now)
    result = publisher.publish(change.id, decline_app=True,
                               fallback_token="PAT-CANARY")
    assert result.head_sha == "c" * 40 and result.freshness == "STALE"
    assert all(json.loads(call["body"])["state"] == "error"
               for call in transport.calls[2:])


def test_lesser_status_clears_old_denial_contexts(tmp_path, monkeypatch) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, _ = _publisher_fixture(tmp_path, [], now=now)
    statuses: list[dict[str, object]] = []

    def request(method, path, token, *, body=None):
        if method == "GET":
            return 200, {"head": {"sha": "a" * 40}}
        assert method == "POST" and path.endswith("/statuses/" + "a" * 40)
        statuses.append(body)
        return 201, {"id": len(statuses)}

    monkeypatch.setattr(publisher._client, "_request", request)
    validate = github_check_module.PassportV2Payload.model_validate
    denials = ["first denial " * 14, "second denial " * 14]

    def with_denials(cls, value):
        return validate(value).model_copy(update={
            "policy_preset_name": "strict", "policy_preset_version": "1.3.2",
            "policy_decision": "DENY", "policy_denials": denials.copy(),
        })

    monkeypatch.setattr(github_check_module.PassportV2Payload, "model_validate",
                        classmethod(with_denials))
    publisher.publish(change.id, decline_app=True, fallback_token="PAT-CANARY")
    first = {body["context"]: body["description"] for body in statuses}
    statuses.clear()
    denials.clear()
    publisher.publish(change.id, decline_app=True, fallback_token="PAT-CANARY")
    second = {body["context"]: body["description"] for body in statuses}
    assert first.keys() == second.keys()
    assert first["sentinel/passport/policy-denials-2"] != "Policy denials: [end]"
    assert second["sentinel/passport/policy-denials-1"] == "Policy denials: none"
    assert all(second[f"sentinel/passport/policy-denials-{slot}"] == "Policy denials: [end]"
               for slot in range(2, 9))


def test_declined_app_requires_previously_authorized_fallback_token(tmp_path) -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    publisher, change, transport = _publisher_fixture(tmp_path, [], now=now)
    with pytest.raises(ValueError, match="authorized GitHub fallback token"):
        publisher.publish(change.id, decline_app=True)
    assert not transport.calls
