"""Unit tests for confined check boxes with a fake AppContainer layer (no real profile)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.contracts.models import ChangeContract, JournalEventType
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.execution.appcontainer import remove_tree_no_follow
from backend.app.execution.check_box import BoxPlatform, CheckBoxes
from backend.app.execution.check_repository import (
    CheckRunRecord,
    CheckRunRepository,
    CheckRunState,
    RuntimeGrant,
)

FAKE_SID = "S-1-15-2-1111111111-2222222222-3333333333-444444444-555555555-666666666-777777777"


# ---------------------------------------------------------------------- fakes


class FakeWindows:
    """Profiles as a set and a fake LocalAppData folder under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles: set[str] = set()
        self.revoked: list[tuple[str, str]] = []
        self.granted: list[tuple[str, str]] = []
        self.order: list[str] = []
        self.fail_revoke = False
        self.fail_delete = False

    def derive_package_sid(self, name: str) -> str:
        return FAKE_SID

    def container_folder(self, sid: str) -> Path:
        raise AssertionError("not used by a fake box")

    def local_appdata(self) -> Path:
        return self.root

    def ensure_profile(self, name: str, *, display_name: str):
        self.order.append(f"profile:{name}")
        self.profiles.add(name)
        container = self.root / "Packages" / name / "AC"
        container.mkdir(parents=True, exist_ok=True)
        from backend.app.execution.appcontainer import AppContainerProfile

        return AppContainerProfile(name, FAKE_SID, container), True

    def delete_profile(self, name: str) -> None:
        if self.fail_delete:
            raise AppError("APPCONTAINER_PROFILE_FAILED", "x", details={"hresult": "0x80070005"})
        self.order.append(f"delete:{name}")
        self.profiles.discard(name)
        remove_tree_no_follow(self.root / "Packages" / name)

    def profile_exists(self, name: str) -> bool:
        return name in self.profiles

    def grant(self, path, sid, *, allowed_root=None) -> None:
        self.order.append("grant")
        self.granted.append((str(path), sid))

    def revoke(self, path, sid, *, allowed_root=None) -> None:
        if self.fail_revoke:
            raise AppError("CHECK_RUNTIME_GRANT_FAILED", "x", status_code=500)
        self.order.append("revoke")
        self.revoked.append((str(path), sid))

    def platform(self, **overrides) -> BoxPlatform:
        values = dict(
            derive_package_sid=self.derive_package_sid, ensure_profile=self.ensure_profile,
            delete_profile=self.delete_profile, profile_exists=self.profile_exists,
            container_folder=self.container_folder, local_appdata=self.local_appdata,
            grant=self.grant, revoke=self.revoke,
        )
        values.update(overrides)
        return BoxPlatform(**values)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "checks.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def windows(tmp_path: Path) -> FakeWindows:
    root = tmp_path / "localappdata"
    root.mkdir()
    return FakeWindows(root)


def _make_change(database: Database) -> UUID:
    now = datetime.now(UTC)
    change_id = uuid4()
    ChangeRepository(database).create(StoredChange(
        id=change_id, title="Check box", intent="Exercise check boxes",
        repository_path="C:\\work\\repo", created_at=now, updated_at=now,
        last_refreshed_at=None, git_summary=None, verification=None,
        contract=ChangeContract(),
    ))
    return change_id


def _record(change_id: UUID, profile: str, *, state=CheckRunState.CREATING,
            grants: tuple[RuntimeGrant, ...] = ()) -> CheckRunRecord:
    now = datetime.now(UTC)
    return CheckRunRecord(
        id=uuid4(), change_id=change_id, profile_name=profile, package_sid=FAKE_SID,
        state=state, network=False, runtime_grants=grants, created_at=now, updated_at=now,
    )


def _events(database: Database, change_id: UUID) -> list[dict]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT event_type, subject_type, subject_id, payload_json FROM journal_events "
            "WHERE change_id = ? ORDER BY seq", (str(change_id),),
        ).fetchall()
    return [{"type": row["event_type"], "subject_type": row["subject_type"],
             "subject_id": row["subject_id"], "payload": json.loads(row["payload_json"])}
            for row in rows]


# ---------------------------------------------------------------------- task 1


def test_migration_creates_check_runs_without_a_change_foreign_key(database: Database) -> None:
    with database.connection() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(check_runs)")}
        foreign = connection.execute("PRAGMA foreign_key_list(check_runs)").fetchall()
    assert columns == {
        "id", "change_id", "profile_name", "package_sid", "state", "network", "tree_digest",
        "runtime_digests_json", "facts_json", "exit_code", "timed_out", "created_at",
        "updated_at",
    }
    assert foreign == []


