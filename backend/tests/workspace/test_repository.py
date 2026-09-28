"""Workspace persistence: migration 012, one live workspace per Change, compare-and-set
updates, write-ahead ordering and refusal of an invalid apply-back approval."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.execution.appcontainer import local_appdata_known_folder, profile_failed
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace import manager as manager_module
from backend.app.workspace.manager import WorkspaceManager
from backend.app.workspace.models import WorkspaceRecord
from backend.app.workspace.repository import WorkspaceRepository
from backend.migrations import LATEST_SCHEMA_VERSION
from backend.tests.support_kb import write
from backend.tests.workspace.conftest import TEST_PROFILE_PREFIX, repo_fingerprint

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def _record(change_id=None, *, state=WorkspaceState.CREATING, **changes) -> WorkspaceRecord:
    base = WorkspaceRecord(
        id=uuid4(), change_id=change_id or uuid4(), state=state,
        profile_name=TEST_PROFILE_PREFIX + uuid4().hex, created_at=NOW, updated_at=NOW,
    )
    return dataclasses.replace(base, **changes)


def _schema(database: Database) -> dict[str, str]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE tbl_name = 'change_workspaces'"
        ).fetchall()
    return {row["name"]: row["sql"] or "" for row in rows}


# --------------------------------------------------------------------- migration 012


def test_initialize_twice_creates_change_workspaces_with_its_indexes(tmp_path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    database.initialize()

    assert database.schema_version() == LATEST_SCHEMA_VERSION
    schema = _schema(database)
    assert "change_workspaces" in schema
    assert "REFERENCES" not in schema["change_workspaces"].upper()  # outlives a Change delete
    live_index = schema["idx_change_workspaces_live_change"]
    assert "UNIQUE" in live_index.upper() and "WHERE state != 'CLEANED'" in live_index
    assert "idx_change_workspaces_state" in schema


def test_partial_unique_index_allows_one_live_workspace_per_change(workspace_database) -> None:
    repository = WorkspaceRepository(workspace_database)
    change_id = uuid4()
    first = repository.insert(_record(change_id))

    with pytest.raises(sqlite3.IntegrityError):
        repository.insert(_record(change_id, state=WorkspaceState.READY))

    repository.update(dataclasses.replace(first, state=WorkspaceState.CLEANED),
                      expected_state=WorkspaceState.CREATING)
    second = repository.insert(_record(change_id))
    assert repository.live_for_change(change_id) == second
    assert repository.latest_for_change(change_id).id in {first.id, second.id}
    assert [item.id for item in repository.list_unclean()] == [second.id]


def test_record_round_trips_every_field(workspace_database) -> None:
    repository = WorkspaceRepository(workspace_database)
    record = _record(
        state=WorkspaceState.SEALED,
        package_sid="S-1-15-2-1-2-3-4-5-6-7",
        container_path=Path(r"C:\Users\x\AppData\Local\Packages\p\AC"),
        workspace_path=Path(r"C:\Users\x\AppData\Local\Packages\p\AC\ws"),
        source_repository=Path(r"C:\repo"),
        base_branch="refs/heads/main",
        base_sha="a" * 40,
        sealed_sha="b" * 40,
        applied_sha=None,
        refusal_reason="USER_BRANCH_MOVED",
        approval_digest="c" * 64,
        approved_base_sha="a" * 40,
        approved_sealed_sha="b" * 40,
        active_run_id=str(uuid4()),
        runs=({"run_id": str(uuid4()), "appcontainer": {"integrity_rid": "0x1000",
                                                        "capability_sids": []}},),
        limitations=("one", "two"),
        updated_at=NOW + timedelta(minutes=5),
        cleaned_at=NOW + timedelta(minutes=9),
    )
    repository.insert(record)

    assert repository.get(record.id) == record
    assert repository.get(uuid4()) is None


def test_update_with_a_stale_expected_state_conflicts_and_changes_nothing(
    workspace_database,
) -> None:
    repository = WorkspaceRepository(workspace_database)
    record = repository.insert(_record())
    ready = dataclasses.replace(record, state=WorkspaceState.READY)
    repository.update(ready, expected_state=WorkspaceState.CREATING)

    stale = dataclasses.replace(record, state=WorkspaceState.CLEANED, limitations=("lost",))
    with pytest.raises(AppError) as raised:
        repository.update(stale, expected_state=WorkspaceState.CREATING)

    assert raised.value.code == "WORKSPACE_STATE_CONFLICT"
    assert raised.value.details["state"] == "READY"
    assert repository.get(record.id) == ready


# --------------------------------------------------------------------- write-ahead


def _fake_profile_layer(monkeypatch, tmp_path: Path, events: list[tuple[str, ...]]) -> None:
    def failing_ensure_profile(name, *, display_name):
        events.append(("ensure_profile", name))
        raise profile_failed("create", 0x80070005)

    monkeypatch.setattr(manager_module, "ensure_profile", failing_ensure_profile)
    monkeypatch.setattr(manager_module, "delete_profile", lambda name: None)
    monkeypatch.setattr(manager_module, "profile_exists", lambda name: False)
    monkeypatch.setattr(manager_module, "local_appdata_known_folder", lambda: tmp_path / "lad")


def _spy_inserts(manager: WorkspaceManager, monkeypatch, events) -> None:
    real_insert = manager.repository.insert

    def insert(record, **kwargs):
        events.append(("insert", record.state.value, record.profile_name))
        return real_insert(record, **kwargs)

    monkeypatch.setattr(manager.repository, "insert", insert)


def test_create_writes_the_creating_row_before_the_profile_exists(
    workspace_database, user_repo, tmp_path, monkeypatch,
) -> None:
    events: list[tuple[str, ...]] = []
    _fake_profile_layer(monkeypatch, tmp_path, events)
    manager = WorkspaceManager(workspace_database, profile_prefix=TEST_PROFILE_PREFIX)
    _spy_inserts(manager, monkeypatch, events)
    change_id = uuid4()

    with pytest.raises(AppError) as raised:
        manager.create(change_id, user_repo)

    assert raised.value.code.startswith(("WORKSPACE_", "APPCONTAINER_"))
    assert [event[0] for event in events] == ["insert", "ensure_profile"]
    assert events[0][1] == "CREATING"
    assert events[0][2] == events[1][1]  # the row named the profile before it was created
    record = manager.repository.latest_for_change(change_id)
    assert record is not None and record.profile_name == events[1][1]
    assert record.state in {WorkspaceState.CLEANED, WorkspaceState.CLEANUP_FAILED}


def test_create_never_leaves_a_silent_creating_row_when_cleanup_cannot_run(
    workspace_database, user_repo, tmp_path, monkeypatch,
) -> None:
    events: list[tuple[str, ...]] = []
    _fake_profile_layer(monkeypatch, tmp_path, events)

    def unavailable():
        raise AppError("APPCONTAINER_LAUNCH_FAILED", "known folder lookup failed", status_code=500)

    monkeypatch.setattr(manager_module, "local_appdata_known_folder", unavailable)
    manager = WorkspaceManager(workspace_database, profile_prefix=TEST_PROFILE_PREFIX)
    change_id = uuid4()

    with pytest.raises(AppError) as raised:
        manager.create(change_id, user_repo)

    assert raised.value.code == "WORKSPACE_CLONE_FAILED"
    record = manager.repository.latest_for_change(change_id)
    assert record is not None
    assert record.state == WorkspaceState.CLEANUP_FAILED
    assert record.limitations


# --------------------------------------------------------------------- real Windows


def _test_folders() -> set[str]:
    packages = local_appdata_known_folder() / "Packages"
    return {path.name for path in packages.glob(TEST_PROFILE_PREFIX + "*")}


@windows_only
def test_create_from_a_non_repository_refuses_without_side_effects(
    workspace_manager, tmp_path,
) -> None:
    plain = tmp_path / "plain"
    write(plain, "file.txt", "not a repository\n")
    before = _test_folders()
    change_id = uuid4()

    with pytest.raises(AppError) as raised:
        workspace_manager.create(change_id, plain)

    assert raised.value.code.startswith("WORKSPACE_")
    assert workspace_manager.live_for_change(change_id) is None
    assert workspace_manager.repository.list_unclean() == []
    assert _test_folders() == before


@windows_only
def test_apply_with_a_wrong_token_is_refused_and_touches_nothing(
    workspace_manager, user_repo,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    write(record.workspace_path, "agent.txt", "agent output\n")
    preview = workspace_manager.preview(change_id)
    before = repo_fingerprint(user_repo)

    for token in ("wrong", "", preview.approval_token + "x"):
        with pytest.raises(AppError) as raised:
            workspace_manager.apply(change_id, token)
        assert raised.value.code == "WORKSPACE_APPROVAL_INVALID"

    # A token whose recorded binding no longer matches the sealed commit is refused too.
    sealed = workspace_manager.get(record.id)
    rebound = dataclasses.replace(sealed, approved_sealed_sha="0" * 40)
    workspace_manager.repository.update(rebound, expected_state=WorkspaceState.SEALED)
    with pytest.raises(AppError) as raised:
        workspace_manager.apply(change_id, preview.approval_token)
    assert raised.value.code == "WORKSPACE_APPROVAL_INVALID"

    assert repo_fingerprint(user_repo) == before
    assert not (user_repo / "agent.txt").exists()
    assert workspace_manager.get(record.id).state == WorkspaceState.SEALED
