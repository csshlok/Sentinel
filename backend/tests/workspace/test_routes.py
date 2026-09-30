"""Workspace routes over the real HTTP API: show, preview, policy-gated idempotent apply,
discard and sweep (real AppContainer profiles and real Git on Windows).

The workspace is created through ``app.state.workspace_manager.ensure`` plus host
edits in ``AC\\ws`` and ``finish_run`` (the agent launch path is proven in the
launcher tests); delegations are issued through ``/api/v1/delegations``.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.main import create_app
from backend.app.workspace import manager as manager_module
from backend.tests.support_kb import git, make_repo, write
from backend.tests.workspace.conftest import TEST_PROFILE_PREFIX, teardown_workspaces

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

FACTS = {
    "profile_name": "set-below", "package_sid": "S-1-15-2-1-2-3",
    "is_appcontainer": True, "integrity_rid": "0x1000",
    "capability_sids": ["S-1-15-3-1"], "job_verified": True,
    "verified_at": "2026-09-30T12:00:00+00:00",
}


@pytest.fixture
def api(tmp_path: Path):
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    manager = app.state.workspace_manager
    # Profiles created here must be swept by the workspace conftest finalizer.
    manager._prefix = TEST_PROFILE_PREFIX
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    client.__enter__()
    yield app, client
    teardown_workspaces(manager)
    client.__exit__(None, None, None)


def _setup(client: TestClient, repo: Path, scopes: list[str]):
    created = client.post("/api/v1/changes", json={
        "title": "workspace routes", "intent": "apply agent work back",
        "repository_path": str(repo)})
    assert created.status_code == 201, created.text
    change = created.json()
    human = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}).json()
    agent = client.post("/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}).json()
    delegation = None
    if scopes:
        response = client.post("/api/v1/delegations", json={
            "grantor_id": human["id"], "grantee_id": agent["id"], "change_id": change["id"],
            "scopes": scopes, "ttl_seconds": 3600})
        assert response.status_code == 201, response.text
        delegation = response.json()
    return change, agent["id"], human["id"], delegation


def _repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "user-repo", {
        "calc.py": "def add(a, b):\n    return a + b\n", "README.md": "hello\n"})


def _workspace_with_edits(app, change_id: str, repo: Path):
    manager = app.state.workspace_manager
    run_id = uuid4()
    record = manager.ensure(UUID(change_id), str(repo), run_id=run_id)
    write(record.workspace_path, "calc.py",
          "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    write(record.workspace_path, "notes.txt", "agent notes\n")
    manager.finish_run(record.id, run_id, facts={**FACTS, "profile_name": record.profile_name},
                       status="COMPLETED")
    return record, run_id


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def test_workspace_routes_are_in_the_schema_and_no_forbidden_family(api) -> None:
    app, _client = api
    paths = set(app.openapi()["paths"])
    for path in ("/api/v1/changes/{change_id}/workspace",
                 "/api/v1/changes/{change_id}/workspace/preview",
                 "/api/v1/changes/{change_id}/workspace/apply",
                 "/api/v1/changes/{change_id}/workspace/discard",
                 "/api/v1/workspaces/sweep"):
        assert path in paths, path
    assert not [path for path in paths if "/processes" in path or "/snapshots" in path]


def test_show_is_404_without_a_workspace_and_for_an_unknown_change(api, tmp_path) -> None:
    _app, client = api
    change, *_ = _setup(client, _repo(tmp_path), [])
    missing = client.get(f"/api/v1/changes/{change['id']}/workspace")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "WORKSPACE_NOT_FOUND"
    unknown = client.get(f"/api/v1/changes/{uuid4()}/workspace")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "CHANGE_NOT_FOUND"


def test_sweep_on_a_clean_database_reports_empty_lists(api) -> None:
    _app, client = api
    response = client.post("/api/v1/workspaces/sweep")
    assert response.status_code == 200, response.text
    assert response.json() == {"cleaned": [], "preserved": [], "failed": []}


def test_routes_return_503_when_the_workspace_service_is_absent(api) -> None:
    app, client = api
    # RuntimeServices is frozen; the router reads ``runtime.workspace`` per request.
    object.__setattr__(app.state.runtime_services, "workspace", None)
    response = client.post("/api/v1/workspaces/sweep")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CAPABILITY_UNAVAILABLE"


@windows_only
def test_show_preview_and_delegated_idempotent_apply(api, tmp_path, monkeypatch) -> None:
    app, client = api
    repo = _repo(tmp_path)
    before = _head(repo)
    change, agent, _human, delegation = _setup(client, repo, ["workspace.apply"])
    base = f"/api/v1/changes/{change['id']}/workspace"
    record, run_id = _workspace_with_edits(app, change["id"], repo)

    shown = client.get(base)
    assert shown.status_code == 200, shown.text
    view = shown.json()
    assert view["state"] == "READY"
    assert view["profile_name"] == record.profile_name
    assert view["package_sid"] == record.package_sid
    assert view["workspace_path"] == str(record.workspace_path)
    assert view["base_sha"] == before
    assert view["credential_staged"] is False
    assert view["runs"][0]["run_id"] == str(run_id)
    assert view["runs"][0]["boundary"]["is_appcontainer"] is True
    assert view["runs"][0]["boundary"]["job_verified"] is True
    assert "approval_digest" not in view and "credential_fingerprints" not in view

    preview = client.post(f"{base}/preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["approval_token"] and body["fast_forward_possible"] is True
    assert {item["path"] for item in body["changed_paths"]} == {"calc.py", "notes.txt"}
    assert _head(repo) == before  # preview only reads the user repository

    uses_before = client.get(f"/api/v1/delegations/{delegation['id']}").json()["uses"]
    applied = client.post(f"{base}/apply", json={
        "actor_id": agent, "approval_token": body["approval_token"]})
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["applied"] is True and result["preview"] is None
    assert result["workspace"]["state"] == "CLEANED"
    assert result["workspace"]["applied_sha"] == body["sealed_sha"]
    assert _head(repo) == body["sealed_sha"]
    uses_after_apply = client.get(f"/api/v1/delegations/{delegation['id']}").json()["uses"]
    assert uses_after_apply == uses_before + 1

    after = client.get(base).json()
    assert after["applied_sha"] == body["sealed_sha"] and after["cleaned_at"] is not None

    calls: list[object] = []
    original = manager_module.run_git

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(manager_module, "run_git", spy)
    replay = client.post(f"{base}/apply", json={
        "actor_id": agent, "approval_token": body["approval_token"]})
    assert replay.status_code == 200, replay.text
    assert replay.json()["applied"] is True
    assert replay.json()["workspace"]["applied_sha"] == body["sealed_sha"]
    assert calls == []
    uses_after_replay = client.get(f"/api/v1/delegations/{delegation['id']}").json()["uses"]
    assert uses_after_replay == uses_after_apply

    wrong = client.post(f"{base}/apply", json={"actor_id": agent, "approval_token": "nope"})
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "WORKSPACE_APPROVAL_INVALID"


@windows_only
def test_apply_without_delegation_is_denied_and_journaled(api, tmp_path) -> None:
    app, client = api
    repo = _repo(tmp_path)
    before = _head(repo)
    change, agent, _human, _delegation = _setup(client, repo, [])
    base = f"/api/v1/changes/{change['id']}/workspace"
    _workspace_with_edits(app, change["id"], repo)
    token = client.post(f"{base}/preview").json()["approval_token"]

    denied = client.post(f"{base}/apply", json={"actor_id": agent, "approval_token": token})
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] != "WORKSPACE_APPROVAL_INVALID"
    assert client.get(base).json()["state"] == "SEALED"
    assert _head(repo) == before
    events = client.get(f"/api/v1/changes/{change['id']}/events").json()["items"]
    denials = [event for event in events if event["event_type"] == "policy.decision.denied"]
    assert denials and denials[-1]["payload"]["operation"] == "workspace.apply"
    assert token not in str(events)


@windows_only
def test_moved_user_branch_refuses_with_a_token_less_preview(api, tmp_path) -> None:
    app, client = api
    repo = _repo(tmp_path)
    change, agent, _human, _delegation = _setup(client, repo, ["workspace.apply"])
    base = f"/api/v1/changes/{change['id']}/workspace"
    _workspace_with_edits(app, change["id"], repo)
    token = client.post(f"{base}/preview").json()["approval_token"]
    write(repo, "user.txt", "user moved on\n")
    git(repo, "add", "user.txt")
    git(repo, "commit", "-q", "-m", "user commit")
    moved = _head(repo)

    response = client.post(f"{base}/apply", json={"actor_id": agent, "approval_token": token})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["applied"] is False
    assert result["workspace"]["state"] == "APPLY_REFUSED"
    assert result["workspace"]["refusal_reason"] == "USER_BRANCH_MOVED"
    assert result["preview"]["refusal_reason"] == "USER_BRANCH_MOVED"
    assert result["preview"]["approval_token"] is None
    assert result["preview"]["fast_forward_possible"] is False
    assert {item["path"] for item in result["preview"]["changed_paths"]} == {
        "calc.py", "notes.txt"}
    assert _head(repo) == moved


@windows_only
def test_discard_requires_a_discard_delegation(api, tmp_path) -> None:
    app, client = api
    repo = _repo(tmp_path)
    change, agent, human, _delegation = _setup(client, repo, ["workspace.discard"])
    base = f"/api/v1/changes/{change['id']}/workspace"
    _workspace_with_edits(app, change["id"], repo)

    refused = client.post(f"{base}/discard", json={"actor_id": human})
    assert refused.status_code == 403, refused.text
    assert client.get(base).json()["state"] == "READY"

    discarded = client.post(f"{base}/discard", json={"actor_id": agent})
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["state"] == "CLEANED"
    assert discarded.json()["cleaned_at"] is not None
