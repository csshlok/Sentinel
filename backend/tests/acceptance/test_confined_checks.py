"""Phase 5 acceptance: agent-authored checks run confined, through the real HTTP API (05-05).

Real Windows, real boundary. A live uvicorn server runs ``create_app`` with real
``CheckBoxes`` (``sentinel.test.`` profiles, a throwaway runtime cache); every
check is requested over HTTP exactly as a client would, and the box is a real
per-run AppContainer. A separate raw 127.0.0.1 listener stands in for "any
other local port" beside the real API port.

Each escape class has a positive control: the same agent-authored file run on
the host, at user authority, in a throwaway copy of the repository outside
Sentinel, must succeed at every attempt. Only then does the confined denial
mean anything. The attempts are:

- write a canary outside the check tree (the user repository, the Sentinel
  store, ``%PUBLIC%``);
- read the Sentinel store (api_token, database, trust registry) and list it,
  plus list the real ``%LOCALAPPDATA%\\Sentinel`` when this machine has one;
- read the user repository directly (its git-ignored ``.env``, a listing);
- read a Windows Credential Manager secret (Sentinel's credential store kind);
- open a persisted per-user CNG signing key (Sentinel's Passport key kind);
- connect to the live API port and to the stand-in port;
- reach the internet without a declared network (separate test; skipped only
  when the host itself is offline, because then the control cannot pass).

The Node variant (``npm test`` running a package.json script) covers the file
and port attempts; it does not attempt Win32 credential or key APIs.
The unsupported-toolchain test uses a stand-in ``cargo.bat`` on PATH (no Rust
toolchain is needed to prove how Sentinel routes ``cargo``).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.support_kb import git, make_repo, write

FIXTURES = Path(__file__).parent / "fixtures" / "confined"

# GitHub-hosted runners: the hosted Python install holds a reparse point, so the
# check-runtime snapshot is refused by design (CHECK_RUNTIME_UNSAFE_SOURCE), and
# `npm test` spawns cmd.exe from System32, which the hosted Server SKU denies an
# AppContainer. These tests need a real box, so they skip there unless opted in.
HOSTED_RUNNER_CHECK_RUNTIME_GAP = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("SENTINEL_CI_REAL_APPCONTAINER") != "1",
    reason="hosted runner: Python install has a reparse point (snapshot refused by design) "
           "and System32 spawns are denied inside an AppContainer; "
           "set SENTINEL_CI_REAL_APPCONTAINER=1 to run",
)

pytestmark = [
    pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
    pytest.mark.real_check_boxes,
    HOSTED_RUNNER_CHECK_RUNTIME_GAP,
]

TEST_PREFIX = "sentinel.test."
PROBE_MARKER = "SENTINEL_PROBE "
INTERNET = ("1.1.1.1", 443)
PYTEST_ARGS = ["-s", "-q", "-p", "no:cacheprovider", "tests"]


# ------------------------------------------------------------------ live API


class _RequestLog:
    """ASGI wrapper recording every HTTP request the live API receives."""

    def __init__(self, app) -> None:
        self.app = app
        self.requests: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            with self._lock:
                self.requests.append((scope["method"], scope["path"]))
        await self.app(scope, receive, send)

    def count(self) -> int:
        with self._lock:
            return len(self.requests)


class _StandInListener:
    """A live 127.0.0.1 port that records every connection it accepts."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted: list[tuple[str, int]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                connection, address = self.sock.accept()
            except (TimeoutError, OSError):
                continue
            self.accepted.append(address)
            connection.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(5)
        self.sock.close()


@dataclass
class LiveApi:
    base: str
    port: int
    store: Path
    database: Path
    log: _RequestLog
    listener: _StandInListener
    app: object
    client: object
    sent: list[str] = field(default_factory=list)

    def call(self, method: str, path: str, **kwargs):
        self.sent.append(path)
        return self.client.request(method, path, **kwargs)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def runtime_cache(tmp_path_factory):
    from backend.tests.workspace.conftest import delete_test_profiles

    cache = tmp_path_factory.mktemp("confined-acceptance") / "check-runtimes"
    try:
        yield cache
    finally:
        delete_test_profiles()
        shutil.rmtree(cache, ignore_errors=True)


