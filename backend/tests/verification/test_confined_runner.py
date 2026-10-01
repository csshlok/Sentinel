"""Both verification runners run through a check box; the unconfined path needs a delegation.

The harness tests (host 'box', see ``support_checks``) prove routing, boundary
facts, journaling and the opt-in. The ``real`` test proves containment with a
real ``sentinel.test.*`` AppContainer box and the snapshot python, with a
positive control that runs the same probe on the host.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts.models import (
    ChangeContract,
    VerificationRequest,
    VerificationStatus,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.execution.runner import BoundedVerificationRunner
from backend.app.verification.runner import SubprocessVerificationRunner
from backend.tests.support_checks import host_check_boxes
from backend.tests.support_kb import make_repo, write

RUNNERS = [SubprocessVerificationRunner, BoundedVerificationRunner]


def _make_change(database: Database, repo: Path, **contract) -> UUID:
    now = datetime.now(UTC)
    change_id = uuid4()
    ChangeRepository(database).create(StoredChange(
        id=change_id, title="Confined runner", intent="Exercise the confined runners",
        repository_path=str(repo), created_at=now, updated_at=now, last_refreshed_at=None,
        git_summary=None, verification=None, contract=ChangeContract(**contract),
    ))
    return change_id


def _events(database: Database, change_id: UUID) -> list[dict]:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT event_type, subject_id, payload_json FROM journal_events "
            "WHERE change_id = ? ORDER BY seq", (str(change_id),),
        ).fetchall()
    return [{"type": row["event_type"], "subject_id": row["subject_id"],
             "payload": json.loads(row["payload_json"])} for row in rows]


@pytest.fixture
def setup(tmp_path):
    repo = make_repo(tmp_path / "repo", {"calc.py": "VALUE = 2\n", ".gitignore": ".env\n"})
    write(repo, ".env", "SECRET=canary\n")
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    boxes, windows = host_check_boxes(tmp_path / "boxes", database)
    return repo, database, boxes, windows


# ---------------------------------------------------------------------- harness


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_runner_goes_through_a_box_and_reports_its_boundary(setup, runner_type) -> None:
    repo, database, boxes, windows = setup
    change_id = _make_change(database, repo)
    request = VerificationRequest(executable="python", args=[
        "-c", "import calc, os; print(calc.VALUE, os.path.exists('.env'))"])
    checked = runner_type(boxes).run_checked(str(repo), request, 4096, change_id=change_id)
    assert checked.result.status is VerificationStatus.PASSED
    # The tree is the repository copy: tracked code present, the ignored .env absent.
    assert checked.result.stdout.split() == ["2", "False"]
    # 05-04: the host harness reports unverified token facts (is_appcontainer=False), so
    # neither the runner nor the contract result may claim the box boundary.
    assert checked.boundary is None
    assert checked.result.boundary is None
    assert checked.result.check_run_id == checked.check_run_id
    record = boxes.repository.get(checked.check_run_id)
    assert record is not None and record.state.value == "CLEANED"
    assert windows.spawned[0]["cwd"].name == "tree"
    confined = [e for e in _events(database, change_id) if e["type"] == "check.confined_run"]
    assert len(confined) == 1
    assert confined[0]["subject_id"] == str(checked.check_run_id)
    assert confined[0]["payload"]["boundary"] == "APPCONTAINER"


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_port_run_keeps_returning_a_plain_verification_result(setup, runner_type) -> None:
    repo, database, boxes, _ = setup
    result = runner_type(boxes).run(str(repo), VerificationRequest(
        executable="python", args=["-c", "print(1)"]), 4096, change_id=_make_change(database, repo))
    assert result.status is VerificationStatus.PASSED and result.stdout.strip() == "1"


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_a_confined_run_needs_a_change_and_a_box_manager(setup, runner_type) -> None:
    repo, database, boxes, windows = setup
    request = VerificationRequest(executable="python", args=["-c", "print(1)"])
    with pytest.raises(AppError) as error:
        runner_type(boxes).run(str(repo), request, 100)
    assert error.value.code == "CHECK_CHANGE_REQUIRED"
    with pytest.raises(AppError) as error:
        runner_type().run(str(repo), request, 100, change_id=uuid4())
    assert error.value.code == "CHECK_RUNTIME_UNAVAILABLE"
    assert windows.spawned == []
    assert boxes.repository.list_unclean() == []


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_unconfined_toolchain_needs_the_opt_in(setup, runner_type) -> None:
    repo, database, boxes, windows = setup
    with pytest.raises(AppError) as error:
        runner_type(boxes).run(str(repo), VerificationRequest(executable="cargo", args=["test"]),
                               100, change_id=_make_change(database, repo))
    assert error.value.code == "CHECK_TOOLCHAIN_UNCONFINED"
    assert windows.spawned == []


def _host_python_as(monkeypatch, runner_type) -> None:
    """Make the unconfined resolver return this interpreter for 'cargo' (no cargo needed)."""

    if runner_type is SubprocessVerificationRunner:
        monkeypatch.setattr("backend.app.verification.runner.resolve_executable",
                            lambda request: sys.executable)
    else:
        monkeypatch.setattr("backend.app.execution.runner._resolve",
                            lambda name, root, env: sys.executable)


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_opted_in_unconfined_run_is_journaled_as_unconfined(setup, runner_type,
                                                             monkeypatch) -> None:
    repo, database, boxes, windows = setup
    change_id = _make_change(database, repo)
    _host_python_as(monkeypatch, runner_type)
    checked = runner_type(boxes).run_checked(
        str(repo), VerificationRequest(executable="cargo", args=[
            "-c", "import os; print(os.getcwd())"]),
        4096, change_id=change_id, allow_unconfined=True)
    assert checked.result.status is VerificationStatus.PASSED
    # Honest: an unconfined run really runs in the user repository, at user authority.
    assert Path(checked.result.stdout.strip()).resolve() == repo.resolve()
    assert checked.boundary == "UNCONFINED"
    assert windows.spawned == []  # no box was used
    assert boxes.repository.for_change(change_id) == []
    events = [e for e in _events(database, change_id) if e["type"].startswith("check.")]
    assert [e["type"] for e in events] == ["check.unconfined_run", "check.unconfined_run"]
    assert [e["payload"]["phase"] for e in events] == ["started", "finished"]
    for event in events:
        payload = event["payload"]
        assert payload["boundary"] == "UNCONFINED"
        assert payload["executable"] == "cargo"
        assert payload["check_run_id"] == str(checked.check_run_id)
        assert "print" not in json.dumps(payload)  # digests only, never argv text
    assert events[1]["payload"]["exit_code"] == 0


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_unconfined_intent_is_journaled_before_the_command_runs(setup, runner_type,
                                                                 monkeypatch) -> None:
    """WR-01: a crash after an unconfined run starts still leaves it on record."""

    from backend.app.execution.check_repository import (
        CheckRunRepository,
        confined_checks_fact,
    )

    repo, database, boxes, _ = setup
    change_id = _make_change(database, repo)
    _host_python_as(monkeypatch, runner_type)
    seen_at_start: list[list[dict]] = []

    def crashing_run(argv, **_kwargs):
        seen_at_start.append(_events(database, change_id))
        raise RuntimeError("the server died while the check ran")

    monkeypatch.setattr("backend.app.execution.commands.run_verification_command", crashing_run)
    with pytest.raises(RuntimeError):
        runner_type(boxes).run_checked(
            str(repo), VerificationRequest(executable="cargo", args=["test"]),
            4096, change_id=change_id, allow_unconfined=True)
    assert [[(e["type"], e["payload"]["phase"]) for e in events]
            for events in seen_at_start] == [[("check.unconfined_run", "started")]]
    # The intent alone makes the Change's confined_checks FAIL.
    events = CheckRunRepository(database).events_for_change(change_id)
    assert confined_checks_fact([], records={}, events=events)[0] == "FAIL"


@pytest.mark.parametrize("runner_type", RUNNERS)
def test_a_failed_intent_append_runs_nothing(setup, runner_type, monkeypatch) -> None:
    repo, database, boxes, _ = setup
    change_id = _make_change(database, repo)
    _host_python_as(monkeypatch, runner_type)
    ran: list[object] = []
    monkeypatch.setattr("backend.app.execution.commands.run_verification_command",
                        lambda argv, **_kwargs: ran.append(argv))

    def refuse(*_args, **_kwargs):
        raise AppError("JOURNAL_APPEND_FAILED", "the journal is locked", status_code=503)

    monkeypatch.setattr(boxes, "record_unconfined_run", refuse)
    with pytest.raises(AppError) as error:
        runner_type(boxes).run_checked(
            str(repo), VerificationRequest(executable="cargo", args=["test"]),
            4096, change_id=change_id, allow_unconfined=True)
    assert error.value.code == "JOURNAL_APPEND_FAILED"
    assert ran == []


# ---------------------------------------------------------------------- API opt-in


def _client_change(client, repo: Path, *, max_risk: str = "MEDIUM") -> str:
    response = client.post("/api/v1/changes", json={
        "title": "Unconfined opt-in", "intent": "Run cargo", "repository_path": str(repo),
        "contract": {"max_risk": max_risk},
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _actor(client, change_id: str, scopes: list[str]) -> str:
    actor = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "A"}).json()["id"]
    grantor = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "G"}).json()["id"]
    response = client.post("/api/v1/delegations", json={
        "grantor_id": grantor, "grantee_id": actor, "change_id": change_id,
        "scopes": scopes, "ttl_seconds": 3600})
    assert response.status_code == 201, response.text
    return actor


def _verify(client, change_id: str, actor: str, executable: str, args: list[str]):
    return client.post(f"/api/v1/changes/{change_id}/verify", json={
        "actor_id": actor,
        "verification": {"executable": executable, "args": args, "timeout_seconds": 30}})


def test_api_unconfined_toolchain_requires_the_delegated_scope(tmp_path, monkeypatch) -> None:
    repo = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})
    _host_python_as(monkeypatch, SubprocessVerificationRunner)
    app = create_test_app(tmp_path)
    with TestClient(app, headers={"Authorization": f"Bearer {app.state.api_token}"}) as client:
        # High-risk Change, but the actor lacks checks.unconfined: refused before running.
        change_id = _client_change(client, repo, max_risk="HIGH")
        actor = _actor(client, change_id, ["change.legacy_verify"])
        response = _verify(client, change_id, actor, "cargo", ["-c", "print('ran')"])
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CHECK_TOOLCHAIN_UNCONFINED"

        # Delegated, but the Change admits only MEDIUM risk: still refused.
        low = _client_change(client, repo)
        actor = _actor(client, low, ["change.legacy_verify", "checks.unconfined"])
        response = _verify(client, low, actor, "cargo", ["-c", "print('ran')"])
        assert response.status_code == 409
        assert response.json()["error"]["details"]["policy_reason"] == "RISK_TOO_HIGH"

        # Delegated on a HIGH-risk Change: runs, journaled UNCONFINED.
        actor = _actor(client, change_id, ["change.legacy_verify", "checks.unconfined"])
        response = _verify(client, change_id, actor, "cargo", ["-c", "print('ran')"])
        assert response.status_code == 200, response.text
        assert response.json()["verification"]["status"] == "PASSED"
        database = app.state.check_boxes.repository.database
        types = [e["type"] for e in _events(database, UUID(change_id))]
        assert "check.unconfined_run" in types
        assert "check.confined_run" not in types

        # A confined toolchain needs no extra scope and is journaled confined.
        response = _verify(client, change_id, actor, "python",
                           ["-c", "import app; print(app.VALUE)"])
        assert response.status_code == 200, response.text
        assert response.json()["verification"]["stdout"].strip() == "1"
        types = [e["type"] for e in _events(database, UUID(change_id))]
        assert "check.confined_run" in types


def test_api_verify_refuses_while_the_workspace_holds_unapplied_work(
    tmp_path, monkeypatch,
) -> None:
    """WR-06: no check runs over the untouched base tree while agent work is unapplied."""

    from backend.app.workspace.manager import WorkspaceManager

    repo = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})
    unapplied: set[str] = set()
    monkeypatch.setattr(WorkspaceManager, "unapplied_work",
                        lambda self, change_id: str(change_id) in unapplied)
    app = create_test_app(tmp_path)
    assert app.state.check_boxes._evidence_guard is not None  # the production wiring
    with TestClient(app, headers={"Authorization": f"Bearer {app.state.api_token}"}) as client:
        change_id = _client_change(client, repo)
        actor = _actor(client, change_id, ["change.legacy_verify"])
        unapplied.add(change_id)
        response = _verify(client, change_id, actor, "python", ["-c", "print('ran')"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "WORKSPACE_NOT_APPLIED"
        assert client.get(f"/api/v1/changes/{change_id}/checks").json()["items"] == []
        # Once the work is applied (or discarded), the same check runs.
        unapplied.clear()
        response = _verify(client, change_id, actor, "python", ["-c", "print('ran')"])
        assert response.status_code == 200, response.text


def test_a_box_is_never_opened_while_the_workspace_holds_unapplied_work(tmp_path) -> None:
    """WR-06: the guard sits in CheckBoxes.open, so every caller of a box is covered."""

    repo = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    boxes, windows = host_check_boxes(tmp_path / "boxes", database,
                                      evidence_guard=lambda change_id: True)
    change_id = _make_change(database, repo)
    with pytest.raises(AppError) as error:
        SubprocessVerificationRunner(boxes).run(
            str(repo), VerificationRequest(executable="python", args=["-c", "print(1)"]),
            4096, change_id=change_id)
    assert error.value.code == "WORKSPACE_NOT_APPLIED"
    assert windows.spawned == [] and boxes.repository.for_change(change_id) == []


def create_test_app(tmp_path: Path):
    from backend.app.main import create_app

    return create_app(settings=Settings(database_path=tmp_path / "api.sqlite3"))


# ---------------------------------------------------------------------- real boundary

PROBE = r"""
import json, os, sys
target = sys.argv[1]
result = {"cwd": os.getcwd()}
try:
    with open(os.path.join(target, "escaped.txt"), "w") as handle:
        handle.write("escaped")
    result["write"] = "allowed"
