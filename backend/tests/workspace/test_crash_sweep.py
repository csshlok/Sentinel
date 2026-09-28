"""DB-driven sweep: a crashed backend, a crash mid-create and failed cleanups are recovered;
profiles not recorded in the sweep's own database are never touched (research Pitfall 14).

The crash test is real: a child Python process creates a workspace, begins a
run, stages a dummy credential file, launches a node agent inside the
AppContainer and is then killed with TerminateProcess. The kill-on-close Job
must end the agent, and the sweep must purge the staged home while keeping
the unapplied workspace.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.contracts.models import WorkspaceState, utc_now
from backend.app.core.errors import AppError
from backend.app.execution.appcontainer import (
    delete_profile,
    ensure_profile,
    local_appdata_known_folder,
    profile_exists,
    remove_tree_no_follow,
)
from backend.app.execution.process_supervisor import IS_WINDOWS, is_process_running
from backend.app.workspace import manager as manager_module
from backend.app.workspace.manager import WorkspaceManager
from backend.app.workspace.models import WorkspaceRecord
from backend.tests.workspace.conftest import TEST_PROFILE_PREFIX, teardown_workspaces

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

REPO_ROOT = Path(__file__).resolve().parents[3]

CHILD = textwrap.dedent("""
    import json, sys, time, uuid
    from pathlib import Path
    from backend.app.core.database import Database
    from backend.app.execution.appcontainer import base_environment, spawn_appcontainer_supervised
    from backend.app.workspace.manager import WorkspaceManager

    database_path, source, change_id, node = sys.argv[1:5]
    database = Database(Path(database_path))
    database.initialize()
    manager = WorkspaceManager(database, profile_prefix="sentinel.test.")
    record = manager.ensure(uuid.UUID(change_id), source, run_id=uuid.uuid4())
    staged = record.container_path / "home" / ".claude"
    staged.mkdir(parents=True, exist_ok=True)
    (staged / ".credentials.json").write_text('{"dummy": "not a real credential"}')
    env = base_environment(record.container_path, path_entries=[Path(node).parent])
    agent = spawn_appcontainer_supervised(
        [node, "-e", "require('fs').writeFileSync('before-crash.txt', 'unapplied work');"
                     " setInterval(() => {}, 1000);"],
        cwd=record.workspace_path, env=env, redact=lambda text: text,
        profile_name=record.profile_name, expected_package_sid=record.package_sid,
        capabilities=(),
    )
    print(json.dumps({"workspace_id": str(record.id), "agent_pid": agent.pid}), flush=True)
    time.sleep(600)
