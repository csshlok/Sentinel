"""D-08: a Change that still owns a live workspace cannot be deleted (real AppContainer on Windows)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.appcontainer import profile_exists
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.main import create_app
from backend.tests.support_kb import make_repo, write
from backend.tests.workspace.conftest import TEST_PROFILE_PREFIX, teardown_workspaces

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")


@pytest.fixture
def api(tmp_path: Path):
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    manager = app.state.workspace_manager
    manager._prefix = TEST_PROFILE_PREFIX  # swept by the workspace conftest finalizer
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    client.__enter__()
    yield app, client
    teardown_workspaces(manager)
    client.__exit__(None, None, None)


def _change(client: TestClient, repo: Path) -> dict:
    created = client.post("/api/v1/changes", json={
        "title": "delete guard", "intent": "never orphan a workspace",
        "repository_path": str(repo)})
    assert created.status_code == 201, created.text
    return created.json()


def test_a_change_that_never_had_a_workspace_deletes_normally(api, tmp_path) -> None:
    _app, client = api
    change = _change(client, make_repo(tmp_path / "user-repo"))
    deleted = client.delete(f"/api/v1/changes/{change['id']}")
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/changes/{change['id']}").status_code == 404


def test_the_guard_is_absent_from_a_plain_change_service(api) -> None:
    from backend.app.core.change_service import ChangeService

    app, _client = api
    service = app.state.change_service
    plain = ChangeService(service.repository, service.git_inspection, service.verification,
                          service.lifecycle_facts, service.settings)
    assert plain.workspace_guard is None
    assert service.workspace_guard == app.state.workspace_manager.has_live_workspace


@windows_only
def test_delete_is_refused_while_the_workspace_is_live_then_allowed_after_discard(
    api, tmp_path,
) -> None:
    app, client = api
    repo = make_repo(tmp_path / "user-repo", {"README.md": "hello\n"})
    change = _change(client, repo)
    human = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}).json()
    agent = client.post("/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}).json()
    delegation = client.post("/api/v1/delegations", json={
        "grantor_id": human["id"], "grantee_id": agent["id"], "change_id": change["id"],
        "scopes": ["workspace.discard"], "ttl_seconds": 3600})
    assert delegation.status_code == 201, delegation.text

    manager = app.state.workspace_manager
    run_id = uuid4()
    record = manager.ensure(UUID(change["id"]), str(repo), run_id=run_id)
    write(record.workspace_path, "notes.txt", "agent notes\n")
    manager.finish_run(record.id, run_id, facts=None, status="COMPLETED")
    assert manager.get(record.id).state.value == "READY"

    refused = client.delete(f"/api/v1/changes/{change['id']}")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "CHANGE_HAS_LIVE_WORKSPACE"
    assert error["details"] == {"change_id": change["id"]}
    assert client.get(f"/api/v1/changes/{change['id']}").status_code == 200

    discarded = client.post(f"/api/v1/changes/{change['id']}/workspace/discard",
                            json={"actor_id": agent["id"]})
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["state"] == "CLEANED"
    assert profile_exists(record.profile_name) is False

    deleted = client.delete(f"/api/v1/changes/{change['id']}")
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/changes/{change['id']}").status_code == 404
