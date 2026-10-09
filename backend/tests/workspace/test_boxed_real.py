"""The bring-your-own ``boxed`` adapter in a real workspace AppContainer (Phase 12).

A native executable the caller names (``node.exe`` here, a self-contained stand-in for an agent
CLI) is snapshotted into the box's tools folder and runs only inside a verified AppContainer.

Only the single executable is snapshotted, so an executable that needs files beside it can fail
in the box: ``hostname.exe`` copied out of System32 ran FAILED with no output (most likely it
cannot find ``en-US/hostname.exe.mui`` beside its copy; not investigated further). That limit is
stated in README and SECURITY.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.launcher import AgentLauncher
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.workspace.conftest import HOSTED_RUNNER_APPCONTAINER_GAP

pytestmark = [pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
              HOSTED_RUNNER_APPCONTAINER_GAP]


def test_boxed_runs_a_named_native_executable_from_its_snapshot_in_a_verified_box(
    workspace_manager, user_repo: Path, node_exe: str,
) -> None:
    launcher = AgentLauncher(workspaces=workspace_manager,
                             credentials=CredentialBroker(InMemoryCredentialStore()))
    change_id = uuid4()
    run = launcher.launch(change_id, str(user_repo), AgentLaunchRequest(
        adapter="boxed", executable="node", args=["-e", "console.log(6 * 7)"],
        timeout_seconds=60), 65_536)
    assert run.status is AgentRunStatus.PASSED, (run.stdout, run.stderr, run.limitations)
    assert run.stdout.strip() == "42"
    boundary = run.execution_boundary
    assert boundary is not None and boundary.kind == "APPCONTAINER"
    assert boundary.job_verified and boundary.integrity_rid == "0x1000"
    assert boundary.capabilities == ["internetClient"]
    record = workspace_manager.live_for_change(change_id)
    assert (Path(record.container_path) / "tools" / "node.exe").is_file()
    assert run.restricted_token_applied is False
    workspace_manager.discard(change_id)