""")


def _wait(predicate, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _purger(calls: list[Path]):
    def purge(home: Path) -> bool:
        calls.append(home)
        credential = home / ".claude" / ".credentials.json"
        if credential.exists():
            credential.unlink()
        return True

    return purge


def test_crashed_backend_is_recovered_by_the_sweep(
    workspace_database, user_repo: Path, node_exe: str,
) -> None:
    change_id = uuid4()
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(workspace_database.path), str(user_repo),
         str(change_id), node_exe],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    purged: list[Path] = []
    manager = WorkspaceManager(workspace_database, profile_prefix=TEST_PROFILE_PREFIX,
                               credential_purger=_purger(purged))
    agent_pid = None
    try:
        line = child.stdout.readline()
        assert line, child.stderr.read().decode(errors="replace")
        started = json.loads(line)
        workspace_id, agent_pid = UUID(started["workspace_id"]), started["agent_pid"]
        record = manager.get(workspace_id)
        work = record.workspace_path / "before-crash.txt"
        credential = record.container_path / "home" / ".claude" / ".credentials.json"
        assert _wait(work.exists, 10), "the agent never wrote its work"
        assert credential.exists()
        assert record.active_run_id is not None
        assert is_process_running(agent_pid)

        os.kill(child.pid, signal.SIGTERM)  # TerminateProcess: no cleanup code runs
        child.wait(timeout=10)
        assert _wait(lambda: not is_process_running(agent_pid), 10), "Job kill-on-close failed"

        report = manager.sweep()

        assert report.preserved == (workspace_id,)
        assert report.cleaned == () and report.failed == ()
        swept = manager.get(workspace_id)
        assert swept.state == WorkspaceState.READY
        assert swept.active_run_id is None
        assert any("was interrupted before it finished" in item for item in swept.limitations)
        assert not credential.exists()
        assert not (record.container_path / "home").exists()
        assert purged == [record.container_path / "home"]
        assert work.read_bytes() == b"unapplied work"  # unapplied work is preserved

        discarded = manager.discard(change_id)
        assert discarded.state == WorkspaceState.CLEANED
        assert profile_exists(record.profile_name) is False
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        child.stdout.close()
        child.stderr.close()
        if agent_pid is not None:
            _wait(lambda: not is_process_running(agent_pid), 10)
        teardown_workspaces(manager)


def _insert(manager: WorkspaceManager, state: WorkspaceState, **fields) -> WorkspaceRecord:
    now = utc_now()
    record = WorkspaceRecord(
        id=uuid4(), change_id=uuid4(), state=state,
        profile_name=TEST_PROFILE_PREFIX + uuid4().hex, created_at=now, updated_at=now,
        **fields,
    )
    return manager.repository.insert(record)


def test_crash_while_creating_is_cleaned_by_the_sweep(workspace_manager) -> None:
    record = _insert(workspace_manager, WorkspaceState.CREATING)
    ensure_profile(record.profile_name, display_name="Sentinel workspace")  # never cloned
    assert profile_exists(record.profile_name)

    report = workspace_manager.sweep()

    assert report.cleaned == (record.id,)
    assert workspace_manager.get(record.id).state == WorkspaceState.CLEANED
    assert profile_exists(record.profile_name) is False
    assert not os.path.lexists(local_appdata_known_folder() / "Packages" / record.profile_name)


def test_failed_cleanup_is_retried_by_the_sweep(
    workspace_manager, user_repo: Path, monkeypatch,
) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    real_delete = manager_module.delete_profile
    calls = {"n": 0}

    def fail_first(name):
        calls["n"] += 1
        if calls["n"] == 1:
            from backend.app.execution.appcontainer import profile_failed

            raise profile_failed("delete", 0x80070020)
        return real_delete(name)

    monkeypatch.setattr(manager_module, "delete_profile", fail_first)
    with pytest.raises(AppError) as raised:
        workspace_manager.cleanup(record.id)
    assert raised.value.code == "WORKSPACE_CLEANUP_FAILED"
    assert workspace_manager.get(record.id).state == WorkspaceState.CLEANUP_FAILED

    report = workspace_manager.sweep()

    assert report.cleaned == (record.id,)
    assert workspace_manager.get(record.id).state == WorkspaceState.CLEANED
    assert profile_exists(record.profile_name) is False


def test_sweep_never_touches_a_profile_its_database_does_not_record(
    workspace_manager, user_repo: Path,
) -> None:
    foreign = TEST_PROFILE_PREFIX + uuid4().hex
    profile, _ = ensure_profile(foreign, display_name="Sentinel workspace")
    marker = profile.container_path / "ws"
    marker.mkdir(parents=True, exist_ok=True)
    (marker / "someone-elses-work.txt").write_bytes(b"not ours\n")
    recorded = _insert(workspace_manager, WorkspaceState.DISCARDED)
    try:
        report = workspace_manager.sweep()

        assert report.cleaned == (recorded.id,)
        assert profile_exists(foreign) is True
        assert (marker / "someone-elses-work.txt").read_bytes() == b"not ours\n"
    finally:
        remove_tree_no_follow(profile.container_path)
        delete_profile(foreign)
        remove_tree_no_follow(local_appdata_known_folder() / "Packages" / foreign)
    assert profile_exists(foreign) is False


def test_sweep_skips_rows_whose_run_is_live(workspace_manager, user_repo: Path) -> None:
    change_id, run_id = uuid4(), uuid4()
    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_id)
    staged = record.container_path / "home" / ".claude" / ".credentials.json"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(b"{}")

    explicit = workspace_manager.sweep(live_run_ids={run_id})
    implicit = workspace_manager.sweep()  # runs started by this manager are live by default

    for report in (explicit, implicit):
        assert report == type(report)()
    current = workspace_manager.get(record.id)
    assert current.active_run_id == str(run_id)
    assert staged.exists()
    assert not any("interrupted" in item for item in current.limitations)

    # Another process (a restarted backend) sees the same row as interrupted.
    restarted = WorkspaceManager(workspace_manager.repository.database,
                                 profile_prefix=TEST_PROFILE_PREFIX)
    report = restarted.sweep()
    assert report.preserved == (record.id,)
    assert workspace_manager.get(record.id).active_run_id is None
    assert not staged.exists()
