"""SBOX-01/02 through the product path: AgentLauncher -> workspace AppContainer -> apply-back.

Real Windows AppContainer, real WorkspaceManager, real CredentialBroker with a
dummy credential file (never the user's ~/.claude). The only stand-in is the
agent itself: node under a custom AppContainer runtime profile.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus, WorkspaceState
from backend.app.core.config import Settings
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.agent_ports import CredentialFingerprint, WorkspaceProvider
from backend.app.execution.agent_profiles import BoundaryKind, RuntimeProfile
from backend.app.execution.appcontainer import local_appdata_known_folder, profile_exists
from backend.app.execution.launcher import (
    RESTRICTED_AUTHORITY,
    AgentAdapter,
    AgentLauncher,
)
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.main import create_app
from backend.app.workspace.manager import WorkspaceManager
from backend.tests.support_kb import git
from backend.tests.workspace.conftest import repo_fingerprint

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

ACCESS = "sk-ant-oat01-DUMMYlaunchREALtoken-0123456789abcdef"
KIND = "claude-oauth-file"

AGENT_SCRIPT = "\n".join([
    "const fs = require('fs');",
    "const path = require('path');",
    "const staged = path.join(process.env.USERPROFILE, '.claude', '.credentials.json');",
    "const present = fs.existsSync(staged);",
    "let token = 'none';",
    "if (present) { token = JSON.parse(fs.readFileSync(staged, 'utf8')).claudeAiOauth.accessToken; }",
    f"fs.writeFileSync('created.txt', {json.dumps('created through the launcher' + chr(10))});",
    f"fs.appendFileSync('calc.py', {json.dumps(chr(10) + 'def sub(a, b):' + chr(10) + '    return a - b' + chr(10))});",
    "fs.renameSync('rename_me.txt', 'renamed.txt');",
    "fs.unlinkSync('delete_me.txt');",
    "process.stdout.write('credential-present=' + present + ' token=' + token + ' done');",
])


def _lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.fixture
def dummy_credential(tmp_path: Path) -> Path:
    path = tmp_path / "dummy-home" / ".claude" / ".credentials.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": ACCESS, "refreshToken": "sk-ant-ort01-DUMMYrefreshREAL-9876543210",
        "expiresAt": 1893456000000, "scopes": ["user:inference"],
    }}), encoding="utf-8")
    return path


def test_node_agent_runs_in_the_workspace_appcontainer_through_the_launcher(
    workspace_manager: WorkspaceManager, user_repo: Path, node_exe: str,
    dummy_credential: Path,
) -> None:
    broker = CredentialBroker(InMemoryCredentialStore(),
                              agent_credential_sources={KIND: dummy_credential})
    launcher = AgentLauncher(
        adapters={"fake-node": AgentAdapter("fake-node", frozenset({"node"}))},
        profiles={"fake-node": RuntimeProfile(
            "fake-node", BoundaryKind.APPCONTAINER, capabilities=("internetClient",),
            staged_home=True, credential_kind=KIND, tool_snapshot=False,
        )},
        workspaces=workspace_manager, credentials=broker,
    )
    change_id = uuid4()
    before = repo_fingerprint(user_repo)
    source_bytes = dummy_credential.read_bytes()

    run = launcher.launch(change_id, str(user_repo), AgentLaunchRequest(
        adapter="fake-node", executable="node", args=["-e", AGENT_SCRIPT],
        timeout_seconds=60), 65_536)

    record = workspace_manager.live_for_change(change_id)
    assert record is not None
    assert run.status is AgentRunStatus.PASSED, (run.stderr, run.limitations)
    assert run.restricted_token_applied is False
    assert run.descendant_control_available is True
    assert run.authority_reduction is not None
    assert "AppContainer" in run.authority_reduction
    assert record.package_sid in run.authority_reduction
    assert run.authority_reduction != RESTRICTED_AUTHORITY
    assert RESTRICTED_AUTHORITY not in run.limitations
    assert all("restricted Windows token" not in text for text in run.limitations)
    # The agent saw the staged credential during the run, and its output is redacted.
    assert "credential-present=true" in run.stdout
    assert ACCESS not in run.stdout and ACCESS not in run.stderr
    assert "token=[REDACTED] done" in run.stdout
    # After the run: the staged credential is gone, the source is untouched.
    staged = record.container_path / "home" / ".claude" / ".credentials.json"
    assert not os.path.lexists(staged)
    assert dummy_credential.read_bytes() == source_bytes
    # The workspace record holds the verified boundary facts and the fingerprint only.
    assert record.active_run_id is None
    last = record.runs[-1]
    assert last["run_id"] == str(run.id) and last["status"] == "PASSED"
    facts = last["facts"]
    assert facts["is_appcontainer"] is True
    assert facts["integrity_rid"] == "0x1000"
    assert facts["capability_sids"] == ["S-1-15-3-1"]
    assert facts["job_verified"] is True
    assert facts["package_sid"] == record.package_sid
    assert isinstance(workspace_manager, WorkspaceProvider)
    expected = CredentialFingerprint.from_bytes(KIND, source_bytes).to_payload()
    assert list(record.credential_fingerprints) == [expected]
    workspace_manager.record_credential(record.id, CredentialFingerprint.from_payload(expected))
    assert len(workspace_manager.get(record.id).credential_fingerprints) == 1  # stored once
    assert ACCESS not in record.to_json()
    # The user's repository was not touched by the run.
    assert repo_fingerprint(user_repo) == before

    preview = workspace_manager.preview(change_id)
    assert {(status, path) for status, path, *_ in preview.changed_paths} == {
        ("A", "created.txt"), ("M", "calc.py"), ("D", "delete_me.txt"),
        ("D", "rename_me.txt"), ("A", "renamed.txt"),
    }
    assert preview.approval_token
    applied = workspace_manager.apply(change_id, preview.approval_token)
    assert applied.state == WorkspaceState.CLEANED
    assert git(user_repo, "rev-parse", "HEAD").strip() == preview.sealed_sha
    assert _lf(user_repo / "created.txt") == "created through the launcher\n"
    assert _lf(user_repo / "calc.py") == (
        "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    assert _lf(user_repo / "renamed.txt") == "rename me\n"
    assert not (user_repo / "rename_me.txt").exists()
    assert not (user_repo / "delete_me.txt").exists()
    assert not (user_repo / ".claude").exists()
    packages = local_appdata_known_folder() / "Packages" / record.profile_name
    assert not os.path.lexists(packages)
    assert profile_exists(record.profile_name) is False


def test_failed_spawn_still_deletes_the_staged_credential(
    workspace_manager: WorkspaceManager, user_repo: Path, node_exe: str,
    dummy_credential: Path, monkeypatch,
) -> None:
    from backend.app.execution import launcher as module
    from backend.app.execution.appcontainer import verification_failed

    def refuse(*args, **kwargs):
        raise verification_failed("capabilities")

    monkeypatch.setattr(module, "spawn_appcontainer_supervised", refuse)
    monkeypatch.setattr(module, "spawn_restricted_supervised",
                        lambda *a, **k: pytest.fail("restricted fallback"))
    broker = CredentialBroker(InMemoryCredentialStore(),
                              agent_credential_sources={KIND: dummy_credential})
    launcher = AgentLauncher(
        adapters={"fake-node": AgentAdapter("fake-node", frozenset({"node"}))},
        profiles={"fake-node": RuntimeProfile(
            "fake-node", BoundaryKind.APPCONTAINER, staged_home=True, credential_kind=KIND)},
        workspaces=workspace_manager, credentials=broker,
    )
    change_id = uuid4()
    run = launcher.launch(change_id, str(user_repo), AgentLaunchRequest(
        adapter="fake-node", executable="node", args=["-e", "0"], timeout_seconds=30), 4096)
    assert run.status is AgentRunStatus.ERROR
    assert any("APPCONTAINER_VERIFICATION_FAILED" in text for text in run.limitations)
    record = workspace_manager.live_for_change(change_id)
    assert not os.path.lexists(record.container_path / "home" / ".claude" / ".credentials.json")
    assert record.active_run_id is None
    assert record.runs[-1]["status"] == "ERROR" and record.runs[-1]["facts"] is None


def test_create_app_composes_the_appcontainer_launch_path(tmp_path: Path) -> None:
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app):
        launcher = app.state.agent_launcher
        manager = app.state.workspace_manager
        assert isinstance(manager, WorkspaceManager)
        assert launcher.workspace_provider is manager
        broker = launcher.credential_stager
        assert isinstance(broker, CredentialBroker)
        assert broker is app.state.credential_broker
        assert app.state.runtime_services.credentials.broker is broker
        assert app.state.runtime_services.evidence.evidence._launcher is launcher
        assert launcher.runtime_profile("claude").boundary is BoundaryKind.APPCONTAINER
        assert launcher.runtime_profile("codex").boundary is BoundaryKind.UNAVAILABLE
        assert launcher.runtime_profile("generic").boundary is BoundaryKind.RESTRICTED_TOKEN
