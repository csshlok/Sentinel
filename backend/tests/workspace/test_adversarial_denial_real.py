"""Phase 3 SC1 (SBOX-06): in-box denial suite, every denial paired with a host positive control.

The box is the ``claude`` runtime profile (``BoxedPythonLauncher``: same
capabilities, staged home, credential staging, per-run workspace drive and
static environment) running snapshot Python, so the probes can call Win32
directly. ``adversarial_probe.py`` makes one attempt per resource and reports the
OS error code; each attempt that must be denied is checked against the same
resource reached from the host in this test, so a broken probe can never pass
as a denial.

Probed here (beyond ``test_containment_real.py``):

* a Sentinel store replica restricted by ``prepare_store_directory`` (the
  SQLite database that holds the journal, a trust registry and an
  ``api_token``), plus the real ``%LOCALAPPDATA%\\Sentinel`` when it exists:
  list, read and write;
* another AppContainer's folder: read, list and write;
* executing a binary from outside the grants;
* TCP to this host's LAN address (no ``privateNetworkClientServer``), to
  ``localhost`` by name and to ``[::1]``;
* a host named pipe with its default DACL;
* Credential Manager through ``CredReadW`` / ``CredEnumerateW``;
* a CNG software/platform key, and the installation key name;
* registry key creation in HKCU and HKLM.

Still UNKNOWN after this file: another machine on the private network (only
this host's own LAN address is reachable here), devices other than named
pipes, ALPC/RPC endpoints, and the internet beyond the Phase 2 need test.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import winreg
from multiprocessing.connection import Client, Listener
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentRunStatus
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.support_kb import git, write
from backend.tests.workspace.conftest import (
    HOSTED_RUNNER_APPCONTAINER_GAP,
    TEST_PROFILE_PREFIX,
    repo_fingerprint,
)

pytestmark = [
    pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
    HOSTED_RUNNER_APPCONTAINER_GAP,
]

PROBE_SOURCE = Path(__file__).with_name("adversarial_probe.py")
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
CMDKEY = str(SYSTEM32 / "cmdkey.exe")
ERROR_ACCESS_DENIED = 5
ERROR_NOT_FOUND = 1168
NTE_BAD_KEYSET = 0x80090016
E_ACCESSDENIED = 0x80070005


class _Listener:
    """A host TCP listener that counts accepted connections."""

    def __init__(self, host: str, family: int = socket.AF_INET) -> None:
        self.server = socket.socket(family, socket.SOCK_STREAM)
        self.server.bind((host, 0))
        self.server.listen(8)
        self.server.settimeout(0.2)
        self.host = host
        self.family = family
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

    def control(self) -> None:
        """Host positive control: connect and wait until the accept is counted."""

        before = self.accepted
        with socket.socket(self.family, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect((self.host, self.port))
        for _ in range(60):
            if self.accepted > before:
                return
            threading.Event().wait(0.05)
        raise AssertionError(f"the host could not reach its own listener on {self.host}")

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.server.close()


class _Pipe:
    """A host named pipe (default DACL) that accepts connections in a thread."""

    def __init__(self) -> None:
        self.name = rf"\\.\pipe\sentinel-test-{uuid4().hex}"
        self.listener = Listener(self.name, family="AF_PIPE")
        self.accepted = 0
        self._closing = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._closing:
            try:
                connection = self.listener.accept()
            except OSError:
                return
            if not self._closing:
                self.accepted += 1
            connection.close()

    def close(self) -> None:
        self._closing = True
        try:
            Client(self.name, family="AF_PIPE").close()  # unblock accept()
        except OSError:
            pass
        self._thread.join(timeout=5)
        self.listener.close()


def _lan_address() -> str | None:
    """This host's outbound IPv4 address (no packet is sent), or None."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET-1: routing lookup only
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith(("127.", "0.")) else address