except Exception as exc:
    result["write"] = "denied:" + type(exc).__name__
try:
    with open(os.path.join(target, ".env")) as handle:
        handle.read()
    result["read_env"] = "allowed"
except Exception as exc:
    result["read_env"] = "denied:" + type(exc).__name__
print(json.dumps(result))
"""


if IS_WINDOWS:
    from backend.tests.workspace.conftest import (
        HOSTED_RUNNER_APPCONTAINER_GAP,
        delete_test_profiles,
    )
else:  # pragma: no cover - the real boundary is Windows-only
    HOSTED_RUNNER_APPCONTAINER_GAP = pytest.mark.skip(reason="AppContainers are Windows-only")

    def delete_test_profiles():
        return []


@pytest.fixture(scope="module")
def real_cache(tmp_path_factory):
    cache = tmp_path_factory.mktemp("confined-runner-real") / "check-runtimes"
    try:
        yield cache
    finally:
        delete_test_profiles()
        shutil.rmtree(cache, ignore_errors=True)


@pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")
@HOSTED_RUNNER_APPCONTAINER_GAP
def test_real_verification_runs_contained(tmp_path, real_cache) -> None:
    from backend.app.core.journal import JournalWriter
    from backend.app.execution.check_box import CheckBoxes

    repo = make_repo(tmp_path / "user-repo", {"calc.py": "VALUE = 2\n", ".gitignore": ".env\n"})
    write(repo, ".env", "SECRET=canary-confined-runner\n")

    # Positive control: the same probe at user authority reaches the repository.
    control = subprocess.run([sys.executable, "-c", PROBE, str(repo)], capture_output=True,
                             text=True, timeout=60, cwd=tmp_path, check=True)
    assert json.loads(control.stdout) | {"cwd": None} == {
        "cwd": None, "write": "allowed", "read_env": "allowed"}
    (repo / "escaped.txt").unlink()

    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    boxes = CheckBoxes(database, journal=JournalWriter(database),
                       profile_prefix="sentinel.test.", runtime_root=real_cache)
    change_id = _make_change(database, repo)
    try:
        checked = SubprocessVerificationRunner(boxes).run_checked(
            str(repo), VerificationRequest(executable="python", args=["-c", PROBE, str(repo)],
                                           timeout_seconds=120),
            65536, change_id=change_id)
    finally:
        boxes.sweep(live_run_ids=())
    assert checked.result.status is VerificationStatus.PASSED, checked.result.stderr
    probe = json.loads(checked.result.stdout)
    assert probe["write"].startswith("denied:")
    assert probe["read_env"].startswith("denied:")
    assert Path(probe["cwd"]).name == "tree"
    assert not (repo / "escaped.txt").exists()
    assert checked.boundary == "APPCONTAINER"
    assert checked.result.boundary == "APPCONTAINER"  # verified real box run (05-04)
    assert checked.result.check_run_id == checked.check_run_id
    confined = [e for e in _events(database, change_id) if e["type"] == "check.confined_run"]
    assert len(confined) == 1
    assert confined[0]["payload"]["is_appcontainer"] is True
    assert confined[0]["payload"]["job_verified"] is True
    assert confined[0]["payload"]["boundary"] == "APPCONTAINER"
    assert boxes.repository.get(checked.check_run_id).state.value == "CLEANED"
    assert not os.path.lexists(tmp_path / "escaped.txt")
