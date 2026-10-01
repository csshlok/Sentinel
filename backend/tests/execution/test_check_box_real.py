"""Real Windows proof of the confined check box: tree, run, outputs, containment, cleanup.

Uses a real ``sentinel.test.*`` AppContainer profile per box, the snapshot
python built by ``python_runtime(sys.executable)`` into a throwaway cache, and a
real Git repository with tracked, untracked and ignored files. Every test cleans
its profiles; a module finalizer removes any ``sentinel.test.*`` leftover.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.execution.process_supervisor import IS_WINDOWS

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

if IS_WINDOWS:
    from backend.tests.workspace.conftest import (
        HOSTED_RUNNER_APPCONTAINER_GAP,
        delete_test_profiles,
        security_sddl,
    )

    pytestmark = [pytestmark, HOSTED_RUNNER_APPCONTAINER_GAP]

TEST_PROFILE_PREFIX = "sentinel.test."
REPO_ROOT = Path(__file__).resolve().parents[3]
CANARY = "canary-secret-7f3a9c0e5b"


@pytest.fixture(scope="module", autouse=True)
def _sweep_test_profiles():
    yield
    delete_test_profiles()


@pytest.fixture(scope="module")
def cache_and_runtime(tmp_path_factory):
    from backend.app.execution.check_box import python_box_runtime
    from backend.app.execution.check_runtime import python_runtime

    cache = tmp_path_factory.mktemp("check-box-real") / "check-runtimes"
    try:
        yield cache, python_box_runtime(python_runtime(sys.executable, root=cache))
    finally:
        shutil.rmtree(cache, ignore_errors=True)


@pytest.fixture
def database(tmp_path):
    from backend.app.core.database import Database

    database = Database(tmp_path / "checks.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def boxes(database, cache_and_runtime):
    from backend.app.core.journal import JournalWriter
    from backend.app.execution.check_box import CheckBoxes

    cache, _ = cache_and_runtime
    manager = CheckBoxes(database, journal=JournalWriter(database),
                         profile_prefix=TEST_PROFILE_PREFIX, runtime_root=cache)
    yield manager
    manager.sweep(live_run_ids=())


@pytest.fixture
def repo(tmp_path) -> Path:
    from backend.tests.support_kb import make_repo, write

    root = make_repo(tmp_path / "user-repo", {
        "calc.py": "def add(a, b):\n    return a + b\n",
        "pkg/mod.py": "VALUE = 1\n",
        ".gitignore": ".env\n.venv/\nnode_modules/\n",
    })
    write(root, "untracked.py", "NEW = 2\n")
    write(root, ".env", f"SECRET={CANARY}\n")
    write(root, "node_modules/left-pad/index.js", "module.exports = 1\n")
    return root


def _make_change(database) -> UUID:
    from backend.app.contracts.models import ChangeContract
    from backend.app.core.change_repository import ChangeRepository, StoredChange

    now = datetime.now(UTC)
    change_id = uuid4()
    ChangeRepository(database).create(StoredChange(
        id=change_id, title="Real check box", intent="Prove the confined check box",
        repository_path="C:\\work\\repo", created_at=now, updated_at=now,
        last_refreshed_at=None, git_summary=None, verification=None,
        contract=ChangeContract(),
    ))
    return change_id


def _events(database, change_id: UUID) -> list[dict]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT event_type, payload_json FROM journal_events WHERE change_id = ? "
            "ORDER BY seq", (str(change_id),),
        ).fetchall()
    return [{"type": row["event_type"], "payload": json.loads(row["payload_json"])}
            for row in rows]


def _assert_box_gone(profile_name: str, container: Path) -> None:
    from backend.app.execution.appcontainer import local_appdata_known_folder, profile_exists

    assert not profile_exists(profile_name)
    assert not os.path.lexists(container / "tree")
    assert not os.path.lexists(local_appdata_known_folder() / "Packages" / profile_name)


PROBE = r"""
import json, os, socket, sys
targets = json.loads(sys.argv[1])
results = {}

def attempt(name, action):
    try:
        action()
        results[name] = "allowed"
    except Exception as exc:
        results[name] = "denied:" + type(exc).__name__