@pytest.fixture
def live_api(tmp_path, runtime_cache, monkeypatch):
    import httpx
    import uvicorn

    import backend.app.main as main
    from backend.app.core.config import Settings
    from backend.app.core.evidence_store import prepare_store_directory
    from backend.app.credentials.memory_store import InMemoryCredentialStore
    from backend.app.execution.check_box import CheckBoxes

    # A Sentinel store laid out and ACL'd like the real one (user + SYSTEM only).
    store = tmp_path / "LocalAppData" / "Sentinel"
    assert prepare_store_directory(store) is True
    (store / "trusted_keys.json").write_text('{"schema_version": 1, "keys": []}\n',
                                             encoding="utf-8")

    def real_boxes(database, *, journal=None, **_kwargs):
        return CheckBoxes(database, journal=journal, profile_prefix=TEST_PREFIX,
                          runtime_root=runtime_cache)

    monkeypatch.setattr(main, "CheckBoxes", real_boxes)
    database = store / "sentinel.sqlite3"
    app = main.create_app(settings=Settings(database_path=database),
                          credential_store=InMemoryCredentialStore())
    log = _RequestLog(app)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(log, host="127.0.0.1", port=port, lifespan="on",
                                          log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 60
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "live API did not start"
        time.sleep(0.05)
    listener = _StandInListener()
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1", timeout=900,
                          headers={"Authorization": f"Bearer {app.state.api_token}"})
    api = LiveApi(base=f"http://127.0.0.1:{port}", port=port, store=store, database=database,
                  log=log, listener=listener, app=app, client=client)
    try:
        yield api
    finally:
        client.close()
        server.should_exit = True
        thread.join(30)
        listener.close()
        report = app.state.check_boxes.sweep(live_run_ids=())
        assert not getattr(report, "failed", None), report


# ------------------------------------------------------------------ host secrets


@pytest.fixture
def credential():
    """A generic Windows credential, the kind Sentinel's credential store keeps."""

    from backend.app.credentials.windows_store import WindowsCredentialStore

    prefix = TEST_PREFIX + uuid4().hex
    store = WindowsCredentialStore(target_prefix=prefix)
    store.put("github", "canary-secret-" + uuid4().hex)
    try:
        yield f"{prefix}:github"
    finally:
        store.delete("github")


@pytest.fixture
def signing_key():
    """A persisted per-user CNG key created exactly as Sentinel creates its Passport key."""

    from backend.app.passport.cng import CngKey

    name = TEST_PREFIX + uuid4().hex
    key = CngKey.open(name=name)
    try:
        yield name
    finally:
        key.delete_for_test()


# ------------------------------------------------------------------ helpers


def _probe_line(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.startswith(PROBE_MARKER)]
    assert len(lines) == 1, stdout
    return json.loads(lines[0][len(PROBE_MARKER):])


def _render(template: str, config: dict) -> str:
    text = (FIXTURES / template).read_text(encoding="utf-8")
    return text.replace("__CONFIG__", json.dumps(config))


def _copy_outside(repo: Path, destination: Path) -> Path:
    """A throwaway copy of the working tree (no .git) outside Sentinel, for the control."""

    shutil.copytree(repo, destination, ignore=shutil.ignore_patterns(".git"))
    return destination


def _host_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("PYTEST_", "COV_"))}


def _host_pytest(directory: Path) -> dict:
    completed = subprocess.run([sys.executable, "-m", "pytest", *PYTEST_ARGS], cwd=directory,
                               capture_output=True, text=True, timeout=300, env=_host_env())
    return _probe_line(completed.stdout)


def _node() -> Path:
    found = shutil.which("node")
    if found is None:
        pytest.skip("Node.js is not installed on this machine (node.exe not on PATH)")
    return Path(found)


def _host_npm_test(directory: Path) -> subprocess.CompletedProcess:
    node = _node()
    npm_cli = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    return subprocess.run([str(node), str(npm_cli), "test"], cwd=directory, capture_output=True,
                          text=True, timeout=300, env=_host_env())


def _create_change(api: LiveApi, repo: Path, **contract) -> str:
    response = api.call("POST", "/changes", json={
        "title": "Confined checks", "intent": "Run the agent's checks",
        "repository_path": str(repo), "contract": contract})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _actor(api: LiveApi, change_id: str, scopes: list[str]) -> str:
    actor = api.call("POST", "/actors", json={"kind": "HUMAN", "display_name": "Dev"}).json()["id"]
    grantor = api.call("POST", "/actors", json={"kind": "HUMAN", "display_name": "Lead"}).json()["id"]
    response = api.call("POST", "/delegations", json={
        "grantor_id": grantor, "grantee_id": actor, "change_id": change_id,
        "scopes": scopes, "ttl_seconds": 3600})
    assert response.status_code == 201, response.text
    return actor


