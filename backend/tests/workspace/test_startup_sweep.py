"""D-05 startup trigger: the DB-driven sweep runs when the backend starts.

The database is seeded first (a crashed CREATING row with a real profile and a
READY workspace whose run never finished, with a staged credential file), then
an app is built on that database; its lifespan must reconcile both rows. A
sweep that raises is logged and never blocks startup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts.models import WorkspaceState, utc_now
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.appcontainer import (
    ensure_profile,
    local_appdata_known_folder,
    profile_exists,
)
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.main import create_app
from backend.app.workspace.manager import WorkspaceManager
from backend.app.workspace.models import WorkspaceRecord
from backend.tests.support_kb import make_repo
from backend.tests.workspace.conftest import TEST_PROFILE_PREFIX, teardown_workspaces

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")


def _client(app) -> TestClient:
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    return client


@windows_only
def test_startup_sweep_cleans_crashed_rows_and_purges_interrupted_runs(tmp_path) -> None:
    database_path = tmp_path / "state" / "api.sqlite3"
    database_path.parent.mkdir(parents=True)
    database = Database(database_path)
    database.initialize()
    seeder = WorkspaceManager(database, profile_prefix=TEST_PROFILE_PREFIX)

    now = utc_now()
    creating = seeder.repository.insert(WorkspaceRecord(
        id=uuid4(), change_id=uuid4(), state=WorkspaceState.CREATING,
        profile_name=TEST_PROFILE_PREFIX + uuid4().hex, created_at=now, updated_at=now))
    ensure_profile(creating.profile_name, display_name="Sentinel workspace")
    repo = make_repo(tmp_path / "user-repo", {"README.md": "hello\n"})
    ready = seeder.ensure(uuid4(), str(repo), run_id=uuid4())  # the run never finishes
    staged = ready.container_path / "home" / ".claude" / ".credentials.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text('{"dummy": "not a real credential"}', encoding="utf-8")
    (ready.workspace_path / "unapplied.txt").write_text("agent work\n", encoding="utf-8")
    assert profile_exists(creating.profile_name)

    app = create_app(settings=Settings(database_path=database_path),
                     credential_store=InMemoryCredentialStore())
    manager = app.state.workspace_manager
    try:
        with _client(app) as client:
            assert client.get("/api/v1/health").status_code == 200
            report = app.state.workspace_sweep_report
            assert report is not None
            assert report.cleaned == (creating.id,)
            assert report.preserved == (ready.id,)
            assert report.failed == ()

            assert manager.get(creating.id).state == WorkspaceState.CLEANED
            assert profile_exists(creating.profile_name) is False
            assert not os.path.lexists(
                local_appdata_known_folder() / "Packages" / creating.profile_name)

            swept = manager.get(ready.id)
            assert swept.state == WorkspaceState.READY
            assert swept.active_run_id is None
            assert any("was interrupted before it finished" in item
                       for item in swept.limitations)
            assert not staged.exists()
            assert (ready.workspace_path / "unapplied.txt").read_text(
                encoding="utf-8") == "agent work\n"
    finally:
        teardown_workspaces(manager)
    assert profile_exists(ready.profile_name) is False


def test_a_failing_startup_sweep_is_logged_and_never_blocks_startup(
    tmp_path, monkeypatch, caplog,
) -> None:
    def explode(self, **_kwargs):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(WorkspaceManager, "sweep", explode)
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with caplog.at_level(logging.ERROR, logger="backend.app.main"):
        with _client(app) as client:
            health = client.get("/api/v1/health")
            assert health.status_code == 200, health.text
            assert health.json()["status"] == "ok"
            assert app.state.workspace_sweep_report is None
    assert any("Startup workspace sweep failed" in record.getMessage()
               for record in caplog.records)


def test_a_clean_database_sweeps_nothing_at_startup(tmp_path) -> None:
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with _client(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        report = app.state.workspace_sweep_report
        assert report is not None
        assert (report.cleaned, report.preserved, report.failed) == ((), (), ())
