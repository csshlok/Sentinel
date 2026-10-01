"""Manifest flow uses a one-shot loopback callback and broker-only secret storage."""

from __future__ import annotations

import http.client
import json
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.providers.github_app import (
    GitHubAppManifestFlow, GitHubAppManifestFlows, app_provider_name,
)
from backend.tests.providers.fakes import FakeHttpTransport, json_response


def _flow(*, owner: str = "example", response: object | None = None) -> tuple[
    GitHubAppManifestFlow, CredentialBroker, FakeHttpTransport
]:
    broker = CredentialBroker(InMemoryCredentialStore())
    transport = FakeHttpTransport([json_response(201, response or {
        "id": 42, "slug": "sentinel-example",
        "pem": "-----BEGIN RSA PRIVATE KEY-----\nsecret-canary\n-----END RSA PRIVATE KEY-----",
        "webhook_secret": "webhook-canary",
        "owner": {"login": owner, "type": "Organization"},
    })])
    flow = GitHubAppManifestFlow(
        owner=owner, account_kind="organization", broker=broker,
        transport=transport, timeout_seconds=2,
    )
    return flow, broker, transport


def _callback(flow: GitHubAppManifestFlow, *, state: str, consume: bool = True) -> tuple[int, bytes]:
    assert flow._server is not None
    connection = http.client.HTTPConnection("127.0.0.1", flow._server.server_address[1],
                                            timeout=2)
    connection.request("GET", f"/callback?code=one-use-code&state={state}")
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    assert flow._thread is not None
    if consume:
        flow._thread.join(2)
    return result


def test_manifest_callback_stores_only_broker_secret_once() -> None:
    flow, broker, transport = _flow()
    started = flow.start()
    assert started.status == "PENDING"
    assert started.registration_url is not None
    assert started.registration_url.startswith("http://127.0.0.1:")
    page = flow.registration_html()
    assert "method='post'" in page
    assert "github.com/organizations/example/settings/apps/new" in page
    assert "127.0.0.1" in page
    assert "secret-canary" not in page
    assert "webhook-canary" not in page
    registration = urlsplit(started.registration_url)
    browser = http.client.HTTPConnection(registration.hostname, registration.port, timeout=2)
    browser.request("GET", registration.path)
    response = browser.getresponse()
    assert response.status == 200
    assert b"Create Sentinel GitHub App" in response.read()
    browser.close()
    assert _callback(flow, state=flow._state) == (
        200, b"Sentinel GitHub App registration complete.")
    view = flow.view()
    assert view.status == "COMPLETE"
    assert view.app_slug == "sentinel-example"
    assert view.registration_url is None
    assert "secret-canary" not in repr(view)
    assert "webhook-canary" not in repr(view)
    grant = broker.issue_grant(uuid4(), uuid4(),
                               [f"{app_provider_name('example')}.publish"], 10)
    stored = json.loads(broker.resolve_secret(grant.id,
                                              scope=f"{app_provider_name('example')}.publish"))
    assert stored["id"] == 42
    assert stored["webhook_secret"] == "webhook-canary"
    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == (
        "https://api.github.com/app-manifests/one-use-code/conversions")
    with pytest.raises(OSError):
        _callback(flow, state=flow._state)


def test_favicon_and_wrong_state_leave_flow_pending_until_valid_callback() -> None:
    flow, broker, transport = _flow()
    flow.start()
    assert flow._server is not None
    connection = http.client.HTTPConnection("127.0.0.1", flow._server.server_address[1], timeout=2)
    connection.request("GET", "/favicon.ico")
    response = connection.getresponse()
    assert response.status == 404
    response.read()
    connection.close()
    assert _callback(flow, state="wrong-state", consume=False)[0] == 400
    assert flow.view().status == "PENDING"
    assert not transport.calls
    assert broker.store.get(f"provider:{app_provider_name('example')}") is None
    assert _callback(flow, state=flow._state)[0] == 200
    assert flow.view().status == "COMPLETE"


def test_malformed_conversion_fails_closed_and_hides_response() -> None:
    flow, broker, _ = _flow(response={"id": 42, "slug": "bad", "pem": "secret-canary"})
    flow.start()
    status, body = _callback(flow, state=flow._state)
    assert status == 400
    assert b"secret-canary" not in body
    assert "secret-canary" not in repr(flow.view())
    assert broker.store.get(f"provider:{app_provider_name('example')}") is None


@pytest.mark.parametrize("owner", [
    {"login": "someone-else", "type": "Organization"},
    {"login": "example", "type": "User"},
    None,
])
def test_converted_app_owner_must_match_request(owner) -> None:
    response = {"id": 42, "slug": "sentinel-example",
                "pem": "-----BEGIN RSA PRIVATE KEY-----\nsecret-canary\n-----END RSA PRIVATE KEY-----",
                "owner": owner}
    flow, broker, _ = _flow(response=response)
    flow.start()
    assert _callback(flow, state=flow._state)[0] == 400
    assert flow.view().status == "FAILED"
    assert flow.view().reason == "APP_OWNER_MISMATCH"
    assert broker.store.get(f"provider:{app_provider_name('example')}") is None


def test_owner_namespaces_are_distinct_and_validated() -> None:
    assert app_provider_name("Alice") != app_provider_name("Bob")
    with pytest.raises(ValueError):
        app_provider_name("../../other")


def test_pending_flow_registry_rejects_duplicate_owner() -> None:
    _, broker, transport = _flow()
    flows = GitHubAppManifestFlows(broker, transport=transport)
    first = flows.create(owner="Example", account_kind="user")
    assert flows.get(first.flow_id) == first
    with pytest.raises(ValueError, match="already pending"):
        flows.create(owner="example", account_kind="user")
    assert flows.get("unknown") is None
    _callback(flows._flows[first.flow_id], state="wrong-state")


def test_manifest_api_routes_do_not_expose_app_credentials(tmp_path) -> None:
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        started = client.post("/api/v1/providers/github/app/flows", json={
            "owner": "example", "account_kind": "user",
        })
        assert started.status_code == 201
        data = started.json()
        assert data["status"] == "PENDING"
        assert data["registration_url"].startswith("http://127.0.0.1:")
        assert "pem" not in started.text and "webhook_secret" not in started.text
        observed = client.get(f"/api/v1/providers/github/app/flows/{data['flow_id']}")
        assert observed.status_code == 200
        assert observed.json()["status"] == "PENDING"
        status = client.get("/api/v1/providers/github/app/status/example")
        assert status.status_code == 200
        assert status.json() == {"owner": "example", "configured": False}
        url = urlsplit(data["registration_url"])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
        conn.request("GET", "/callback?code=bad&state=wrong")
        assert conn.getresponse().status == 400
        conn.close()