def test_repository_round_trip_and_compare_and_set(database: Database) -> None:
    repository = CheckRunRepository(database)
    grant = RuntimeGrant("C:\\cache\\python\\" + "a" * 64, "a" * 64)
    record = repository.insert(_record(uuid4(), "sentinel.test.x1", grants=(grant,)))
    loaded = repository.get(record.id)
    assert loaded is not None
    assert loaded.state is CheckRunState.CREATING and loaded.runtime_grants == (grant,)
    assert loaded.network is False and loaded.timed_out is None

    ready = repository.update(
        CheckRunRecord(**{**{f: getattr(loaded, f) for f in loaded.__slots__},
                          "state": CheckRunState.READY, "tree_digest": "b" * 64}),
        expected_state=CheckRunState.CREATING,
    )
    assert repository.get(record.id).tree_digest == "b" * 64
    with pytest.raises(AppError) as error:
        repository.update(ready, expected_state=CheckRunState.CREATING)
    assert error.value.code == "CHECK_RUN_STATE_CONFLICT"
    assert error.value.details["state"] == "READY"
    assert [item.id for item in repository.list_unclean()] == [record.id]


def test_journaled_transition_commits_with_the_row(database: Database, windows) -> None:
    journal = JournalWriter(database)
    boxes = CheckBoxes(database, journal=journal, profile_prefix="sentinel.test.",
                       platform=windows.platform())
    change_id = _make_change(database)
    record = boxes.repository.insert(_record(change_id, "sentinel.test.j1",
                                             state=CheckRunState.RUNNING))
    boxes._save(record, CheckRunState.RUNNING, state=CheckRunState.FINISHED, exit_code=0,
                timed_out=False, event=JournalEventType.CHECK_CONFINED_RUN,
                payload={"boundary": "APPCONTAINER"})
    assert boxes.repository.get(record.id).state is CheckRunState.FINISHED
    events = _events(database, change_id)
    assert [event["type"] for event in events] == ["check.confined_run"]
    assert events[0]["subject_type"] == "check_run"
    assert events[0]["subject_id"] == str(record.id)


def test_failed_journal_append_rolls_the_transition_back(database: Database, windows) -> None:
    class ExplodingJournal(JournalWriter):
        def append(self, *args, **kwargs):
            raise RuntimeError("journal down")

    boxes = CheckBoxes(database, journal=ExplodingJournal(database),
                       profile_prefix="sentinel.test.", platform=windows.platform())
    change_id = _make_change(database)
    record = boxes.repository.insert(_record(change_id, "sentinel.test.j2",
                                             state=CheckRunState.RUNNING))
    with pytest.raises(RuntimeError):
        boxes._save(record, CheckRunState.RUNNING, state=CheckRunState.FINISHED,
                    event=JournalEventType.CHECK_CONFINED_RUN, payload={})
    assert boxes.repository.get(record.id).state is CheckRunState.RUNNING


def test_journal_append_is_skipped_when_the_change_is_gone(database: Database, windows) -> None:
    boxes = CheckBoxes(database, journal=JournalWriter(database),
                       profile_prefix="sentinel.test.", platform=windows.platform())
    record = boxes.repository.insert(_record(uuid4(), "sentinel.test.j3",
                                             state=CheckRunState.RUNNING))
    boxes._save(record, CheckRunState.RUNNING, state=CheckRunState.FINISHED,
                event=JournalEventType.CHECK_CONFINED_RUN, payload={})
    assert boxes.repository.get(record.id).state is CheckRunState.FINISHED


def _leftover_box(windows: FakeWindows, boxes: CheckBoxes, tmp_path: Path,
                  state: CheckRunState) -> tuple[CheckRunRecord, Path]:
    name = "sentinel.test." + uuid4().hex
    entry = tmp_path / "cache" / "python" / ("c" * 64)
    entry.mkdir(parents=True, exist_ok=True)
    record = boxes.repository.insert(_record(
        uuid4(), name, state=state, grants=(RuntimeGrant(str(entry), "c" * 64),)))
    windows.ensure_profile(name, display_name="x")
    container = windows.root / "Packages" / name / "AC"
    for sub in ("tree", "scratch"):
        (container / sub).mkdir()
        (container / sub / "file.txt").write_text("x", encoding="utf-8")
    return record, container


