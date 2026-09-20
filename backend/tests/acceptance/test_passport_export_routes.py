"""Black-box acceptance coverage for signed Passport export (A.7).

Real HTTP API (`TestClient`), a real disposable Git repository, and real
Ed25519 signing/verification -- no mocked crypto. Matches the conventions
in `test_evidence_routes.py`: only the credential store is in-memory.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.app.passport.signing import SIGNING_KEY_CREDENTIAL_NAME, verify
from backend.tests.support_kb import make_repo

FILES = {"app.py": "def add(a, b):\n    return a + b\n"}


def build(tmp_path, *, credential_store=None):
    store = credential_store or InMemoryCredentialStore()
    app = create_app(
        settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
        credential_store=store,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    client.__enter__()
    return client, store


def setup_change(client, repo):
    created = client.post("/api/v1/changes", json={
        "title": "signed export change", "intent": "exercise the signed export route",
        "repository_path": str(repo), "contract": {"required_checks": []}})
    assert created.status_code == 201, created.text
    return created.json()


def test_export_route_requires_authentication(tmp_path):
    client, _ = build(tmp_path)
    change = setup_change(client, make_repo(tmp_path / "repo", FILES))
    del client.headers["Authorization"]

    response = client.post(f"/api/v1/changes/{change['id']}/passport/export")

    assert response.status_code == 401


def test_signing_key_route_requires_authentication(tmp_path):
    client, _ = build(tmp_path)
    del client.headers["Authorization"]

    assert client.get("/api/v1/identity/signing-key").status_code == 401


def test_export_without_a_prior_passport_build_404s_like_the_read_route(tmp_path):
    client, _ = build(tmp_path)
    change = setup_change(client, make_repo(tmp_path / "repo", FILES))
    base = f"/api/v1/changes/{change['id']}"

    assert client.get(f"{base}/passport").status_code == 404
    assert client.post(f"{base}/passport/export").status_code == 404


def test_export_signs_the_already_built_passport_and_verifies_against_the_published_key(
    tmp_path,
):
    repo = make_repo(tmp_path / "repo", FILES)
    client, store = build(tmp_path)
    change = setup_change(client, repo)
    base = f"/api/v1/changes/{change['id']}"

    built = client.post(f"{base}/passport")
    assert built.status_code == 201, built.text

    exported = client.post(f"{base}/passport/export")
    assert exported.status_code == 200, exported.text
    bundle = exported.json()
    assert bundle["passport"]["id"] == built.json()["id"]

    key_response = client.get("/api/v1/identity/signing-key")
    assert key_response.status_code == 200
    public_key = key_response.json()["public_key"]
    assert bundle["signer_public_key"] == public_key

    # Real signature verification, matching `backend/tests/passport/test_signing.py`.
    from backend.app.contracts.models import SignedPassportExport

    parsed_bundle = SignedPassportExport.model_validate(bundle)
    assert verify(parsed_bundle, public_key) is True

    # A tampered copy of the exported content must not verify.
    tampered = parsed_bundle.model_copy(
        update={"passport": parsed_bundle.passport.model_copy(update={"limitations": ["x"]})}
    )
    assert verify(tampered, public_key) is False

    # Re-exporting is idempotent about identity: same underlying passport
    # and signer, real signature both times.
    exported_again = client.post(f"{base}/passport/export")
    assert exported_again.status_code == 200
    assert exported_again.json()["signer_public_key"] == public_key

    # No raw private key material anywhere in any response body.
    raw_private_key = store.get(SIGNING_KEY_CREDENTIAL_NAME)
    assert raw_private_key is not None
    for response in (built, exported, key_response, exported_again):
        assert raw_private_key not in response.text
    assert raw_private_key != bundle["signature"]
    assert raw_private_key != bundle["signer_public_key"]


def test_signing_identity_is_stable_across_a_backend_restart(tmp_path):
    store = InMemoryCredentialStore()
    repo = make_repo(tmp_path / "repo", FILES)
    client, _ = build(tmp_path, credential_store=store)
    change = setup_change(client, repo)
    base = f"/api/v1/changes/{change['id']}"
    client.post(f"{base}/passport")
    first_key = client.get("/api/v1/identity/signing-key").json()["public_key"]

    # A second app instance over the same credential store simulates a
    # backend restart: the signing identity must not change.
    second_client, _ = build(tmp_path, credential_store=store)
    second_key = second_client.get("/api/v1/identity/signing-key").json()["public_key"]

    assert first_key == second_key
