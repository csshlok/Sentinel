"""Opt-in: real Claude Code end to end through AgentLauncher in the workspace AppContainer.

Skipped unless ``RUN_SENTINEL_LIVE_AGENT_TEST=1``: it uses the network, the
user's real Claude login (copied by the credential broker into the staged home
for each run and deleted afterwards, as approved in spike 004) and a small
amount of API usage. Also skipped when ``~/.claude/.credentials.json`` or a
``claude`` executable is missing.

Step 1 (create and edit): ``--allowedTools "Read Edit Write"``, as validated in
spike 004. Step 2 (rename and delete): a second run allowed only the
``PowerShell`` tool.

History: on 2026-09-28 (Claude Code 2.1.284) step 2 used ``Bash(git mv:*)`` and
``Bash(git rm:*)`` and FAILED, because Git Bash (MSYS2) cannot initialise inside
the AppContainer (0xC0000142). Spike 007 (2026-10-08) showed the PowerShell
tool works when the workspace is run from a per-run drive (``<letter>:/ws``),
which the claude profile now does (quick 261008-9pq).
Then preview and apply land the changes in the user repository. The real
``~/.claude/.credentials.json`` is only read by the broker; its SHA-256 must
be unchanged afterwards and no staged copy may remain.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus, WorkspaceState
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.agent_profiles import BoundaryKind
from backend.app.execution.dos_drive import query_drive
from backend.app.execution.launcher import AgentLauncher
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.manager import WorkspaceManager
from backend.tests.support_kb import git
from backend.tests.workspace.conftest import repo_fingerprint

REAL_CREDENTIAL = Path.home() / ".claude" / ".credentials.json"

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("RUN_SENTINEL_LIVE_AGENT_TEST") != "1",
        reason=("Opt-in live test: set RUN_SENTINEL_LIVE_AGENT_TEST=1. It needs the network, "
                "uses the real Claude login (~/.claude/.credentials.json, staged and deleted) "
                "and costs a small amount of API usage."),
    ),
    pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
    pytest.mark.skipif(not REAL_CREDENTIAL.is_file(), reason="no ~/.claude/.credentials.json"),
    pytest.mark.skipif(shutil.which("claude") is None, reason="no claude executable on PATH"),
]

EDIT_PROMPT = ("Edit calc.py: add a function sub(a, b) that returns a - b. Then create notes.txt "
               "containing exactly: edited-in-appcontainer. Do nothing else.")
RENAME_PROMPT = ("Use the PowerShell tool to run exactly these two commands, one at a time, in "
                 "the current directory: `Rename-Item rename_me.txt renamed.txt` and then "
                 "`Remove-Item delete_me.txt`. Do nothing else.")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _claude(launcher: AgentLauncher, change_id, repo: Path, prompt: str, tools: str):
    return launcher.launch(change_id, str(repo), AgentLaunchRequest(
        adapter="claude", executable="claude",
        args=["-p", prompt, "--permission-mode", "acceptEdits", "--allowedTools", tools],
        timeout_seconds=300), 262_144)


def _evidence(run, record) -> dict:
    facts = record.runs[-1]["facts"] if record.runs else None
    return {
        "run_id": str(run.id), "status": run.status.value, "exit_code": run.exit_code,
        "duration_ms": run.duration_ms, "restricted_token_applied": run.restricted_token_applied,
        "authority_reduction": run.authority_reduction,
        "descendants": [(item.pid, item.executable_path) for item in run.descendant_processes],
        "stdout_tail": run.stdout[-1500:], "stderr_tail": run.stderr[-1500:],
        "limitations": run.limitations, "facts": facts,
    }


def test_real_claude_code_edits_renames_and_deletes_inside_the_workspace(
    workspace_manager: WorkspaceManager, user_repo: Path, record_property,
) -> None:
    host_sha_before = _sha256(REAL_CREDENTIAL)
    version = subprocess.run([shutil.which("claude"), "--version"], capture_output=True,
                             text=True, timeout=60).stdout.strip()
    record_property("claude_version", version)
    broker = CredentialBroker(InMemoryCredentialStore())  # default source: ~/.claude, broker-read
    launcher = AgentLauncher(workspaces=workspace_manager, credentials=broker)
    assert launcher.runtime_profile("claude").boundary is BoundaryKind.APPCONTAINER
    change_id = uuid4()
    before = repo_fingerprint(user_repo)
    evidence: dict = {"claude_version": version}
    staged = None
    try:
        # Step 1: create and edit.
        first = _claude(launcher, change_id, user_repo, EDIT_PROMPT, "Read Edit Write")
        record = workspace_manager.live_for_change(change_id)
        staged = Path(record.container_path) / "home" / ".claude" / ".credentials.json"
        evidence["step1"] = _evidence(first, record)
        evidence["step1"]["staged_credential_exists_after"] = os.path.lexists(staged)
        workspace = Path(record.workspace_path)
        evidence["step1"]["workspace_status"] = git(workspace, "status", "--porcelain")
        record_property("step1", json.dumps(evidence["step1"]))
        assert first.status is AgentRunStatus.PASSED, evidence["step1"]
        assert first.restricted_token_applied is False
        assert first.authority_reduction and "AppContainer" in first.authority_reduction
        assert "def sub(a, b)" in _lf(workspace / "calc.py")
        assert _lf(workspace / "notes.txt").strip() == "edited-in-appcontainer"
        assert not os.path.lexists(staged)
        assert repo_fingerprint(user_repo) == before
        facts = record.runs[-1]["facts"]
        assert facts["is_appcontainer"] is True and facts["package_sid"] == record.package_sid
        assert facts["integrity_rid"] == "0x1000"
        assert facts["capability_sids"] == ["S-1-15-3-1"]
        assert facts["job_verified"] is True

        # Step 2: rename and delete through the PowerShell tool (quick 261008-9pq; Git
        # Bash cannot initialise in the box, spike 007).
        second = _claude(launcher, change_id, user_repo, RENAME_PROMPT, "PowerShell")
        record = workspace_manager.live_for_change(change_id)
        evidence["step2"] = _evidence(second, record)
        evidence["step2"]["staged_credential_exists_after"] = os.path.lexists(staged)
        evidence["step2"]["workspace_status"] = git(workspace, "status", "--porcelain")
        record_property("step2", json.dumps(evidence["step2"]))
        assert not os.path.lexists(staged)
        assert second.status is AgentRunStatus.PASSED, evidence["step2"]
        assert (workspace / "renamed.txt").is_file(), evidence["step2"]
        assert not (workspace / "rename_me.txt").exists(), evidence["step2"]
        assert not (workspace / "delete_me.txt").exists(), evidence["step2"]
        assert repo_fingerprint(user_repo) == before
        # The run's workspace drive is disclosed and gone once the run has ended.
        drive_notes = [text for text in second.limitations if "exposed to the agent as drive" in text]
        assert len(drive_notes) == 1, second.limitations
        letter = drive_notes[0].split("as drive ", 1)[1][:2]
        assert query_drive(letter) == [], letter

        # Apply-back lands the agent's work in the user repository.
        preview = workspace_manager.preview(change_id)
        evidence["preview"] = {
            "refusal_reason": preview.refusal_reason,
            "changed_paths": [(status, path, list(flags))
                              for status, path, _old, _new, flags in preview.changed_paths],
            "limitations": list(preview.limitations),
        }
        assert preview.approval_token, evidence["preview"]
        applied = workspace_manager.apply(change_id, preview.approval_token)
        assert applied.state == WorkspaceState.CLEANED
        assert git(user_repo, "rev-parse", "HEAD").strip() == preview.sealed_sha
        assert "def sub(a, b)" in _lf(user_repo / "calc.py")
        assert _lf(user_repo / "notes.txt").strip() == "edited-in-appcontainer"
        assert _lf(user_repo / "renamed.txt") == "rename me\n"
        assert not (user_repo / "rename_me.txt").exists()
        assert not (user_repo / "delete_me.txt").exists()
        assert not (user_repo / ".claude").exists()
    finally:
        host_sha_after = _sha256(REAL_CREDENTIAL)
        evidence["host_credential_sha256_unchanged"] = host_sha_after == host_sha_before
        evidence["staged_credential_remaining"] = bool(staged and os.path.lexists(staged))
        print("LIVE-EVIDENCE " + json.dumps(evidence, default=str))
        live = workspace_manager.live_for_change(change_id)
        if live is not None and live.active_run_id is None:
            try:
                workspace_manager.discard(change_id)
            except Exception:
                pass
    assert host_sha_after == host_sha_before
    assert not (staged and os.path.lexists(staged))