def write(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("pwned")

attempt("scratch_write", lambda: write(os.path.join(targets["scratch"], "out.txt")))
attempt("tree_read", lambda: open("calc.py", encoding="utf-8").read())
attempt("repo_write", lambda: write(os.path.join(targets["repo"], "pwned.txt")))
attempt("repo_env_read", lambda: open(os.path.join(targets["repo"], ".env")).read())
attempt("sentinel_write", lambda: write(os.path.join(targets["sentinel"], "pwned.txt")))
attempt("profile_write", lambda: write(os.path.join(targets["home"], "sentinel-box-pwned.txt")))
attempt("loopback", lambda: socket.create_connection(("127.0.0.1", targets["port"]), timeout=3).close())
print(json.dumps(results))
"""


def test_real_box_tree_run_outputs_containment_and_cleanup(
    boxes, database, repo, cache_and_runtime,
) -> None:
    from backend.app.execution.appcontainer import local_appdata_known_folder

    cache, runtime = cache_and_runtime
    entries = [snapshot.path for snapshot in runtime.snapshots]
    acl_before = [security_sddl(entry) for entry in entries]
    change_id = _make_change(database)
    sentinel_dir = local_appdata_known_folder() / "Sentinel"
    sentinel_dir.mkdir(exist_ok=True)
    home = Path.home()
    planted = [repo / "pwned.txt", sentinel_dir / "pwned.txt", home / "sentinel-box-pwned.txt"]
    assert not any(path.exists() for path in planted)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with boxes.open(change_id, repo, runtime) as box:
            files = {path.relative_to(box.tree).as_posix()
                     for path in box.tree.rglob("*") if path.is_file()}
            assert files == {".gitignore", "calc.py", "pkg/mod.py", "untracked.py"}
            assert CANARY not in "".join(
                path.read_text(encoding="utf-8") for path in box.tree.rglob("*") if path.is_file())
            # The package SID holds a read ACE on each runtime entry only while the box exists.
            assert all(box.package_sid in security_sddl(entry) for entry in entries)
            targets = {"scratch": str(box.scratch), "repo": str(repo),
                       "sentinel": str(sentinel_dir), "home": str(home), "port": port}
            result = box.run([str(runtime.executable), "-c", PROBE, json.dumps(targets)],
                             timeout=120, limit=65_536)
            assert result.exit_code == 0, result.stderr.decode(errors="replace")
            outcome = json.loads(result.stdout.decode())
            # Positive controls: the box runs, reads its tree and writes its scratch.
            assert outcome["scratch_write"] == "allowed"
            assert outcome["tree_read"] == "allowed"
            assert box.read_output("out.txt", 100) == b"pwned"
            # The boundary itself denies (access denied), not a missing path; loopback is
            # dropped (never refused by the live listener, which accepts nothing below).
            for name in ("repo_write", "repo_env_read", "sentinel_write", "profile_write"):
                assert outcome[name] == "denied:PermissionError", (name, outcome[name])
            assert outcome["loopback"] in ("denied:TimeoutError", "denied:PermissionError")
            facts = result.appcontainer
            assert facts.is_appcontainer and facts.job_verified
            assert facts.package_sid == box.package_sid and facts.capability_sids == ()
            assert result.boundary == "APPCONTAINER" and result.capabilities == ()
            listener.setblocking(False)
            with pytest.raises(BlockingIOError):
                listener.accept()  # the listener accepted nothing
            profile_name, container, run_id = box.profile_name, box.container, box.id
            first_digest = box.tree_digest
    finally:
        listener.close()
    assert not any(path.exists() for path in planted)

    _assert_box_gone(profile_name, container)
    assert [security_sddl(entry) for entry in entries] == acl_before
    from backend.app.execution.check_repository import CheckRunState

    assert boxes.repository.get(run_id).state is CheckRunState.CLEANED
    events = _events(database, change_id)
    assert [event["type"] for event in events] == ["check.confined_run"]
    assert events[0]["payload"]["boundary"] == "APPCONTAINER"
    assert events[0]["payload"]["tree_manifest_digest"] == first_digest
    assert events[0]["payload"]["exit_code"] == 0

    # The manifest digest is stable across two opens of the same tree.
    with boxes.open(change_id, repo, runtime) as again:
        assert again.tree_digest == first_digest
    _assert_box_gone(again.profile_name, again.container)


CRASHING_OPENER = r"""
import json, os, sys
from pathlib import Path
from uuid import UUID
from backend.app.core.database import Database
from backend.app.execution.check_box import BoxRuntime, CheckBoxes
from backend.app.execution.check_runtime import RuntimeSnapshot
config = json.loads(sys.argv[1])
boxes = CheckBoxes(Database(Path(config["db"])), profile_prefix=config["prefix"],
                   runtime_root=config["root"])
runtime = BoxRuntime(snapshots=tuple(RuntimeSnapshot(Path(path), digest, 0)
                                     for path, digest in config["snapshots"]))
box = boxes.open(UUID(config["change"]), config["repo"], runtime)
print(json.dumps({"id": str(box.id), "profile": box.profile_name, "sid": box.package_sid,
                  "container": str(box.container)}), flush=True)
os._exit(9)
"""


def test_sweep_cleans_a_box_whose_process_died_before_close(
    boxes, database, repo, cache_and_runtime,
) -> None:
    from backend.app.core.journal import JournalWriter
    from backend.app.execution.appcontainer import profile_exists
    from backend.app.execution.check_box import CheckBoxes
    from backend.app.execution.check_repository import CheckRunState

    cache, runtime = cache_and_runtime
    entries = [snapshot.path for snapshot in runtime.snapshots]
    acl_before = [security_sddl(entry) for entry in entries]
    config = {
        "db": str(database.path), "prefix": TEST_PROFILE_PREFIX, "root": str(cache),
        "repo": str(repo), "change": str(uuid4()),
        "snapshots": [[str(snapshot.path), snapshot.manifest_digest]
                      for snapshot in runtime.snapshots],
    }
    completed = subprocess.run(
        [sys.executable, "-c", CRASHING_OPENER, json.dumps(config)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert completed.returncode == 9, completed.stderr
    opened = json.loads(completed.stdout.strip().splitlines()[-1])
    run_id = UUID(opened["id"])
    container = Path(opened["container"])
    # The process died with the box still in place.
    assert profile_exists(opened["profile"])
    assert (container / "tree" / "calc.py").is_file()
    assert all(opened["sid"] in security_sddl(entry) for entry in entries)
    assert boxes.repository.get(run_id).state is CheckRunState.READY

    restarted = CheckBoxes(database, journal=JournalWriter(database),
                           profile_prefix=TEST_PROFILE_PREFIX, runtime_root=cache)
    report = restarted.sweep()
    assert report.cleaned == (run_id,) and report.failed == ()
    _assert_box_gone(opened["profile"], container)
    assert [security_sddl(entry) for entry in entries] == acl_before
    assert boxes.repository.get(run_id).state is CheckRunState.CLEANED