@pytest.mark.parametrize("state", [CheckRunState.CREATING, CheckRunState.READY,
                                   CheckRunState.RUNNING, CheckRunState.FINISHED,
                                   CheckRunState.CLEANUP_FAILED])
def test_sweep_cleans_every_unclean_row(database, windows, tmp_path, state) -> None:
    boxes = CheckBoxes(database, profile_prefix="sentinel.test.",
                       runtime_root=tmp_path / "cache", platform=windows.platform())
    record, container = _leftover_box(windows, boxes, tmp_path, state)
    report = boxes.sweep()
    assert report.cleaned == (record.id,) and report.failed == ()
    assert boxes.repository.get(record.id).state is CheckRunState.CLEANED
    assert not os.path.lexists(container.parent)
    assert record.profile_name not in windows.profiles
    assert windows.revoked == [(record.runtime_grants[0].path, FAKE_SID)]
    # ACEs are revoked before anything is removed and the profile goes last.
    assert windows.order[-2:] == ["revoke", f"delete:{record.profile_name}"]


def test_sweep_records_cleanup_failed_and_continues(database, windows, tmp_path) -> None:
    boxes = CheckBoxes(database, profile_prefix="sentinel.test.",
                       runtime_root=tmp_path / "cache", platform=windows.platform())
    first, container = _leftover_box(windows, boxes, tmp_path, CheckRunState.READY)
    windows.fail_revoke = True
    report = boxes.sweep()
    assert report.cleaned == ()
    assert [item for item, _ in report.failed] == [first.id]
    assert "revoke" in report.failed[0][1]
    assert boxes.repository.get(first.id).state is CheckRunState.CLEANUP_FAILED
    # Nothing was deleted while an ACE could not be revoked.
    assert first.profile_name in windows.profiles and container.is_dir()

    windows.fail_revoke = False
    assert boxes.sweep().cleaned == (first.id,)
    assert boxes.repository.get(first.id).state is CheckRunState.CLEANED


def test_sweep_skips_live_boxes_and_never_touches_unrecorded_profiles(
    database, windows, tmp_path,
) -> None:
    boxes = CheckBoxes(database, profile_prefix="sentinel.test.",
                       runtime_root=tmp_path / "cache", platform=windows.platform())
    record, container = _leftover_box(windows, boxes, tmp_path, CheckRunState.RUNNING)
    windows.ensure_profile("sentinel.test.unrecorded", display_name="x")
    assert boxes.sweep(live_run_ids={record.id}).cleaned == ()
    assert container.is_dir()
    assert boxes.sweep().cleaned == (record.id,)
    assert "sentinel.test.unrecorded" in windows.profiles


def test_cleanup_failure_on_profile_delete_is_cleanup_failed(database, windows, tmp_path) -> None:
    boxes = CheckBoxes(database, profile_prefix="sentinel.test.",
                       runtime_root=tmp_path / "cache", platform=windows.platform())
    record, _ = _leftover_box(windows, boxes, tmp_path, CheckRunState.FINISHED)
    windows.fail_delete = True
    with pytest.raises(AppError) as error:
        boxes.cleanup(record.id)
    assert error.value.code == "CHECK_BOX_CLEANUP_FAILED"
    assert boxes.repository.get(record.id).state is CheckRunState.CLEANUP_FAILED


def _client(app):
    from fastapi.testclient import TestClient

    return TestClient(app, headers={"Authorization": f"Bearer {app.state.api_token}"})


def test_startup_runs_the_check_sweep_and_survives_its_failure(
    tmp_path, monkeypatch, caplog,
) -> None:
    from backend.app.core.config import Settings
    from backend.app.credentials.memory_store import InMemoryCredentialStore
    from backend.app.main import create_app

    app = create_app(settings=Settings(database_path=tmp_path / "a" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with _client(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        report = app.state.check_sweep_report
        assert report is not None and (report.cleaned, report.failed) == ((), ())

    def explode(self, **_kwargs):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(CheckBoxes, "sweep", explode)
    app = create_app(settings=Settings(database_path=tmp_path / "b" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with caplog.at_level(logging.ERROR, logger="backend.app.main"):
        with _client(app) as client:
            assert client.get("/api/v1/health").status_code == 200
            assert app.state.check_sweep_report is None
    assert any("Startup check box sweep failed" in item.getMessage() for item in caplog.records)
