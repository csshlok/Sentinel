"""Junction-safe, retrying cleanup and discard (real Windows, real AppContainer profiles).

Settles research assumption A4: removal unlinks an agent-planted junction and
never descends into it, so files outside the workspace survive cleanup.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.core.errors import AppError
from backend.app.execution._process import capture
from backend.app.execution.appcontainer import (
    base_environment,
    local_appdata_known_folder,
    profile_exists,
    spawn_appcontainer_supervised,
)
from backend.app.execution.process_supervisor import IS_WINDOWS, is_process_running
from backend.app.workspace import manager as manager_module
from backend.tests.support_kb import write
from backend.tests.workspace.conftest import create_junction

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

CANARY = b"outside canary: cleanup must never delete this\n"


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside-canary"
    (outside / "nested").mkdir(parents=True)
    (outside / "canary.txt").write_bytes(CANARY)
    (outside / "nested" / "deep.txt").write_bytes(CANARY)
    return outside


def _assert_outside_intact(outside: Path) -> None:
    assert (outside / "canary.txt").read_bytes() == CANARY
    assert (outside / "nested" / "deep.txt").read_bytes() == CANARY


def _assert_gone(record) -> None:
    packages = local_appdata_known_folder() / "Packages" / record.profile_name
    assert not os.path.lexists(packages)
    assert profile_exists(record.profile_name) is False


def test_cleanup_unlinks_planted_junctions_without_following_them(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    outside = _outside(tmp_path)
    record = workspace_manager.create(uuid4(), user_repo)
    create_junction(outside, record.workspace_path / "top-link")
    (record.workspace_path / "sub" / "dir").mkdir(parents=True)
    create_junction(outside, record.workspace_path / "sub" / "dir" / "deep-link")
    create_junction(outside, record.workspace_path / ".git" / "objects" / "git-link")

    cleaned = workspace_manager.cleanup(record.id)

    assert cleaned.state == WorkspaceState.CLEANED
    _assert_outside_intact(outside)
    _assert_gone(record)


def test_cleanup_removes_only_the_link_when_home_is_a_junction(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    outside = _outside(tmp_path)
    record = workspace_manager.create(uuid4(), user_repo)
    home = record.container_path / "home"
    if home.exists():
        home.rmdir()
    create_junction(outside, home)

    cleaned = workspace_manager.cleanup(record.id)

    assert cleaned.state == WorkspaceState.CLEANED
    _assert_outside_intact(outside)
    _assert_gone(record)


def test_cleanup_removes_read_only_git_objects_and_the_profile(
    workspace_manager, user_repo: Path,
) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    objects = [path for path in (record.workspace_path / ".git" / "objects").rglob("*")
               if path.is_file()]
    assert objects
    # Git marks object files read-only on some setups (it did not for this clone on
    # Git for Windows 2.50), so make every one read-only to exercise that path.
    for path in objects:
        os.chmod(path, stat.S_IREAD)
    assert all(not os.stat(path).st_mode & stat.S_IWRITE for path in objects)

    cleaned = workspace_manager.cleanup(record.id)

    assert cleaned.state == WorkspaceState.CLEANED
    assert cleaned.cleaned_at is not None
    _assert_gone(record)


def test_cleanup_retries_transient_sharing_violations(
    workspace_manager, user_repo: Path, monkeypatch,
) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    real_remove = manager_module.remove_tree_no_follow
    failures = {"left": 2}
    attempts: list[str] = []

    def flaky(path):
        attempts.append(Path(path).name)
        if Path(path).name == "ws" and failures["left"]:
            failures["left"] -= 1
            error = PermissionError(13, "The process cannot access the file")
            error.winerror = 32
            raise error
        return real_remove(path)

    monkeypatch.setattr(manager_module, "remove_tree_no_follow", flaky)
    cleaned = workspace_manager.cleanup(record.id)

    assert cleaned.state == WorkspaceState.CLEANED
    assert attempts.count("ws") == 3
    _assert_gone(record)


def test_persistent_removal_failure_keeps_the_profile_and_records_cleanup_failed(
    workspace_manager, user_repo: Path, monkeypatch,
) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    real_remove = manager_module.remove_tree_no_follow
    deleted: list[str] = []
    real_delete = manager_module.delete_profile

    def stuck(path):
        if Path(path).name == "ws":
            raise PermissionError(13, "locked")
        return real_remove(path)

    monkeypatch.setattr(manager_module, "remove_tree_no_follow", stuck)
    monkeypatch.setattr(manager_module, "delete_profile",
                        lambda name: deleted.append(name) or real_delete(name))
    monkeypatch.setattr(manager_module, "_REMOVE_BACKOFF_SECONDS", 0.01)

    with pytest.raises(AppError) as raised:
        workspace_manager.cleanup(record.id)

    assert raised.value.code == "WORKSPACE_CLEANUP_FAILED"
    assert deleted == []  # the profile outlives a failed removal of its children
    failed = workspace_manager.get(record.id)
    assert failed.state == WorkspaceState.CLEANUP_FAILED
    assert profile_exists(record.profile_name) is True
    monkeypatch.undo()
    assert workspace_manager.cleanup(record.id).state == WorkspaceState.CLEANED
    _assert_gone(record)


# --------------------------------------------------------------------- discard


def _seal(manager, change_id, record) -> None:
    write(record.workspace_path, "agent.txt", "agent output\n")
    manager.preview(change_id)


def _refuse(manager, change_id, record, user_repo: Path) -> None:
    write(record.workspace_path, "agent.txt", "agent output\n")
    preview = manager.preview(change_id)
    write(user_repo, "user.txt", "moved\n")
    from backend.tests.support_kb import git

    git(user_repo, "add", "user.txt")
    git(user_repo, "commit", "-q", "-m", "user moved")
    assert manager.apply(change_id, preview.approval_token).state == WorkspaceState.APPLY_REFUSED


@pytest.mark.parametrize("prepare", [None, _seal, _refuse], ids=["ready", "sealed", "refused"])
def test_discard_cleans_an_unapplied_workspace(workspace_manager, user_repo: Path,
                                               prepare) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    if prepare is _refuse:
        prepare(workspace_manager, change_id, record, user_repo)
    elif prepare is not None:
        prepare(workspace_manager, change_id, record)
    states: list[str] = []
    real_update = workspace_manager.repository.update

    def spy(updated, *, expected_state, **kwargs):
        states.append(updated.state.value)
        return real_update(updated, expected_state=expected_state, **kwargs)

    workspace_manager.repository.update = spy
    discarded = workspace_manager.discard(change_id)

    assert states == ["DISCARDED", "CLEANED"]
    assert discarded.state == WorkspaceState.CLEANED
    assert discarded.approval_digest is None
    assert workspace_manager.live_for_change(change_id) is None
    assert workspace_manager.discard(change_id) == discarded  # idempotent
    assert not (user_repo / "agent.txt").exists()
    _assert_gone(record)


def test_discard_with_an_active_run_is_refused(workspace_manager, user_repo: Path) -> None:
    change_id, run_id = uuid4(), uuid4()
    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_id)

    with pytest.raises(AppError) as raised:
        workspace_manager.discard(change_id)

    assert raised.value.code == "WORKSPACE_STATE_CONFLICT"
    assert workspace_manager.get(record.id).state == WorkspaceState.READY
    workspace_manager.finish_run(record.id, run_id, facts=None, status="succeeded")


def test_killed_run_then_discard_leaves_no_profile(
    workspace_manager, user_repo: Path, node_exe: str,
) -> None:
    change_id, run_id = uuid4(), uuid4()
    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_id)
    spawned = []

    def factory(argv, cwd, env):
        process = spawn_appcontainer_supervised(
            argv, cwd=cwd, env=env, redact=lambda text: text,
            profile_name=record.profile_name, expected_package_sid=record.package_sid,
            capabilities=(),
        )
        spawned.append(process)
        return process

    cancel = threading.Event()
    timer = threading.Timer(1.5, cancel.set)
    timer.start()
    env = base_environment(record.container_path, path_entries=[Path(node_exe).parent])
    started = time.monotonic()
    try:
        result = capture(
            [node_exe, "-e", "require('fs').writeFileSync('partial.txt', 'x');"
                             " setInterval(() => {}, 1000);"],
            cwd=record.workspace_path, env=env, timeout=60, limit=65_536,
            cancel=cancel, process_factory=factory,
        )
    finally:
        timer.cancel()

    assert result.cancelled is True
    assert time.monotonic() - started < 30
    deadline = time.monotonic() + 10
    while is_process_running(spawned[0].pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not is_process_running(spawned[0].pid)
    workspace_manager.finish_run(record.id, run_id, facts=spawned[0].appcontainer.to_payload(),
                                 status="cancelled")

    discarded = workspace_manager.discard(change_id)

    assert discarded.state == WorkspaceState.CLEANED
    assert discarded.runs[-1]["status"] == "cancelled"
    _assert_gone(record)