def _cmdkey(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([CMDKEY, *args], capture_output=True, text=True, timeout=30)


def _registry_key_exists(root: int, path: str) -> bool:
    try:
        winreg.CloseKey(winreg.OpenKey(root, path))
    except FileNotFoundError:
        return False
    return True


def _parse_probe(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.startswith("PROBE ")]
    assert len(lines) == 1, stdout
    return json.loads(lines[0][len("PROBE "):])


def _denied_file(result: dict) -> bool:
    """A file attempt failed with access denied (never "not found" or a probe bug)."""

    return (result["ok"] is False
            and (result.get("winerror") == ERROR_ACCESS_DENIED or result.get("errno") == 13))


def _commit_probe(repo: Path) -> None:
    write(repo, "adversarial_probe.py", PROBE_SOURCE.read_text(encoding="utf-8"))
    git(repo, "add", "adversarial_probe.py")
    git(repo, "commit", "-q", "-m", "adversarial probe")


def run_probe(launcher, change_id, repo: Path, suite: str, config: dict) -> tuple[object, dict]:
    """Create the workspace, grant the snapshot, run one probe suite; returns (run, results)."""

    record = launcher.prepare_workspace(change_id, repo)
    (Path(record.workspace_path) / "probe-config.json").write_text(
        json.dumps(config), encoding="utf-8")
    launcher.grant(record.package_sid)
    try:
        run = launcher.launch(change_id, repo, ["adversarial_probe.py", suite, "probe-config.json"])
    finally:
        launcher.revoke(record.package_sid)
    assert run.status is AgentRunStatus.PASSED, (run.stdout, run.stderr, run.limitations)
    return run, _parse_probe(run.stdout)


@pytest.fixture
def other_box():
    """A second (unrelated) AppContainer profile with a canary in its own folder."""

    from backend.app.execution.appcontainer import (
        delete_profile,
        ensure_profile,
        remove_tree_no_follow,
    )

    name = TEST_PROFILE_PREFIX + uuid4().hex
    profile, _ = ensure_profile(name, display_name="Sentinel test (other box)")
    canary = profile.container_path / "other-box-canary.txt"
    canary.write_text("other box only", encoding="utf-8")
    try:
        yield profile, canary
    finally:
        try:
            remove_tree_no_follow(profile.container_path)
        finally:
            delete_profile(name)
            remove_tree_no_follow(profile.container_path.parent)


@pytest.fixture
def store_replica(tmp_path: Path):
    """A ``Sentinel`` directory restricted exactly as the real store, with real contents."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from backend.app.core.database import Database
    from backend.app.core.evidence_store import prepare_store_directory
    from backend.app.passport.trust import TrustRegistry

    store = tmp_path / "store" / "Sentinel"
    assert prepare_store_directory(store) is True
    database = Database(store / "change_assurance.sqlite3")
    database.initialize()
    token = store / "api_token"
    token.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    spki = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    registry = TrustRegistry(store / "trusted_keys.json")
    registry.add(spki=spki, label="sentinel-test")
    return store, store / "change_assurance.sqlite3", token, registry.path


@pytest.fixture
def cng_test_key():
    from backend.app.passport.cng import CngKey

    key = CngKey.open(name=f"Sentinel test {uuid4()}")
    try:
        yield key
    finally:
        key.delete_for_test()
        key.close()


def test_the_claude_box_is_denied_every_host_resource_the_host_can_reach(
    tmp_path: Path, user_repo: Path, boxed_python_launcher, other_box, store_replica,
    cng_test_key,
) -> None:
    from backend.app.passport.cng import DEFAULT_KEY_NAME, PLATFORM_PROVIDER, SOFTWARE_PROVIDER, CngKey

    other_profile, other_canary = other_box
    store, db, token, trust = store_replica
    outside = tmp_path / "outside-bin"
    outside.mkdir()
    outside_exe = outside / "whoami.exe"
    shutil.copy2(SYSTEM32 / "whoami.exe", outside_exe)
    real_store = Path(os.environ["LOCALAPPDATA"]) / "Sentinel"
    real_canary = real_store / f"sentinel-test-canary-{uuid4().hex}.txt" if real_store.is_dir() \
        else None
    pwn_name = f"sentinel-test-pwned-{uuid4().hex}.txt"
    cred_target = f"sentinel-test-{uuid4().hex}"
    hkcu_key = rf"Software\sentinel-test-{uuid4().hex}"
    hklm_key = rf"SOFTWARE\sentinel-test-{uuid4().hex}"
    lan_ip = _lan_address()
    listeners = [_Listener("127.0.0.1")]
    v6 = None
    if socket.has_ipv6:
        try:
            v6 = _Listener("::1", socket.AF_INET6)
            listeners.append(v6)
        except OSError:
            v6 = None
    lan = _Listener(lan_ip) if lan_ip else None
    if lan is not None:
        listeners.append(lan)
    pipe = _Pipe()
    created_credential = False
    try:
        if real_canary is not None:
            real_canary.write_text("host-only store canary", encoding="utf-8")
        created = _cmdkey(f"/generic:{cred_target}", "/user:sentinel-test",
                          f"/pass:{secrets.token_urlsafe(24)}")
        assert created.returncode == 0, created.stdout + created.stderr
        created_credential = True

        # Host positive controls, before the probe.
        for listener in listeners:
            listener.control()
        Client(pipe.name, family="AF_PIPE").close()
        assert f"Target: {cred_target}" in _cmdkey(f"/list:{cred_target}").stdout
        assert other_canary.read_text(encoding="utf-8") == "other box only"
        assert os.listdir(store) and token.read_text(encoding="utf-8")
        assert db.read_bytes()[:16] == b"SQLite format 3\x00"
        assert json.loads(trust.read_text(encoding="utf-8"))
        assert subprocess.run([str(outside_exe)], capture_output=True, timeout=30).returncode == 0
        with CngKey.open_existing(name=cng_test_key.name):
            pass
        accepted_before = {listener.host: listener.accepted for listener in listeners}
        pipe_before = pipe.accepted

        _commit_probe(user_repo)
        before = repo_fingerprint(user_repo)
        stores = {"replica_store": {"dir": str(store), "canary": str(token)}}
        if real_canary is not None:
            stores["real_store"] = {"dir": str(real_store), "canary": str(real_canary)}
        config = {
            "stores": stores, "pwn_name": pwn_name, "db": str(db), "trust": str(trust),
            "other_dir": str(other_profile.container_path), "other_canary": str(other_canary),
            "outside_exe": str(outside_exe),
            "lan_ip": lan_ip, "lan_port": lan.port if lan else None,
            "v4_port": listeners[0].port, "v6_port": v6.port if v6 else None,
            "pipe": pipe.name, "cred_target": cred_target,
            "cng_providers": {"software": SOFTWARE_PROVIDER, "platform": PLATFORM_PROVIDER},
            "cng_test_key": cng_test_key.name, "cng_default_key": DEFAULT_KEY_NAME,
            "hkcu_key": hkcu_key, "hklm_key": hklm_key,
        }
        change_id = uuid4()
        run, probe = run_probe(boxed_python_launcher, change_id, user_repo, "denial", config)
        print(json.dumps(probe, indent=1))  # the observed denials, kept in the test log

        # The boundary itself: a verified AppContainer run that could write its workspace.
        record = boxed_python_launcher.workspaces.live_for_change(change_id)
        facts = record.runs[-1]["facts"]
        assert facts["is_appcontainer"] is True
        assert facts["package_sid"] == record.package_sid
        assert probe["workspace_write"]["ok"] is True, probe["workspace_write"]
        assert (Path(record.workspace_path) / "adversarial-probe.txt").read_text(
            encoding="utf-8") == "written-inside"

        # Sentinel's own data: store, database (with the journal) and trust registry.
        for label in stores:
            for action in ("list", "canary_read", "write"):
                assert _denied_file(probe[f"{label}_{action}"]), (label, action, probe)
        assert not (store / pwn_name).exists() and not (real_store / pwn_name).exists()
        for action in ("db_read", "db_write", "trust_read", "trust_write"):
            assert _denied_file(probe[action]), (action, probe[action])
        assert json.loads(trust.read_text(encoding="utf-8"))  # unchanged, still the registry
        # Another box's folder.
        for action in ("other_box_read", "other_box_list", "other_box_write"):
            assert _denied_file(probe[action]), (action, probe[action])
        assert not (other_profile.container_path / "pwned.txt").exists()
        # Execute outside the grants.
        assert _denied_file(probe["exec_outside"]), probe["exec_outside"]
        # Network: no connection reached any host listener.
        for name in ("localhost_connect", "ipv6_loopback_connect", "lan_connect"):
            if name in probe:
                assert probe[name]["ok"] is False, (name, probe[name])
        assert {l.host: l.accepted for l in listeners} == accepted_before
        if lan is None:
            print("UNKNOWN: no LAN IPv4 address, the private-network probe did not run")
        # Named pipe.
        assert probe["named_pipe"]["ok"] is False, probe["named_pipe"]
        assert probe["named_pipe"]["last_error"] == ERROR_ACCESS_DENIED, probe["named_pipe"]
        assert pipe.accepted == pipe_before
        # Credential Manager: the canary is not visible, and nothing is enumerable.
        assert probe["cred_read"]["ok"] is False, probe["cred_read"]
        assert probe["cred_read"]["last_error"] in {ERROR_NOT_FOUND, ERROR_ACCESS_DENIED}
        count = probe["cred_count"]
        assert (count["ok"] is False and count["last_error"] in {ERROR_NOT_FOUND,
                                                                 ERROR_ACCESS_DENIED}) \
            or (count["ok"] is True and count["value"] == 0), count
        # CNG: neither the test key nor the installation key opens in the box.
        for label in ("software", "platform"):
            for kind in ("test", "default"):
                result = probe[f"cng_{kind}_key_{label}"]
                assert result["ok"] is False, (label, kind, result)
                # A CNG status (the key is invisible or denied), never a probe failure.
                assert result.get("last_error") in {NTE_BAD_KEYSET, E_ACCESSDENIED}, result
        # Registry: no key was created in the real hives.
        assert probe["hklm_create"]["ok"] is False, probe["hklm_create"]
        assert not _registry_key_exists(winreg.HKEY_LOCAL_MACHINE, hklm_key)
        assert not _registry_key_exists(winreg.HKEY_CURRENT_USER, hkcu_key)
        assert probe["hkcu_create"]["ok"] is False, probe["hkcu_create"]
        # The user repository is untouched.
        assert repo_fingerprint(user_repo) == before

        # Host positive controls after the probe: everything is still reachable.
        for listener in listeners:
            listener.control()
        assert f"Target: {cred_target}" in _cmdkey(f"/list:{cred_target}").stdout
        with CngKey.open_existing(name=cng_test_key.name):
            pass
        boxed_python_launcher.workspaces.discard(change_id)
    finally:
        for listener in listeners:
            listener.close()
        pipe.close()
        if created_credential:
            _cmdkey(f"/delete:{cred_target}")
        if real_canary is not None:
            real_canary.unlink(missing_ok=True)
            (real_store / pwn_name).unlink(missing_ok=True)
    assert "NONE" in _cmdkey(f"/list:{cred_target}").stdout
