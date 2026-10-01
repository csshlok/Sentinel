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


# ---------------------------------------------------------------------- task 2

import subprocess
import sys

from backend.app.execution.appcontainer import AppContainerFacts
from backend.app.execution.check_box import (
    BoxRuntime,
    CheckBox,
    CheckRunFacts,
    argv_digest,
    python_box_runtime,
)
from backend.app.execution.check_runtime import PythonRuntime, RuntimeSnapshot
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.support_kb import git, make_repo, write

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows-only")
FAKE_BASE_ENV_KEYS = {"SystemRoot", "windir", "COMSPEC", "PATH", "LOCALAPPDATA", "TEMP", "TMP"}


class FakeSpawn:
    """Runs argv as a plain host child (no box) and attaches fake verified facts."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.refuse = False

    def __call__(self, argv, *, cwd, env, redact, profile_name, expected_package_sid,
                 capabilities):
        self.calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env),
                           "profile_name": profile_name, "sid": expected_package_sid,
                           "capabilities": tuple(capabilities)})
        if self.refuse:
            raise AppError("APPCONTAINER_VERIFICATION_FAILED", "x", status_code=500)
        process = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(os.environ), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        process.appcontainer = AppContainerFacts(
            profile_name=profile_name, package_sid=expected_package_sid, is_appcontainer=True,
            integrity_rid=0x1000,
            capability_sids=tuple("S-1-15-3-1" for _ in capabilities),
            job_verified=True, verified_at=datetime.now(UTC),
        )
        return process


def _fake_base_environment(windows: FakeWindows):
    def base_environment(container, *, path_entries=()):
        temp = Path(container) / "Temp"
        temp.mkdir(parents=True, exist_ok=True)
        return {"SystemRoot": "C:\\Windows", "windir": "C:\\Windows",
                "COMSPEC": "C:\\Windows\\System32\\cmd.exe",
                "PATH": ";".join([*(str(p) for p in path_entries), "C:\\Windows\\System32"]),
                "LOCALAPPDATA": str(windows.root), "TEMP": str(temp), "TMP": str(temp)}
    return base_environment


@pytest.fixture
def spawn() -> FakeSpawn:
    return FakeSpawn()


@pytest.fixture
def boxes(database, windows, spawn, tmp_path) -> CheckBoxes:
    return CheckBoxes(
        database, journal=JournalWriter(database), profile_prefix="sentinel.test.",
        runtime_root=tmp_path / "cache",
        platform=windows.platform(spawn=spawn,
                                  base_environment=_fake_base_environment(windows)),
    )


@pytest.fixture
def runtime(tmp_path) -> BoxRuntime:
    entry = tmp_path / "cache" / "python" / ("d" * 64)
    deps = tmp_path / "cache" / "python-deps" / ("e" * 64)
    entry.mkdir(parents=True)
    deps.mkdir(parents=True)
    return python_box_runtime(PythonRuntime(RuntimeSnapshot(entry, "d" * 64, 0),
                                            RuntimeSnapshot(deps, "e" * 64, 0), ()))


@pytest.fixture
def repo(tmp_path) -> Path:
    root = make_repo(tmp_path / "repo", {
        "calc.py": "def add(a, b):\n    return a + b\n",
        "pkg/mod.py": "VALUE = 1\n",
        "deleted.txt": "gone soon\n",
        ".gitignore": ".env\n.venv/\nnode_modules/\nbuild/\n",
    })
    (root / "deleted.txt").unlink()
    write(root, "untracked.py", "NEW = 2\n")
    write(root, ".env", "SECRET=canary-0123456789\n")
    write(root, ".venv/lib/site.py", "x = 1\n")
    write(root, "node_modules/left-pad/index.js", "module.exports = 1\n")
    return root


def _tree_files(tree: Path) -> set[str]:
    return {path.relative_to(tree).as_posix() for path in tree.rglob("*") if path.is_file()}


def test_box_copies_tracked_and_untracked_never_ignored_or_deleted(
    boxes, windows, repo, runtime, database,
) -> None:
    change_id = _make_change(database)
    rows_at_profile: list[int] = []
    original = windows.ensure_profile

    def ensure_profile(name, *, display_name):
        rows_at_profile.append(len(boxes.repository.list_unclean()))
        return original(name, display_name=display_name)

    boxes._platform = windows.platform(ensure_profile=ensure_profile, spawn=FakeSpawn(),
                                       base_environment=_fake_base_environment(windows))
    with CheckBox.open(boxes, change_id, repo, runtime) as box:
        assert _tree_files(box.tree) == {".gitignore", "calc.py", "pkg/mod.py", "untracked.py"}
        record = boxes.repository.get(box.id)
        assert record.state is CheckRunState.READY
        assert record.tree_digest == box.tree_digest and len(box.tree_digest) == 64
        assert box.profile_name.startswith("sentinel.test.")
        assert box.scratch.is_dir()
        assert sorted(path for path, _ in windows.granted) == sorted(
            str(snapshot.path) for snapshot in runtime.snapshots)
        first_digest = box.tree_digest
    # The row existed before the profile was created.
    assert rows_at_profile == [1]
    assert boxes.repository.get(box.id).state is CheckRunState.CLEANED
    assert box.profile_name not in windows.profiles
    assert not (windows.root / "Packages" / box.profile_name).exists()
    assert sorted(path for path, _ in windows.revoked) == sorted(
        str(snapshot.path) for snapshot in runtime.snapshots)

    with boxes.open(change_id, repo, runtime) as again:
        assert again.tree_digest == first_digest
    (repo / "untracked.py").write_text("NEW = 3\n", encoding="utf-8")
    with boxes.open(change_id, repo, runtime) as changed:
        assert changed.tree_digest != first_digest


def _assert_refused_before_anything(boxes, windows, change_id, repo, runtime, code,
                                    **kwargs) -> None:
    with pytest.raises(AppError) as error:
        boxes.open(change_id, repo, runtime, **kwargs)
    assert error.value.code == code
    assert boxes.repository.list_unclean() == []
    assert windows.profiles == set()


def test_gitlink_and_embedded_repository_are_refused(boxes, windows, repo, runtime) -> None:
    head = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},vendored")
    _assert_refused_before_anything(boxes, windows, uuid4(), repo, runtime,
                                    "CHECK_TREE_GITLINK")
    git(repo, "update-index", "--force-remove", "vendored")
    make_repo(repo / "nested")
    _assert_refused_before_anything(boxes, windows, uuid4(), repo, runtime,
                                    "CHECK_TREE_GITLINK")


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_hidden_index_entries_are_refused(boxes, windows, repo, runtime, flag) -> None:
    git(repo, "update-index", flag, "calc.py")
    _assert_refused_before_anything(boxes, windows, uuid4(), repo, runtime,
                                    "CHECK_TREE_HIDDEN_INDEX_ENTRY")


def test_tree_over_the_size_limit_is_refused(boxes, windows, repo, runtime) -> None:
    _assert_refused_before_anything(boxes, windows, uuid4(), repo, runtime,
                                    "CHECK_TREE_TOO_LARGE", size_limit=10)


@windows_only
def test_reparse_point_on_a_listed_path_is_refused(boxes, windows, repo, runtime,
                                                   tmp_path) -> None:
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mod.py").write_text("STOLEN = 1\n", encoding="utf-8")
    remove_tree_no_follow(repo / "pkg")
    _winapi.CreateJunction(str(outside), str(repo / "pkg"))
    _assert_refused_before_anything(boxes, windows, uuid4(), repo, runtime,
                                    "CHECK_TREE_REPARSE_POINT")


def test_a_failed_open_after_the_profile_cleans_up(boxes, windows, repo, runtime) -> None:
    def grant(*_args, **_kwargs):
        raise AppError("CHECK_RUNTIME_GRANT_FAILED", "x", status_code=500)

    boxes._platform = windows.platform(grant=grant)
    change_id = uuid4()
    with pytest.raises(AppError) as error:
        boxes.open(change_id, repo, runtime)
    assert error.value.code == "CHECK_RUNTIME_GRANT_FAILED"
    rows = boxes.repository.for_change(change_id)
    assert [row.state for row in rows] == [CheckRunState.CLEANED]
    assert windows.profiles == set()
    assert not any((windows.root / "Packages").iterdir())


def test_runtime_may_not_override_base_environment_keys() -> None:
    with pytest.raises(ValueError):
        BoxRuntime(env={"Path": "C:\\evil"})
    with pytest.raises(ValueError):
        BoxRuntime(env={"LOCALAPPDATA": "C:\\elsewhere"})


def test_python_box_runtime_points_at_the_snapshots(runtime) -> None:
    interpreter, deps = runtime.snapshots
    assert dict(runtime.env) == {
        "PYTHONHOME": str(interpreter.path), "PYTHONPATH": str(deps.path),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
    }
    assert runtime.executable == interpreter.path / "python.exe"


PROBE = ("import os, sys; open(os.path.join('..', 'scratch', 'out.txt'), 'w').write('made'); "
         "print('x' * 5000); sys.exit(3)")


def test_run_uses_the_box_environment_tree_and_no_capabilities(
    boxes, spawn, repo, runtime, database,
) -> None:
    change_id = _make_change(database)
    with boxes.open(change_id, repo, runtime) as box:
        with pytest.raises(AppError) as error:
            box.run(["python", "-c", "pass"], timeout=30, limit=100)
        assert error.value.code == "CHECK_BOX_INVALID_ARGV"
        assert spawn.calls == []

        argv = [sys.executable, "-c", PROBE]
        result = box.run(argv, timeout=60, limit=1000)
        assert isinstance(result, CheckRunFacts)
        call = spawn.calls[0]
        assert call["cwd"] == box.tree
        assert set(call["env"]) == FAKE_BASE_ENV_KEYS | set(runtime.env)
        assert call["env"]["PYTHONHOME"] == runtime.env["PYTHONHOME"]
        assert call["capabilities"] == ()
        assert call["profile_name"] == box.profile_name and call["sid"] == box.package_sid
        assert result.exit_code == 3 and result.timed_out is False
        assert len(result.stdout) == 1000 and result.truncated is True
        assert result.boundary == "APPCONTAINER" and result.capabilities == ()
        assert result.argv_sha256 == argv_digest(argv)
        assert box.read_output("out.txt", 100) == b"made"
        record = boxes.repository.get(box.id)
        assert record.state is CheckRunState.FINISHED and record.exit_code == 3
        assert record.facts["is_appcontainer"] is True

    events = _events(database, change_id)
    assert [event["type"] for event in events] == ["check.confined_run"]
    payload = events[0]["payload"]
    assert payload["boundary"] == "APPCONTAINER"
    assert payload["profile_name"] == record.profile_name
    assert payload["package_sid"] == FAKE_SID
    assert payload["capabilities"] == [] and payload["network"] is False
    assert payload["argv_sha256"] == argv_digest(argv)
    assert payload["tree_manifest_digest"] == record.tree_digest
    assert payload["runtime_manifest_digests"] == ["d" * 64, "e" * 64]
    assert payload["exit_code"] == 3 and payload["timed_out"] is False
    text = json.dumps(events[0])
    # No argv text, output or host paths are journaled.
    assert "scratch" not in text and "x" * 50 not in text
    assert json.dumps(str(repo))[1:-1] not in text
    assert Path(sys.executable).name not in text


def test_network_box_requests_only_internet_client(boxes, spawn, repo, runtime) -> None:
    with boxes.open(uuid4(), repo, runtime, network=True) as box:
        result = box.run([sys.executable, "-c", "pass"], timeout=60, limit=100)
    assert spawn.calls[0]["capabilities"] == ("internetClient",)
    assert result.capabilities == ("internetClient",) and result.network is True
    assert boxes.repository.get(box.id).network is True


def test_timeout_is_reported(boxes, repo, runtime) -> None:
    with boxes.open(uuid4(), repo, runtime) as box:
        result = box.run([sys.executable, "-c", "import time; time.sleep(30)"],
                         timeout=1, limit=100)
    assert result.timed_out is True and result.exit_code is None


def test_a_refused_launch_is_not_journaled(boxes, spawn, repo, runtime, database) -> None:
    change_id = _make_change(database)
    spawn.refuse = True
    with boxes.open(change_id, repo, runtime) as box:
        with pytest.raises(AppError):
            box.run([sys.executable, "-c", "pass"], timeout=10, limit=100)
        assert boxes.repository.get(box.id).state is CheckRunState.FINISHED
    assert _events(database, change_id) == []
    assert boxes.repository.get(box.id).state is CheckRunState.CLEANED


def test_read_output_stays_inside_scratch(boxes, repo, runtime, tmp_path) -> None:
    outside = tmp_path / "outside-scratch"
    with boxes.open(uuid4(), repo, runtime) as box:
        (box.scratch / "sub").mkdir()
        (box.scratch / "sub" / "report.json").write_bytes(b"{}")
        (box.scratch / "big.bin").write_bytes(b"0" * 200)
        assert box.read_output("sub/report.json", 10) == b"{}"
        assert box.read_output("sub\\report.json", 10) == b"{}"
        for name in ("../tree/calc.py", "..\\tree\\calc.py", str(box.tree / "calc.py"),
                     "C:calc.py", "sub/../../tree/calc.py", "", "out.txt:stream", "/etc"):
            with pytest.raises(AppError) as error:
                box.read_output(name, 1000)
            assert error.value.code == "CHECK_OUTPUT_REFUSED", name
        with pytest.raises(AppError) as error:
            box.read_output("big.bin", 100)
        assert error.value.code == "CHECK_OUTPUT_TOO_LARGE"
        with pytest.raises(AppError) as error:
            box.read_output("missing.txt", 100)
        assert error.value.code == "CHECK_OUTPUT_NOT_FOUND"
        if IS_WINDOWS:
            import _winapi

            outside.mkdir()
            (outside / "secret.txt").write_bytes(b"secret")
            _winapi.CreateJunction(str(outside), str(box.scratch / "link"))
            with pytest.raises(AppError) as error:
                box.read_output("link/secret.txt", 100)
            assert error.value.code == "CHECK_OUTPUT_REFUSED"
    # The junction was unlinked, never descended, by close().
    if IS_WINDOWS:
        assert (outside / "secret.txt").read_bytes() == b"secret"


def test_exit_always_closes_even_when_the_body_raises(boxes, windows, repo, runtime) -> None:
    with pytest.raises(RuntimeError):
        with boxes.open(uuid4(), repo, runtime) as box:
            raise RuntimeError("check body failed")
    assert boxes.repository.get(box.id).state is CheckRunState.CLEANED
    assert windows.profiles == set()
    with pytest.raises(AppError) as error:
        box.run([sys.executable, "-c", "pass"], timeout=10, limit=10)
    assert error.value.code == "CHECK_RUN_STATE_CONFLICT"
    box.close()  # idempotent


def test_open_boxes_are_skipped_by_the_sweep(boxes, repo, runtime) -> None:
    with boxes.open(uuid4(), repo, runtime) as box:
        assert boxes.sweep().cleaned == ()
        assert box.tree.is_dir()
