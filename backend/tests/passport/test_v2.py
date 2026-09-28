"""V2 signatures bind stored Change, journal and launches, never caller bytes."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts.models import DiffCoverageResult, JournalEventType
from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.app.passport.cng import CngKey, verify_signature
from backend.app.passport.v2 import PassportV2Issuer, canonical_payload
from backend.app.assurance.store import EvidenceStore
from backend.app.git.state import GitStateTracker
from backend.tests.passport.test_builder import _database, _seed_change
from backend.tests.support_kb import make_repo, write


def _launch(database, change_id) -> str:
    run_id = uuid4()
    now = datetime.now(UTC).isoformat()
    payload = json.dumps({"id": str(run_id), "change_id": str(change_id),
                          "status": "SUCCEEDED", "output": "private output"})
    with database.connection() as connection:
        connection.execute(
            "INSERT INTO agent_runs (id, change_id, status, payload_json, started_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(run_id), str(change_id), "SUCCEEDED", payload, now),
        )
    JournalWriter(database).append(change_id, JournalEventType.AGENT_LAUNCHED,
                                   subject_type="agent_run", subject_id=run_id,
                                   payload={"adapter": "test", "executable": "test"})
    JournalWriter(database).append(change_id, JournalEventType.AGENT_COMPLETED,
                                   subject_type="agent_run", subject_id=run_id,
                                   payload={"status": "SUCCEEDED", "exit_code": 0})
    return str(run_id)


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_issue_uses_database_only_and_binds_journal_and_launch(tmp_path: Path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    event = JournalWriter(database).append(change.id, JournalEventType.PASSPORT_BUILT,
                                           payload={"source": "database"})
    run_id = _launch(database, change.id)
    key_name = f"Sentinel disposable test {uuid4()}"
    issuer = PassportV2Issuer(database, key_name=key_name, installation_label="Lab")
    try:
        issued = issuer.issue(change.id)
        assert issued.payload.journal_head != event.event_hash
        assert issued.payload.journal_event_count == 3
        assert issued.payload.journal_integrity == "PASS"
        assert [str(item.run_id) for item in issued.payload.launch_records] == [run_id]
        assert issued.payload.execution_boundary == "UNKNOWN"
        assert issued.payload.runs_later == "UNKNOWN"
        assert issued.signer_identity == "Sentinel installation Lab"
        assert "private output" not in issued.model_dump_json()
        spki = base64.b64decode(issued.signer_public_spki_b64)
        signature = base64.b64decode(issued.signature_b64)
        assert verify_signature(spki=spki, message=canonical_payload(issued.payload),
                                signature=signature)
        assert not verify_signature(spki=spki, message=canonical_payload(issued.payload) + b"!",
                                    signature=signature)
        with pytest.raises(TypeError):
            issuer.issue(change.id, {"forged": True})  # type: ignore[call-arg]
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


def test_tampered_journal_refuses_issue(tmp_path: Path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    event = JournalWriter(database).append(change.id, JournalEventType.PASSPORT_BUILT,
                                           payload={"source": "database"})
    with database.connection() as connection:
        connection.execute("DROP TRIGGER journal_events_immutable_update")
        connection.execute("UPDATE journal_events SET payload_json = ? WHERE id = ?",
                           ('{"source":"forged"}', str(event.id)))
    with pytest.raises(AppError, match="hash mismatch"):
        PassportV2Issuer(database).snapshot(change.id)


def test_launch_record_mutation_changes_bound_digest(tmp_path: Path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    run_id = _launch(database, change.id)
    issuer = PassportV2Issuer(database)
    first = issuer.snapshot(change.id).launch_records[0].record_digest
    with database.connection() as connection:
        raw = connection.execute("SELECT payload_json FROM agent_runs WHERE id = ?",
                                 (run_id,)).fetchone()["payload_json"]
        changed = json.loads(raw)
        changed["output"] = "altered"
        connection.execute("UPDATE agent_runs SET payload_json = ? WHERE id = ?",
                           (json.dumps(changed), run_id))
    second = issuer.snapshot(change.id).launch_records[0].record_digest
    assert first != second


def test_v2_rejects_missing_and_contradictory_launch_rows(tmp_path: Path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    run_id = _launch(database, change.id)
    issuer = PassportV2Issuer(database)
    with database.connection() as connection:
        connection.execute("UPDATE agent_runs SET status = 'FAILED' WHERE id = ?", (run_id,))
    with pytest.raises(AppError, match="Launch status differs"):
        issuer.snapshot(change.id)
    with database.connection() as connection:
        connection.execute("DELETE FROM agent_runs WHERE id = ?", (run_id,))
    with pytest.raises(AppError, match="Launch records and journal differ"):
        issuer.snapshot(change.id)


def test_http_rejects_caller_supplied_payload(tmp_path: Path) -> None:
    app = create_app(settings=Settings(database_path=tmp_path / "state.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        response = client.post(f"/api/v1/changes/{uuid4()}/passport/v2/issue",
                               json={"payload": {"checks_passed": True}})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PASSPORT_PAYLOAD_FORBIDDEN"


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_v2_issuer_signs_stale_after_repository_moves(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    database = _database(tmp_path)
    change = _seed_change(database)
    with database.connection() as connection:
        connection.execute("UPDATE changes SET repository_path = ? WHERE id = ?",
                           (str(root), str(change.id)))
    captured = GitStateTracker().capture(change.id, "measured", str(root), 1, 1_048_576)
    now = datetime.now(UTC)
    EvidenceStore(database).save_diff_coverage(DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=uuid4(), tested_checkpoint_id=uuid4(),
        head_sha=captured.head_sha, status_digest=captured.status_digest,
        contract_digest="c" * 64, started_at=now, completed_at=now,
        collector_status="COLLECTED", checks_passed=True, diff_exercised="PASS",
        freshness="CURRENT", changed_executable_lines=1, executed_changed_lines=1,
        measured_percent=100,
    ))
    write(root, "module.py", "VALUE = 2\n")
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        issued = PassportV2Issuer(database, key_name=key_name).issue(change.id)
        assert issued.payload.diff_coverage.freshness == "STALE"
        assert issued.payload.diff_coverage.diff_exercised == "STALE"
        assert verify_signature(spki=base64.b64decode(issued.signer_public_spki_b64),
                                message=canonical_payload(issued.payload),
                                signature=base64.b64decode(issued.signature_b64))
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()
