"""SC3 / threat T-01-40: what the workspace AppContainer agent cannot reach, with host controls.

Real Windows AppContainer through ``AgentLauncher`` (the ``fake_node_launcher``
profile mirrors ``claude``: internetClient plus a staged home). One node probe
reports an outcome per resource; every denial is paired with a positive
control showing the same resource is reachable from the host, so a "denied"
result cannot come from a broken probe.

Probed here: the user repository (write and read), a canary under the real
user profile, the real ``~/.claude`` (read-only listing, only when it exists),
a 127.0.0.1 listener, and a Credential Manager target. Resources NOT probed
here (the registry beyond spike 003, named pipes, other loopback services,
devices, other users' files, the internet itself, ...) remain UNKNOWN until the
Phase 3 adversarial suite.

Real user state is touched only through uniquely named canaries (a directory
under ``%USERPROFILE%`` and a ``sentinel-test-*`` generic credential), each
removed in a ``finally`` block; the real ``~/.claude`` is only listed, never
written.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentRunStatus
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.manager import WorkspaceManager
from backend.tests.support_kb import git, write
from backend.tests.workspace.conftest import FakeNodeLauncher, repo_fingerprint

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

CMDKEY = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmdkey.exe")
DENIED_CODES = {"EPERM", "EACCES"}

PROBE = r"""
const fs = require('fs');
const net = require('net');
const path = require('path');
const { spawnSync } = require('child_process');
const cfg = JSON.parse(process.argv[process.argv.length - 1]);
const out = {};
function attempt(name, fn) {
  try { const value = fn(); out[name] = { ok: true, value: value === undefined ? null : value }; }
  catch (e) { out[name] = { ok: false, code: e.code || null, message: String(e.message).slice(0, 200) }; }
}
attempt('repo_write', () => fs.writeFileSync(path.join(cfg.repo, 'pwned.txt'), 'pwned'));
attempt('repo_read', () => fs.readFileSync(path.join(cfg.repo, 'calc.py'), 'utf8').length);
attempt('canary_read', () => fs.readFileSync(cfg.canary_file, 'utf8'));
attempt('canary_list', () => fs.readdirSync(cfg.canary_dir).length);
if (cfg.claude_dir) attempt('claude_list', () => fs.readdirSync(cfg.claude_dir).length);
attempt('workspace_write', () => fs.writeFileSync('containment-probe.txt', 'written-inside'));
// The child's stdio is a workspace file, not a pipe: inside the AppContainer a
// piped spawn (execFileSync) never returns, not even at its own timeout (measured).
attempt('cmdkey', () => {
  const fd = fs.openSync('cmdkey-output.txt', 'w');
  let result;
  try {
    result = spawnSync(cfg.cmdkey, ['/list:' + cfg.target],
      { stdio: ['ignore', fd, fd], windowsHide: true, timeout: 20000 });
  } finally { fs.closeSync(fd); }
  if (result.error) throw result.error;
  return { status: result.status, output: fs.readFileSync('cmdkey-output.txt', 'utf8') };
});
const started = Date.now();
const socket = net.connect(cfg.port, '127.0.0.1');
let settled = false;
function finish(result) {
  if (settled) return;
  settled = true;
  out.loopback = Object.assign(result, { elapsed_ms: Date.now() - started });
  socket.destroy();
  fs.writeSync(1, 'PROBE ' + JSON.stringify(out) + '\n');
}
socket.setTimeout(3000, () => finish({ connected: false, reason: 'timeout' }));
socket.on('connect', () => finish({ connected: true }));
socket.on('error', (e) => finish({ connected: false, reason: e.code || 'error' }));
"""


# `node probe.js` would fail inside the container before running anything: the
# main-module realpath lstat()s C:\ (EPERM there, measured), so the committed
# probe is evaluated from -e instead.
RUN_PROBE = "eval(require('fs').readFileSync('probe.js', 'utf8'))"


class _Listener:
    """A host TCP listener on 127.0.0.1 that counts accepted connections."""

    def __init__(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.server.settimeout(0.2)
        self.port = self.server.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self.server.accept()
            except (TimeoutError, OSError):
                continue
            self.accepted += 1
            connection.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.server.close()


def _cmdkey(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([CMDKEY, *args], capture_output=True, text=True, timeout=30)


def _parse_probe(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.startswith("PROBE ")]
    assert len(lines) == 1, stdout
    return json.loads(lines[0][len("PROBE "):])


def test_the_appcontainer_agent_is_denied_host_resources_that_the_host_can_reach(
    workspace_manager: WorkspaceManager, user_repo: Path,
    fake_node_launcher: FakeNodeLauncher,
) -> None:
    profile_root = Path(os.environ["USERPROFILE"])
    canary_dir = profile_root / f"sentinel-test-canary-{uuid4().hex}"
    canary_file = canary_dir / "canary.txt"
    real_claude = profile_root / ".claude"
    target = f"sentinel-test-{uuid4().hex}"
    listener = _Listener()
    created_credential = False
    try:
        canary_dir.mkdir()
        canary_file.write_text("host-only canary", encoding="utf-8")
        created = _cmdkey(f"/generic:{target}", "/user:sentinel-test",
                          f"/pass:{secrets.token_urlsafe(24)}")
        assert created.returncode == 0, created.stdout + created.stderr
        created_credential = True
        # Positive controls on the host before the probe.
        listed = _cmdkey(f"/list:{target}")
        assert listed.returncode == 0 and f"Target: {target}" in listed.stdout, listed.stdout
        assert canary_file.read_text(encoding="utf-8") == "host-only canary"
        assert (user_repo / "calc.py").read_text(encoding="utf-8")
        claude_present = real_claude.is_dir()
        if claude_present:
            os.listdir(real_claude)  # the host can list it (read-only)
        # The probe is committed to the source so the workspace clone carries it
        # (a launch argument is limited to 2048 characters).
        write(user_repo, "probe.js", PROBE)
        git(user_repo, "add", "probe.js")
        git(user_repo, "commit", "-q", "-m", "containment probe")
        before = repo_fingerprint(user_repo)
        change_id = uuid4()

        config = {
            "repo": str(user_repo), "canary_dir": str(canary_dir),
            "canary_file": str(canary_file),
            "claude_dir": str(real_claude) if claude_present else None,
            "port": listener.port, "cmdkey": CMDKEY, "target": target,
        }
        run = fake_node_launcher.launcher.launch(
            change_id, str(user_repo), _launch_request(json.dumps(config)), 65_536)
        assert run.status is AgentRunStatus.PASSED, (run.stdout, run.stderr)
        probe = _parse_probe(run.stdout)
        accepted_from_container = listener.accepted

        # User repository: write and read denied; nothing landed there.
        assert probe["repo_write"]["ok"] is False
        assert probe["repo_write"]["code"] in DENIED_CODES, probe["repo_write"]
        assert probe["repo_read"]["ok"] is False
        assert probe["repo_read"]["code"] in DENIED_CODES, probe["repo_read"]
        assert not (user_repo / "pwned.txt").exists()
        assert repo_fingerprint(user_repo) == before
        # Real user profile: the canary is unreadable and unlistable from inside.
        assert probe["canary_read"]["ok"] is False
        assert probe["canary_read"]["code"] in DENIED_CODES, probe["canary_read"]
        assert probe["canary_list"]["ok"] is False
        assert probe["canary_list"]["code"] in DENIED_CODES, probe["canary_list"]
        # Real ~/.claude: listing denied (only probed when it exists on this machine).
        if claude_present:
            assert probe["claude_list"]["ok"] is False
            assert probe["claude_list"]["code"] in DENIED_CODES, probe["claude_list"]
        # Loopback: the container connect fails or times out; the listener saw nothing.
        loopback = probe["loopback"]
        assert loopback["connected"] is False, loopback
        assert loopback["elapsed_ms"] <= 4000, loopback
        assert accepted_from_container == 0
        # Credential Manager: the container sees no such target.
        # Some hosts (GitHub's windows-latest) deny the spawn itself; that is a
        # stronger denial, but then the empty-store observation is not made.
        if probe["cmdkey"]["ok"] is False:
            assert probe["cmdkey"]["code"] in DENIED_CODES, probe["cmdkey"]
        else:
            assert "NONE" in probe["cmdkey"]["value"]["output"], probe["cmdkey"]
            assert "Target:" not in probe["cmdkey"]["value"]["output"]
        # Positive control for the boundary being usable: the workspace write landed.
        assert probe["workspace_write"]["ok"] is True, probe["workspace_write"]
        record = workspace_manager.live_for_change(change_id)
        written = record.workspace_path / "containment-probe.txt"
        assert written.read_text(encoding="utf-8") == "written-inside"
        assert record.runs[-1]["facts"]["is_appcontainer"] is True

        # Host positive controls after the probe: loopback accepts, the credential exists.
        with socket.create_connection(("127.0.0.1", listener.port), timeout=3):
            pass
        for _ in range(50):
            if listener.accepted:
                break
            threading.Event().wait(0.05)
        assert listener.accepted == 1
        again = _cmdkey(f"/list:{target}")
        assert f"Target: {target}" in again.stdout
        workspace_manager.discard(change_id)
    finally:
        listener.close()
        if created_credential:
            _cmdkey(f"/delete:{target}")
        shutil.rmtree(canary_dir, ignore_errors=True)
    assert "NONE" in _cmdkey(f"/list:{target}").stdout
    assert not canary_dir.exists()


def _launch_request(config_json: str):
    from backend.app.contracts.models import AgentLaunchRequest

    from backend.tests.workspace.conftest import FAKE_NODE_ADAPTER

    return AgentLaunchRequest(adapter=FAKE_NODE_ADAPTER, executable="node",
                              args=["-e", RUN_PROBE, config_json], timeout_seconds=90)