def _verify(api: LiveApi, change_id: str, actor: str, executable: str, args: list[str]):
    return api.call("POST", f"/changes/{change_id}/verify", json={
        "actor_id": actor,
        "verification": {"executable": executable, "args": args, "timeout_seconds": 300}})


def _journal(api: LiveApi, change_id: str, event_type: str) -> list[dict]:
    from backend.app.core.database import Database

    with Database(api.database).connection() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM journal_events WHERE change_id = ? AND event_type = ? "
            "ORDER BY seq", (change_id, event_type)).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def _check_runs(api: LiveApi, change_id: str) -> list[dict]:
    response = api.call("GET", f"/changes/{change_id}/checks")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _assert_confined_run(api: LiveApi, change_id: str, verification: dict) -> None:
    assert verification["boundary"] == "APPCONTAINER"
    run_id = verification["check_run_id"]
    runs = {item["id"]: item for item in _check_runs(api, change_id)}
    assert runs[run_id]["boundary"] == "APPCONTAINER"
    assert runs[run_id]["state"] == "CLEANED"
    assert runs[run_id]["token"]["is_appcontainer"] is True
    events = [event for event in _journal(api, change_id, "check.confined_run")
              if event["check_run_id"] == run_id]
    assert events, "no check.confined_run journaled"
    assert all(event["boundary"] == "APPCONTAINER" and event["is_appcontainer"] is True
               and event["job_verified"] is True and event["capabilities"] == []
               for event in events)
    assert _journal(api, change_id, "check.unconfined_run") == []


def _no_test_profiles_left() -> None:
    from backend.app.execution.appcontainer import local_appdata_known_folder

    packages = local_appdata_known_folder() / "Packages"
    # Only profiles this module created could match; the module fixture removes the rest.
    leftovers = [path.name for path in packages.glob(TEST_PREFIX + "*")]
    assert leftovers == [], leftovers


def _escape_config(api: LiveApi, repo: Path, canary: str) -> tuple[dict, list[Path]]:
    public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    canaries = [repo / canary, api.store / canary, public / canary]
    config = {
        "writes": {"repo": str(canaries[0]), "store": str(canaries[1]), "public": str(canaries[2])},
        "reads": {"repo_env": str(repo / ".env"), "api_token": str(api.store / "api_token"),
                  "database": str(api.database),
                  "trust_registry": str(api.store / "trusted_keys.json")},
        "lists": {"repo": str(repo), "store": str(api.store)},
        "ports": {"api": api.port, "standin": api.listener.port},
    }
    real_store = Path(os.environ["LOCALAPPDATA"]) / "Sentinel"
    if real_store.is_dir():  # this machine's own Sentinel store
        config["lists"]["real_store"] = str(real_store)
    return config, canaries


