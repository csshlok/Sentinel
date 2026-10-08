"""Plan 02-01 (SC1): each capability is needed and is the only thing that grants its access.

``internetClient`` is the only capability Sentinel requests (claude's model API
traffic). A real workspace box reaches a public HTTPS host with it and cannot
without it; the host is the positive control. The per-run workspace drive adds
no access: another box cannot read through it.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus
from backend.app.execution.dos_drive import map_drive, unmap_drive
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.workspace.conftest import DUMMY_CREDENTIAL_KIND, FAKE_NODE_ADAPTER

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

HOST = "example.com"
INTERNET_PROBE = (
    "const https = require('https');"
    "const done = (r) => { console.log('PROBE ' + JSON.stringify(r)); };"
    f"const req = https.get('https://{HOST}/', {{timeout: 8000}}, (res) => {{"
    "  done({ok: true, status: res.statusCode}); res.resume(); });"
    "req.on('timeout', () => { req.destroy(); done({ok: false, error: 'timeout'}); });"
    "req.on('error', (e) => done({ok: false, error: e.code || String(e)}));"
)


def _host_can_reach(host: str) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=8):
            return True
    except OSError:
        return False


def _launcher(workspace_manager, tmp_path: Path, capabilities: tuple[str, ...]):
    from backend.app.credentials.broker import CredentialBroker
    from backend.app.credentials.memory_store import InMemoryCredentialStore
    from backend.app.execution.agent_profiles import BoundaryKind, RuntimeProfile
    from backend.app.execution.launcher import AgentAdapter, AgentLauncher

    return AgentLauncher(
        adapters={FAKE_NODE_ADAPTER: AgentAdapter(FAKE_NODE_ADAPTER, frozenset({"node"}))},
        profiles={FAKE_NODE_ADAPTER: RuntimeProfile(
            FAKE_NODE_ADAPTER, BoundaryKind.APPCONTAINER, capabilities=capabilities)},
        workspaces=workspace_manager,
        credentials=CredentialBroker(InMemoryCredentialStore(),
                                     agent_credential_sources={DUMMY_CREDENTIAL_KIND: tmp_path}),
    )


def _probe(launcher, repo: Path, script: str) -> dict:
    run = launcher.launch(uuid4(), str(repo), AgentLaunchRequest(
        adapter=FAKE_NODE_ADAPTER, executable="node", args=["-e", script],
        timeout_seconds=60), 65_536)
    assert run.status is AgentRunStatus.PASSED, (run.stdout, run.stderr, run.limitations)
    lines = [line for line in run.stdout.splitlines() if line.startswith("PROBE ")]
    assert len(lines) == 1, run.stdout
    return json.loads(lines[0][len("PROBE "):])


def test_internet_client_is_needed_and_sufficient(
    workspace_manager, user_repo: Path, tmp_path: Path, node_exe: str,
) -> None:
    if not _host_can_reach(HOST):
        pytest.skip(f"positive control failed: this host cannot reach {HOST}:443")
    with_capability = _probe(_launcher(workspace_manager, tmp_path, ("internetClient",)),
                             user_repo, INTERNET_PROBE)
    assert with_capability["ok"] is True, with_capability
    without = _probe(_launcher(workspace_manager, tmp_path, ()), user_repo, INTERNET_PROBE)
    assert without["ok"] is False, without


def test_the_workspace_drive_grants_another_box_nothing(
    workspace_manager, user_repo: Path, tmp_path: Path, node_exe: str,
) -> None:
    owner = workspace_manager.create(uuid4(), user_repo)
    (Path(owner.workspace_path) / "drive-probe.txt").write_text("owner only", encoding="utf-8")
    letter = map_drive(owner.container_path)
    try:
        target = f"{letter}\\\\ws\\\\drive-probe.txt"
        read = ("const fs = require('fs'); let r;"
                f"try {{ r = {{ok: true, text: fs.readFileSync('{target}', 'utf8')}}; }}"
                "catch (e) { r = {ok: false, error: e.code}; }"
                "console.log('PROBE ' + JSON.stringify(r));")
        # Another Change's box (its own profile and package SID) is denied.
        other = _probe(_launcher(workspace_manager, tmp_path, ()), user_repo, read)
        assert other["ok"] is False and other["error"] in {"EACCES", "EPERM"}, other
        # Positive control: the host process reads it through the same drive.
        assert Path(f"{letter}\\ws\\drive-probe.txt").read_text(encoding="utf-8") == "owner only"
    finally:
        unmap_drive(letter, owner.container_path)
