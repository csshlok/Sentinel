from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus
from backend.app.execution.launcher import AgentLauncher
from backend.app.execution.process_supervisor import IS_WINDOWS, is_process_running


pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="Windows Job Objects are Windows-only")


def _tree_code(child_seconds: int = 30, parent_seconds: int = 30) -> str:
    child = f"import time; time.sleep({child_seconds})"
    return (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"time.sleep({parent_seconds})"
    )


def test_real_grandchild_is_attributed_and_job_stop_removes_tree(tmp_path) -> None:
    launcher = AgentLauncher()
    change_id = uuid4()
    result: dict[str, object] = {}

    def run() -> None:
        result["run"] = launcher.launch(
            change_id,
            str(tmp_path),
            AgentLaunchRequest(
                adapter="generic", executable="python", args=["-c", _tree_code()],
                timeout_seconds=60,
            ),
            10_000,
        )

    thread = threading.Thread(target=run)
    thread.start()
    active = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with launcher._lock:
            states = list(launcher._runs.values())
            active = states[0].record if states else None
        if active and active.descendant_processes:
            break
        time.sleep(0.05)
    assert active is not None and active.descendant_control_available
    assert active.restricted_token_applied
    assert len(active.descendant_processes) == 1
    descendant_pid = active.descendant_processes[0].pid
    assert active.descendant_processes[0].attributed
    assert active.descendant_processes[0].executable_path
    assert active.descendant_processes[0].command_line
    assert is_process_running(descendant_pid)

    stopped = launcher.stop(active.id)
    thread.join(10)
    assert stopped.status is AgentRunStatus.CANCELLED
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and is_process_running(descendant_pid):
        time.sleep(0.05)
    assert not is_process_running(descendant_pid)
    final = result["run"]
    assert final.descendant_processes[0].terminated_at is not None


def test_restricted_token_still_allows_selected_repository_edits(tmp_path) -> None:
    run = AgentLauncher().launch(
        uuid4(),
        str(tmp_path),
        AgentLaunchRequest(
            adapter="generic", executable="python",
            args=["-c", "from pathlib import Path; Path('agent.txt').write_text('ok')"],
            timeout_seconds=10,
        ),
        10_000,
    )
    assert run.status is AgentRunStatus.PASSED
    assert run.restricted_token_applied
    assert (tmp_path / "agent.txt").read_text() == "ok"
    assert "not a sandbox" in (run.authority_reduction or "").lower()


def test_restricted_token_removes_non_traverse_privileges(tmp_path) -> None:
    code = (
        "import subprocess; "
        "r=subprocess.run(['whoami','/priv'],capture_output=True,text=True); "
        "print(r.stdout); raise SystemExit(r.returncode)"
    )
    run = AgentLauncher().launch(
        uuid4(), str(tmp_path),
        AgentLaunchRequest(
            adapter="generic", executable="python", args=["-c", code], timeout_seconds=10,
        ),
        30_000,
    )
    assert run.status is AgentRunStatus.PASSED
    # DISABLE_MAX_PRIVILEGE intentionally retains SeChangeNotifyPrivilege so
    # normal path traversal still works, but removes the other privileges the
    # caller token reports (for this account: shutdown/undock/time-zone/etc.).
    assert "SeChangeNotifyPrivilege" in run.stdout
    assert "SeShutdownPrivilege" not in run.stdout
    assert "SeTimeZonePrivilege" not in run.stdout
