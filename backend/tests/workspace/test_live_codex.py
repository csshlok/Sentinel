"""Opt-in: real Codex CLI end to end through AgentLauncher in the workspace AppContainer (spike 008).

Skipped unless ``RUN_SENTINEL_LIVE_AGENT_TEST=1``: it uses the network, the
user's real Codex login (``~/.codex/auth.json``, copied by the credential broker
into the staged home for the run and deleted afterwards) and a small amount of
model usage. Also skipped when the login or a resolvable native ``codex.exe``
is missing.

The run uses ``--sandbox danger-full-access``: Codex's own sandbox is off and
Sentinel's AppContainer is the boundary. Codex's own sandbox modes inside the
box are UNKNOWN (spike 008). Then preview and apply land the edit in the user
repository; the real ``auth.json`` must be unchanged and no staged copy remain.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.launcher import AgentLauncher
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.execution.resolve import resolve_argv
from backend.app.workspace.manager import WorkspaceManager

REAL_CREDENTIAL = Path.home() / ".codex" / "auth.json"


def _native_codex() -> bool:
    try:
        argv = resolve_argv("codex", dict(os.environ), Path.cwd().resolve())
    except Exception:
        return False
    return len(argv) == 1 and argv[0].lower().endswith("codex.exe")


pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_SENTINEL_LIVE_AGENT_TEST") != "1",
        reason=("Opt-in live test: set RUN_SENTINEL_LIVE_AGENT_TEST=1. It needs the network, "
                "uses the real Codex login (~/.codex/auth.json, staged and deleted) and costs a "
                "small amount of model usage."),
    ),
    pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
    pytest.mark.skipif(not REAL_CREDENTIAL.is_file(), reason="no ~/.codex/auth.json"),
    pytest.mark.skipif(not _native_codex(), reason="no npm codex install with a vendored codex.exe"),
]

PROMPT = "Create a file named boxed.txt containing exactly the word: boxed. Do nothing else."


def test_codex_edits_the_workspace_in_the_box_and_the_edit_applies(
    workspace_manager: WorkspaceManager, user_repo: Path,
) -> None:
    before = hashlib.sha256(REAL_CREDENTIAL.read_bytes()).hexdigest()
    launcher = AgentLauncher(workspaces=workspace_manager,
                             credentials=CredentialBroker(InMemoryCredentialStore()))
    change_id = uuid4()
    run = launcher.launch(change_id, str(user_repo), AgentLaunchRequest(
        adapter="codex", executable="codex",
        args=["exec", "--skip-git-repo-check", "--sandbox", "danger-full-access",
              "--color", "never", PROMPT],
        timeout_seconds=300), 262_144)
    assert run.status is AgentRunStatus.PASSED, (run.stdout[-2000:], run.stderr[-2000:])
    boundary = run.execution_boundary
    assert boundary is not None and boundary.kind == "APPCONTAINER" and boundary.job_verified
    assert boundary.integrity_rid == "0x1000"
    record = workspace_manager.live_for_change(change_id)
    workspace_file = Path(record.workspace_path) / "boxed.txt"
    assert workspace_file.read_text(encoding="utf-8").strip() == "boxed"
    assert not (user_repo / "boxed.txt").exists()  # nothing reached the user repo yet

    preview = workspace_manager.preview(change_id)
    assert preview.fast_forward_possible and preview.approval_token
    workspace_manager.apply(change_id, preview.approval_token)
    assert (user_repo / "boxed.txt").read_text(encoding="utf-8").strip() == "boxed"

    # The real login was only read, and no staged copy remains.
    assert hashlib.sha256(REAL_CREDENTIAL.read_bytes()).hexdigest() == before
    staged = Path(record.container_path) / "home" / ".codex" / "auth.json"
    assert not staged.exists()
