"""Research A6 / threat T-01-41: pause, resume and stop still act on an AppContainer run's tree.

Real Windows AppContainer through ``AgentLauncher`` (``fake_node_launcher``).
The agent increments a counter file in the workspace every 100 ms and starts
one long-sleeping child. The child is ``powershell.exe Start-Sleep``, not a
second node: measured on this machine, the AppContainer cannot spawn node
(``C:\\Program Files\\nodejs`` grants ALL APPLICATION PACKAGES nothing, so the
container cannot open its own interpreter's image -- ``spawn`` fails ENOENT),
and a child with piped stdio never returns inside the container. System32
binaries are readable by every AppContainer, so the child is taken from there
and started with ``stdio: 'ignore'``.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.contracts.models import AgentRun, AgentRunStatus, WorkspaceState
from backend.app.execution.process_supervisor import IS_WINDOWS, is_process_running
from backend.app.workspace.manager import WorkspaceManager
from backend.tests.workspace.conftest import HOSTED_RUNNER_APPCONTAINER_GAP, FakeNodeLauncher

pytestmark = [
    pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
    HOSTED_RUNNER_APPCONTAINER_GAP,
]

POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                          "WindowsPowerShell", "v1.0", "powershell.exe")

AGENT = r"""
const fs = require('fs');
const { spawn } = require('child_process');
const child = spawn(process.argv[process.argv.length - 1],
  ['-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 120'],
  { stdio: 'ignore', windowsHide: true });
child.on('error', (e) => { fs.writeFileSync('child.error', String(e.code)); });
if (child.pid) fs.writeFileSync('child.pid', String(child.pid));
let count = 0;
setInterval(() => { count += 1; fs.writeFileSync('counter.txt', String(count)); }, 100);
"""


def _wait(predicate, timeout: float, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def _counter(workspace: Path) -> int:
    try:
        return int((workspace / "counter.txt").read_text(encoding="utf-8") or 0)
    except (OSError, ValueError):
        return -1


def test_pause_resume_stop_and_descendants_on_an_appcontainer_run(
    workspace_manager: WorkspaceManager, user_repo: Path,
    fake_node_launcher: FakeNodeLauncher, record_property,
) -> None:
    from backend.app.contracts.models import AgentLaunchRequest

    from backend.tests.workspace.conftest import FAKE_NODE_ADAPTER

    launcher = fake_node_launcher.launcher
    change_id = uuid4()
    run_ids: list[UUID] = []
    launcher.on_update = lambda run: run_ids.append(run.id) if run.id not in run_ids else None
    finished: list[AgentRun] = []
    request = AgentLaunchRequest(adapter=FAKE_NODE_ADAPTER, executable="node",
                                 args=["-e", AGENT, POWERSHELL], timeout_seconds=120)
    thread = threading.Thread(
        target=lambda: finished.append(launcher.launch(change_id, str(user_repo), request, 65_536)),
        daemon=True)
    thread.start()
    child_pid: int | None = None
    top_pid: int | None = None
    try:
        run_id = _wait(lambda: run_ids[0] if run_ids else None, 60)
        assert run_id is not None, "the launch never reported a run"
        running = _wait(lambda: (lambda run: run if run.status is AgentRunStatus.RUNNING
                                 and run.top_level_pid else None)(launcher.get(run_id)), 60)
        assert running, launcher.get(run_id)
        top_pid = running.top_level_pid
        record = workspace_manager.live_for_change(change_id)
        workspace = Path(record.workspace_path)
        assert _wait(lambda: _counter(workspace) > 2, 30), "the agent never counted"
        pid_text = _wait(lambda: (workspace / "child.pid").exists()
                         and (workspace / "child.pid").read_text(encoding="utf-8"), 30)
        assert pid_text, (workspace / "child.error").read_text(encoding="utf-8") \
            if (workspace / "child.error").exists() else "no child pid"
        child_pid = int(pid_text)

        # Descendants of the boxed agent are observed with executable paths.
        def child_observed():
            for item in launcher.get(run_id).descendant_processes:
                if item.pid == child_pid:
                    return item
            return None

        descendant = _wait(child_observed, 30)
        assert descendant is not None, launcher.get(run_id).descendant_processes
        assert descendant.executable_path is not None
        assert descendant.executable_path.lower().endswith("powershell.exe")
        record_property("descendant_command_line_present", descendant.command_line is not None)
        record_property("descendant_executable_path", descendant.executable_path)

        # Pause freezes the whole tree: the counter stops.
        paused = launcher.pause(run_id)
        assert paused.status is AgentRunStatus.PAUSED
        time.sleep(0.3)  # a write already in flight may still land
        frozen = _counter(workspace)
        time.sleep(1.0)
        assert _counter(workspace) == frozen
        assert is_process_running(top_pid) and is_process_running(child_pid)

        # Resume lets it count again.
        resumed = launcher.resume(run_id)
        assert resumed.status is AgentRunStatus.RUNNING
        assert _wait(lambda: _counter(workspace) > frozen, 5), "resume did not restart the agent"

        # Stop ends the whole tree: the agent and its child.
        stopped = launcher.stop(run_id)
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert stopped.status is AgentRunStatus.CANCELLED, stopped
        assert finished and finished[0].status is AgentRunStatus.CANCELLED
        assert _wait(lambda: not is_process_running(top_pid), 10)
        assert _wait(lambda: not is_process_running(child_pid), 10)
        record = workspace_manager.live_for_change(change_id)
        assert record.active_run_id is None
        assert record.runs[-1]["run_id"] == str(run_id)
        assert record.runs[-1]["status"] == AgentRunStatus.CANCELLED.value
        assert record.runs[-1]["facts"]["is_appcontainer"] is True
        # The staged credential is gone after a cancelled run too.
        assert not os.path.lexists(
            Path(record.container_path) / "home" / ".claude" / ".credentials.json")

        discarded = workspace_manager.discard(change_id)
        assert discarded.state == WorkspaceState.CLEANED
    finally:
        if thread.is_alive():
            for run_id in run_ids:
                try:
                    launcher.stop(run_id)
                except Exception:
                    pass
            thread.join(timeout=30)
        launcher.on_update = None