def _remove(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


# ------------------------------------------------------------------ SC1 (Python)

PY_FILES = {
    ".gitignore": ".env\n__pycache__/\n.pytest_cache/\n",
    "calc.py": "def add(left, right):\n    return left + right\n",
    "tests/test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
}


def test_python_conftest_escapes_are_denied_through_the_api(
    live_api: LiveApi, tmp_path: Path, credential: str, signing_key: str,
) -> None:
    api = live_api
    repo = make_repo(tmp_path / "repo", PY_FILES)
    write(repo, ".env", "SECRET=canary-in-the-user-repository\n")  # git-ignored
    canary = f"escaped-{uuid4().hex}.txt"
    config, canaries = _escape_config(api, repo, canary)
    config |= {"credential_target": credential, "signing_key_name": signing_key}
    # Agent-authored and never committed: an untracked file is part of the check tree.
    write(repo, "conftest.py", _render("hostile_conftest.py.tmpl", config))

    # Positive control: at user authority, outside Sentinel, every attempt succeeds.
    before_control = api.log.count()
    control = _host_pytest(_copy_outside(repo, tmp_path / "control-copy"))
    attempts = {key: value for key, value in control.items()
                if key not in {"cwd", "tree_has_ignored_env"}}
    assert attempts and all(value == "allowed" for value in attempts.values()), control
    assert all(path.exists() for path in canaries)
    assert api.log.count() > before_control  # the control really reached the live API
    assert len(api.listener.accepted) >= 1
    _remove(canaries)
    accepted_before = len(api.listener.accepted)

    # The same file, run as a check through the API, inside a real box.
    change_id = _create_change(api, repo)
    actor = _actor(api, change_id, ["change.legacy_verify"])
    requests_before, sent_before = api.log.count(), len(api.sent)
    response = _verify(api, change_id, actor, "pytest", PYTEST_ARGS)
    assert response.status_code == 200, response.text
    # The live API saw only this test's own requests while the check ran.
    assert api.log.count() - requests_before == len(api.sent) - sent_before
    verification = response.json()["verification"]
    assert verification["status"] == "PASSED", verification["stderr"]
    probe = _probe_line(verification["stdout"])
    print("confined probe:", json.dumps(probe, sort_keys=True))

    assert Path(probe["cwd"]).name == "tree"
    assert probe["tree_has_ignored_env"] is False  # ignored files never enter the box
    for name in config["writes"]:
        assert probe["write_" + name].startswith("denied:PermissionError"), probe
    for name in config["reads"]:
        assert probe["read_" + name].startswith("denied:PermissionError"), probe
    for name in config["lists"]:
        assert probe["list_" + name].startswith("denied:PermissionError"), probe
    for name in config["ports"]:
        # The control proved both ports accept connections; the box's SYN never arrives.
        assert probe["connect_" + name] == "denied:TimeoutError:", probe
    # Credential Manager refuses the AppContainer token outright (ERROR_ACCESS_DENIED).
    assert probe["credential"] == "denied:PermissionError:5", probe
    # The per-user key the control opened does not exist for the box (NTE_BAD_KEYSET
    # 0x80090016 on this machine): NCrypt never exposes it to the AppContainer.
    assert probe["signing_key"].startswith("denied:OSError:0x8"), probe
    assert "canary-secret" not in verification["stdout"]

    assert not any(path.exists() for path in canaries)  # nothing landed
    assert len(api.listener.accepted) == accepted_before  # no connection reached the port
    assert not (repo / "conftest-result.txt").exists()
    _assert_confined_run(api, change_id, response.json()["verification"])
    _no_test_profiles_left()


def test_internet_is_denied_without_a_declared_network(live_api: LiveApi, tmp_path: Path) -> None:
    api = live_api
    try:
        with socket.create_connection(INTERNET, timeout=8):
            pass
    except OSError as exc:
        pytest.skip(f"host cannot reach {INTERNET[0]}:{INTERNET[1]} ({exc!r}); "
                    "the positive control cannot pass offline")
    repo = make_repo(tmp_path / "repo", PY_FILES)
    config = {"writes": {}, "reads": {}, "lists": {}, "ports": {},
              "internet_host": INTERNET[0], "internet_port": INTERNET[1]}
    write(repo, "conftest.py", _render("hostile_conftest.py.tmpl", config))
    control = _host_pytest(_copy_outside(repo, tmp_path / "control-copy"))
    assert control["internet"] == "allowed", control

    change_id = _create_change(api, repo)
    actor = _actor(api, change_id, ["change.legacy_verify"])
    response = _verify(api, change_id, actor, "pytest", PYTEST_ARGS)
    assert response.status_code == 200, response.text
    verification = response.json()["verification"]
    probe = _probe_line(verification["stdout"])
    print("confined probe:", json.dumps(probe, sort_keys=True))
    assert probe["internet"].startswith("denied:"), probe
    _assert_confined_run(api, change_id, verification)
    runs = _check_runs(api, change_id)
    assert all(run["network"] is False for run in runs)


# ------------------------------------------------------------------ SC1 (Node)


def test_node_package_script_escapes_are_denied_through_the_api(
    live_api: LiveApi, tmp_path: Path,
) -> None:
    _node()
    api = live_api
    repo = make_repo(tmp_path / "repo", {
        ".gitignore": ".env\nnode_modules/\n",
        "package.json": json.dumps({"name": "hostile", "version": "1.0.0", "private": True,
                                    "scripts": {"test": "node probe.js"}}, indent=2) + "\n",
    })
    write(repo, ".env", "SECRET=canary-in-the-user-repository\n")
    canary = f"escaped-{uuid4().hex}.txt"
    config, canaries = _escape_config(api, repo, canary)
    write(repo, "probe.js", _render("hostile_probe.js.tmpl", config))
    git(repo, "add", "probe.js")
    git(repo, "commit", "-q", "-m", "agent: add test script")

    control_run = _host_npm_test(_copy_outside(repo, tmp_path / "control-copy"))
    control = _probe_line(control_run.stdout)
    attempts = {key: value for key, value in control.items()
                if key not in {"cwd", "tree_has_ignored_env"}}
    assert attempts and all(value == "allowed" for value in attempts.values()), control
    assert all(path.exists() for path in canaries)
    _remove(canaries)
    accepted_before = len(api.listener.accepted)

    change_id = _create_change(api, repo)
    actor = _actor(api, change_id, ["change.legacy_verify"])
    requests_before, sent_before = api.log.count(), len(api.sent)
    response = _verify(api, change_id, actor, "npm", ["test"])
    assert response.status_code == 200, response.text
    assert api.log.count() - requests_before == len(api.sent) - sent_before
    verification = response.json()["verification"]
    assert verification["status"] == "PASSED", verification["stdout"] + verification["stderr"]
    probe = _probe_line(verification["stdout"])
    print("confined probe:", json.dumps(probe, sort_keys=True))

    assert Path(probe["cwd"]).name == "tree"
    assert probe["tree_has_ignored_env"] is False
    for name in config["writes"]:
        assert probe["write_" + name] == "denied:EPERM", probe
    for name in config["reads"]:
        assert probe["read_" + name] == "denied:EPERM", probe
    for name in config["lists"]:
        assert probe["list_" + name] == "denied:EPERM", probe
    for name in config["ports"]:
        assert probe["connect_" + name] in {"denied:ETIMEDOUT", "denied:TIMEOUT"}, probe
    assert not any(path.exists() for path in canaries)
    assert len(api.listener.accepted) == accepted_before
    _assert_confined_run(api, change_id, verification)
    _no_test_profiles_left()


# ------------------------------------------------------------------ unsupported toolchain

CARGO_STANDIN = (
    "@echo off\r\n"
    "echo stand-in cargo %*\r\n"
    "echo ran at user authority> \"%CD%\\cargo-ran.txt\"\r\n"
    "exit /b 0\r\n"
)


def test_unsupported_toolchain_needs_the_opt_in_and_is_reported_unconfined(
    live_api: LiveApi, tmp_path: Path, monkeypatch,
) -> None:
    from backend.app.core.database import Database
    from backend.app.passport.v2 import PassportV2Issuer

    api = live_api
    toolchain = tmp_path / "stand-in-toolchain"
    toolchain.mkdir()
    (toolchain / "cargo.bat").write_text(CARGO_STANDIN, encoding="ascii", newline="")
    monkeypatch.setenv("PATH", str(toolchain) + os.pathsep + os.environ["PATH"])
    assert Path(shutil.which("cargo")).parent == toolchain

    repo = make_repo(tmp_path / "repo", {"src/lib.rs": "pub fn add() {}\n"})
    change_id = _create_change(api, repo, schema_version=3, max_risk="HIGH",
                               policy_preset_name="strict", policy_change_type="code")

    # Without the delegated opt-in: refused before anything runs.
    plain = _actor(api, change_id, ["change.legacy_verify"])
    refused = _verify(api, change_id, plain, "cargo", ["test"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "CHECK_TOOLCHAIN_UNCONFINED"
    assert not (repo / "cargo-ran.txt").exists()
    assert _check_runs(api, change_id) == []

    # With checks.unconfined on a HIGH-risk Change: it runs, and is reported UNCONFINED.
    delegated = _actor(api, change_id, ["change.legacy_verify", "checks.unconfined"])
    response = _verify(api, change_id, delegated, "cargo", ["test"])
    assert response.status_code == 200, response.text
    verification = response.json()["verification"]
    assert verification["status"] == "PASSED"
    assert "stand-in cargo test" in verification["stdout"]
    assert verification["boundary"] == "UNCONFINED"
    # Honest: an unconfined run really runs in the user repository at user authority.
    assert (repo / "cargo-ran.txt").exists()
    runs = _check_runs(api, change_id)
    assert [run["boundary"] for run in runs] == ["UNCONFINED"]
    assert runs[0]["id"] == verification["check_run_id"]
    assert _journal(api, change_id, "check.confined_run") == []
    assert [event["boundary"] for event in _journal(api, change_id, "check.unconfined_run")] == [
        "UNCONFINED"]

    claims = PassportV2Issuer(Database(api.database)).snapshot(UUID(change_id))
    assert claims.confined_checks == "FAIL"
    assert claims.policy_preset_name == "strict"
    assert claims.policy_decision == "DENY"
    assert any("confined checks" in reason.casefold() for reason in claims.policy_denials)


# ------------------------------------------------------------------ SC2 (legit checks pass)

PY_BEFORE = {
    ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
    "module.py": "def old():\n    return 1\n\n\ndef new():\n    return 1\n",
    "tests/test_module.py": "from module import new, old\n\n\ndef test_old():\n    assert old() == 1\n",
}
PY_AFTER = {
    "module.py": "def old():\n    return 1\n\n\ndef new():\n    return 2\n",
    "tests/test_module.py": ("from module import new, old\n\n\ndef test_old():\n    assert old() == 1\n"
                             "\n\ndef test_new():\n    assert new() == 2\n"),
}


def test_real_python_fixture_reaches_diff_exercised_pass_confined(
    live_api: LiveApi, tmp_path: Path,
) -> None:
    from backend.app.core.database import Database
    from backend.app.passport.v2 import PassportV2Issuer

    api = live_api
    repo = make_repo(tmp_path / "repo", PY_BEFORE)
    change_id = _create_change(api, repo, schema_version=2, diff_coverage_rule={
        "required": True, "minimum_percent": 80, "policy_version": "required-v1"})
    base = f"/changes/{change_id}"
    baseline = api.call("POST", f"{base}/evidence/baseline")
    assert baseline.status_code == 201, baseline.text
    for name, text in PY_AFTER.items():
        write(repo, name, text)
    tested = api.call("POST", f"{base}/evidence/current")
    assert tested.status_code == 201, tested.text
    measured = api.call("POST", f"{base}/assurance/diff-coverage", json={
        "baseline_checkpoint_id": baseline.json()["checkpoint"]["id"],
        "tested_checkpoint_id": tested.json()["checkpoint"]["id"],
        "interpreter_path": sys.executable,
    })
    assert measured.status_code == 200, measured.text
    body = measured.json()
    assert body["checks_passed"] is True, body
    assert body["diff_exercised"] == "PASS", body
    assert body["gate_satisfied"] is True, body
    assert body["boundary"] == "APPCONTAINER"
    assert body["collection_boundary"] == "APPCONTAINER_IN_PROCESS"
    runs = {run["id"]: run for run in _check_runs(api, change_id)}
    assert runs[body["check_run_id"]]["boundary"] == "APPCONTAINER"
    claims = PassportV2Issuer(Database(api.database)).snapshot(UUID(change_id))
    assert claims.confined_checks == "PASS"
    _no_test_profiles_left()


def test_real_node_fixture_npm_test_passes_with_the_node_modules_snapshot(
    live_api: LiveApi, tmp_path: Path,
) -> None:
    _node()
    api = live_api
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "node_project", repo, ignore=shutil.ignore_patterns("vendor"))
    write(repo, ".gitignore", "node_modules/\n")
    make_repo(repo, {})  # commit the fixture sources (node_modules stays ignored)
    shutil.copytree(FIXTURES / "node_project" / "vendor" / "tiny-add",
                    repo / "node_modules" / "tiny-add")
    assert "node_modules" not in git(repo, "ls-files")

    change_id = _create_change(api, repo)
    actor = _actor(api, change_id, ["change.legacy_verify"])
    response = _verify(api, change_id, actor, "npm", ["test"])
    assert response.status_code == 200, response.text
    verification = response.json()["verification"]
    assert verification["status"] == "PASSED", verification["stdout"] + verification["stderr"]
    lines = [line for line in verification["stdout"].splitlines()
             if line.startswith("SENTINEL_NODE_FIXTURE ok ")]
    assert len(lines) == 1, verification["stdout"]
    # The dependency resolved from the read-only node_modules snapshot, not the tree.
    resolved = lines[0].split(" ", 2)[2]
    assert "check-runtimes" in resolved and "\\tree\\" not in resolved, resolved
    _assert_confined_run(api, change_id, verification)
    _no_test_profiles_left()
