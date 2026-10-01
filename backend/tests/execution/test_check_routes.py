"""GET /api/v1/changes/{id}/checks and `sentinel checks list` (05-04).

The route reports the boundary each check run was observed to run under:
APPCONTAINER only when the row AND its journaled ``check.confined_run`` event
carry verified token facts; UNCONFINED for a delegated opt-in run (journal
event, no row); None for anything absent, mixed or unverifiable. Rows are
seeded directly so the negative cases are exact; one test drives a real
verification through the API on the host check-box harness (no containment).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from backend.app.cli import main as cli_main
from backend.app.cli.client import ApiClient
from backend.app.contracts.models import (
    DiffCoverageResult,
    JournalEventType,
    VerificationResult,
)
from backend.app.core.config import Settings
from backend.app.core.journal import JournalWriter
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.check_repository import (
    CheckRunRecord,
    CheckRunRepository,
    CheckRunState,
    RuntimeGrant,
)
from backend.app.main import create_app
from backend.tests.providers.fakes import FakeHttpTransport, json_response
from backend.tests import support_checks
from backend.tests.support_kb import make_repo

SID = "S-1-15-2-1-2-3-4-5-6-7"
TREE = "a" * 64
RUNTIME = "b" * 64
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _facts(**overrides):
    return {
        "profile_name": "sentinel.check.x", "package_sid": SID, "is_appcontainer": True,
        "integrity_rid": "0x1000", "capability_sids": [], "job_verified": True,
        "verified_at": "2026-10-01T12:00:00+00:00", **overrides,
    }


def _event_payload(run_id: UUID, **overrides):
    return {
        "check_run_id": str(run_id), "profile_name": "sentinel.check.x", "package_sid": SID,
        "is_appcontainer": True, "integrity_rid": "0x1000", "job_verified": True,
        "capabilities": [], "capability_sids": [], "network": False,
        "argv_sha256": "c" * 64, "tree_manifest_digest": TREE,
        "runtime_manifest_digests": [RUNTIME], "exit_code": 0, "timed_out": False,
        "boundary": "APPCONTAINER", **overrides,
    }


@pytest.fixture
def api(tmp_path: Path):
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    with client:
        yield app, client


def _change(client: TestClient, repo: Path) -> str:
    created = client.post("/api/v1/changes", json={
        "title": "checks", "intent": "list check runs", "repository_path": str(repo)})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "user-repo", {"calc.py": "def add(a, b):\n    return a + b\n"})


def _seed_row(app, change_id: str, *, facts=None, state=CheckRunState.CLEANED,
              event: dict | None | bool = True) -> UUID:
    run_id = uuid4()
    CheckRunRepository(app.state.database).insert(CheckRunRecord(
        id=run_id, change_id=UUID(change_id), profile_name=f"sentinel.check.{run_id}",
        package_sid=SID, state=state, network=False,
        runtime_grants=(RuntimeGrant("C:\\cache\\py", RUNTIME),),
        created_at=NOW, updated_at=NOW, tree_digest=TREE, facts=facts,
        exit_code=0, timed_out=False,
    ))
    if event is not False and event is not None:
        payload = _event_payload(run_id) if event is True else event | {
            "check_run_id": str(run_id)}
        JournalWriter(app.state.database).append(
            UUID(change_id), JournalEventType.CHECK_CONFINED_RUN, subject_type="check_run",
            subject_id=run_id, payload=payload)
    return run_id


def test_route_lists_verified_box_runs_without_argv_or_output(api, tmp_path) -> None:
    app, client = api
    change_id = _change(client, _repo(tmp_path))
    run_id = _seed_row(app, change_id, facts=_facts())

    response = client.get(f"/api/v1/changes/{change_id}/checks")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["id"] == str(run_id)
    assert item["state"] == "CLEANED"
    assert item["boundary"] == "APPCONTAINER"
    assert item["network"] is False
    assert item["tree_digest"] == TREE
    assert item["runtime_manifest_digests"] == [RUNTIME]
    assert item["exit_code"] == 0 and item["timed_out"] is False
    assert item["token"]["is_appcontainer"] is True and item["token"]["job_verified"] is True
    assert item["token"]["package_sid"] == SID
    text = response.text
    for forbidden in ("argv", "stdout", "stderr", "C:\\\\cache"):
        assert forbidden not in text


def test_unverified_or_unjournaled_rows_never_read_appcontainer(api, tmp_path) -> None:
    app, client = api
    change_id = _change(client, _repo(tmp_path))
    no_event = _seed_row(app, change_id, facts=_facts(), event=False)
    not_appcontainer = _seed_row(app, change_id, facts=_facts(is_appcontainer=False))
    job_unverified = _seed_row(app, change_id, facts=_facts(job_verified=False))
    never_ran = _seed_row(app, change_id, facts=None, state=CheckRunState.FINISHED, event=False)
    event_mismatch = _seed_row(app, change_id, facts=_facts(),
                               event=_event_payload(uuid4(), job_verified=False))

    items = {item["id"]: item for item in
             client.get(f"/api/v1/changes/{change_id}/checks").json()["items"]}
    for run_id in (no_event, not_appcontainer, job_unverified, never_ran, event_mismatch):
        assert items[str(run_id)]["boundary"] is None, run_id
    assert items[str(never_ran)]["token"] is None


def test_unconfined_opt_in_runs_are_listed_as_unconfined(api, tmp_path) -> None:
    app, client = api
    change_id = _change(client, _repo(tmp_path))
    run_id = uuid4()
    JournalWriter(app.state.database).append(
        UUID(change_id), JournalEventType.CHECK_UNCONFINED_RUN, subject_type="check_run",
        subject_id=run_id, payload={
            "check_run_id": str(run_id), "executable": "cargo", "argv_sha256": "d" * 64,
            "exit_code": 3, "timed_out": False, "boundary": "UNCONFINED"})

    body = client.get(f"/api/v1/changes/{change_id}/checks").json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item == {**item, "id": str(run_id), "boundary": "UNCONFINED", "state": "FINISHED",
                    "exit_code": 3, "timed_out": False, "token": None}


def test_an_unconfined_intent_and_its_outcome_list_as_one_run(api, tmp_path) -> None:
    """WR-01: the intent event alone (a run that may have executed) is listed as STARTED."""

    app, client = api
    change_id = _change(client, _repo(tmp_path))
    journal = JournalWriter(app.state.database)
    crashed, finished = uuid4(), uuid4()
    for run_id, phases in ((crashed, ["started"]), (finished, ["started", "finished"])):
        for phase in phases:
            journal.append(
                UUID(change_id), JournalEventType.CHECK_UNCONFINED_RUN, subject_type="check_run",
                subject_id=run_id, payload={
                    "check_run_id": str(run_id), "executable": "cargo", "argv_sha256": "d" * 64,
                    "phase": phase, "exit_code": 0 if phase == "finished" else None,
                    "timed_out": False if phase == "finished" else None,
                    "boundary": "UNCONFINED"})
    items = {item["id"]: item
             for item in client.get(f"/api/v1/changes/{change_id}/checks").json()["items"]}
    assert set(items) == {str(crashed), str(finished)}
    assert items[str(crashed)]["state"] == "STARTED"
    assert items[str(crashed)]["exit_code"] is None
    assert items[str(finished)]["state"] == "FINISHED"
    assert items[str(finished)]["exit_code"] == 0
    assert {item["boundary"] for item in items.values()} == {"UNCONFINED"}


def test_unknown_change_is_404_and_the_route_requires_the_token(api) -> None:
    app, client = api
    missing = client.get("/api/v1/changes/00000000-0000-0000-0000-000000000000/checks")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CHANGE_NOT_FOUND"
    anonymous = TestClient(app).get(
        "/api/v1/changes/00000000-0000-0000-0000-000000000000/checks")
    assert anonymous.status_code == 401


def test_route_is_read_only_get_in_the_schema(api) -> None:
    app, _client = api
    operations = app.openapi()["paths"]["/api/v1/changes/{change_id}/checks"]
    assert set(operations) == {"get"}


def _verify(client: TestClient, change_id: str) -> dict:
    actor = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "O"}).json()
    grantor = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "G"}).json()
    client.post("/api/v1/delegations", json={
        "grantor_id": grantor["id"], "grantee_id": actor["id"], "change_id": change_id,
        "scopes": ["change.legacy_verify"], "ttl_seconds": 3600})
    verified = client.post(f"/api/v1/changes/{change_id}/verify", json={
        "actor_id": actor["id"],
        "verification": {"executable": "python", "args": ["-c", "print(1)"],
                         "timeout_seconds": 60}})
    assert verified.status_code == 200, verified.text
    return verified.json()["verification"]


def test_unverified_harness_facts_are_never_reported_as_appcontainer(api, tmp_path) -> None:
    """The host harness reports is_appcontainer=False: neither surface may claim the box."""

    _app, client = api
    change_id = _change(client, _repo(tmp_path))
    result = _verify(client, change_id)
    assert result["check_run_id"] is not None
    assert result["boundary"] is None
    items = client.get(f"/api/v1/changes/{change_id}/checks").json()["items"]
    assert [item["id"] for item in items] == [result["check_run_id"]]
    assert items[0]["boundary"] is None
    assert items[0]["token"]["is_appcontainer"] is False


@pytest.fixture
def verified_harness(monkeypatch):
    """Host child whose facts are forced verified (must run before ``api`` builds the app)."""

    original = support_checks.HostBoxWindows.spawn

    def verified_spawn(self, *args, **kwargs):
        process = original(self, *args, **kwargs)
        process.appcontainer = replace(process.appcontainer, is_appcontainer=True,
                                       job_verified=True, integrity_rid=0x1000)
        return process

    monkeypatch.setattr(support_checks.HostBoxWindows, "spawn", verified_spawn)


def test_verified_box_run_flows_to_result_and_route(verified_harness, api, tmp_path) -> None:
    """Plumbing only (host child with facts forced verified; no containment is proven)."""

    _app, client = api
    change_id = _change(client, _repo(tmp_path))
    result = _verify(client, change_id)
    assert result["boundary"] == "APPCONTAINER"
    items = client.get(f"/api/v1/changes/{change_id}/checks").json()["items"]
    assert [item["id"] for item in items] == [result["check_run_id"]]
    assert items[0]["boundary"] == "APPCONTAINER"
    assert items[0]["state"] == "CLEANED"


def test_legacy_results_without_the_new_fields_still_validate() -> None:
    legacy = {"executable": "pytest", "args": [], "status": "PASSED", "exit_code": 0,
              "duration_ms": 1, "stdout": "", "stderr": "",
              "started_at": "2026-01-01T00:00:00+00:00",
              "completed_at": "2026-01-01T00:00:00+00:00"}
    result = VerificationResult.model_validate(legacy)
    assert result.check_run_id is None and result.boundary is None
    coverage = DiffCoverageResult.model_validate({
        "change_id": str(uuid4()), "baseline_checkpoint_id": str(uuid4()),
        "tested_checkpoint_id": str(uuid4()), "head_sha": "a" * 40,
        "status_digest": "b" * 64, "contract_digest": "c" * 64,
        "started_at": "2026-01-01T00:00:00+00:00", "completed_at": "2026-01-01T00:00:00+00:00",
        "collector_status": "COLLECTED", "diff_exercised": "PASS", "freshness": "CURRENT",
        "collection_boundary": "UNCONFINED_IN_PROCESS"})
    assert coverage.check_run_id is None and coverage.boundary is None
    with pytest.raises(ValueError):
        VerificationResult.model_validate({**legacy, "boundary": "CONFINED"})


def test_cli_checks_list_gets_the_route(monkeypatch) -> None:
    change = "00000000-0000-0000-0000-000000000001"
    transport = FakeHttpTransport([json_response(200, {"items": [], "count": 0})])
    monkeypatch.setattr(cli_main, "ApiClient",
                        lambda api_url: ApiClient(api_url, transport=transport))
    result = CliRunner().invoke(cli_main.app, ["checks", "list", change, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"items": [], "count": 0}
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == f"http://127.0.0.1:8000/api/v1/changes/{change}/checks"
