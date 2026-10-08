"""Plan 02-03: the signed execution_boundary claim is derived only from bound launch facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.assurance.service import EvidenceService
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (AgentAttachRequest, AgentLaunchRequest, AgentRun,
                                          ExecutionBoundary)
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.passport.v2 import PassportV2Issuer
from backend.tests.passport.test_builder import _database, _seed_change

BOX = ExecutionBoundary(kind="APPCONTAINER", profile="sentinel.w.abc",
                        capabilities=["internetClient"], package_sid="S-1-15-2-1-2-3",
                        integrity_rid="0x1000", job_verified=True,
                        verified_at=datetime(2026, 10, 8, tzinfo=UTC), workspace_drive="Z:")
REDUCED = ExecutionBoundary(kind="RESTRICTED_TOKEN", profile="generic", job_verified=True)


class FakeLauncher:
    on_update = None

    def __init__(self, runs: list[tuple[str, ExecutionBoundary | None, int | None]]) -> None:
        self._runs = list(runs)

    def launch(self, change_id, repository_path, request, output_limit_bytes):
        status, boundary, pid = self._runs.pop(0)
        now = datetime.now(UTC)
        return AgentRun(id=uuid4(), change_id=change_id, adapter=request.adapter,
                        status=status, top_level_pid=pid, exit_code=0 if pid else None,
                        started_at=now, completed_at=now, execution_boundary=boundary)

    def attach(self, change_id, request):
        from backend.app.execution.launcher import AgentLauncher

        return AgentLauncher().attach(change_id, request)


def _snapshot(tmp_path: Path, runs, *, attach: bool = False):
    database = _database(tmp_path)
    change = _seed_change(database)
    service = EvidenceService(EvidenceStore(database), launcher=FakeLauncher(runs),
                              journal=JournalWriter(database))
    for _ in runs:
        service.launch_agent(change, AgentLaunchRequest(adapter="claude", executable="claude"))
    if attach:
        service.attach_agent(change, AgentAttachRequest(adapter="claude", external_run_id="x"))
    return database, change, PassportV2Issuer(database).snapshot(change.id)


@pytest.mark.parametrize(("runs", "attach", "expected"), [
    ([("PASSED", BOX, 10)], False, "APPCONTAINER"),
    ([("PASSED", BOX, 10), ("FAILED", BOX, 11)], False, "APPCONTAINER"),
    ([("PASSED", REDUCED, 10)], False, "RESTRICTED_TOKEN_ONLY"),
    ([("PASSED", BOX, 10), ("PASSED", REDUCED, 11)], False, "MIXED"),
    ([("PASSED", BOX, 10)], True, "MIXED"),
    ([], True, "NONE"),
    ([], False, "UNKNOWN"),
    # A launch that failed before any process started ran no agent code.
    ([("ERROR", None, None), ("PASSED", BOX, 10)], False, "APPCONTAINER"),
    # A run that started but recorded no boundary (legacy) cannot be claimed.
    ([("PASSED", None, 10), ("PASSED", BOX, 11)], False, "UNKNOWN"),
    ([("PASSED", BOX.model_copy(update={"job_verified": False}), 10)], False, "UNKNOWN"),
])
def test_claim_is_appcontainer_only_when_every_started_run_verified_it(
        tmp_path: Path, runs, attach: bool, expected: str) -> None:
    _, _, payload = _snapshot(tmp_path, runs, attach=attach)
    assert payload.execution_boundary == expected
    boundary_lines = [line for line in payload.limitations
                      if "boundar" in line or "reduced token" in line]
    if expected == "APPCONTAINER":
        assert boundary_lines == []
    else:
        assert len(boundary_lines) == 1, payload.limitations


def test_the_journal_records_the_boundary_and_an_argv_digest(tmp_path: Path) -> None:
    database, change, _ = _snapshot(tmp_path, [("PASSED", BOX, 10)])
    with database.connection() as connection:
        row = connection.execute(
            "SELECT payload_json FROM journal_events WHERE change_id = ? AND event_type = ?",
            (str(change.id), "agent.launched")).fetchone()
    payload = json.loads(row["payload_json"])
    assert payload["boundary"]["kind"] == "APPCONTAINER"
    assert payload["boundary"]["workspace_drive"] == "Z:"
    assert len(payload["argv_sha256"]) == 64


def test_a_record_boundary_edited_after_the_journal_is_refused(tmp_path: Path) -> None:
    database, change, _ = _snapshot(tmp_path, [("PASSED", REDUCED, 10)])
    with database.connection() as connection:
        row = connection.execute("SELECT id, payload_json FROM agent_runs WHERE change_id = ?",
                                 (str(change.id),)).fetchone()
        forged = json.loads(row["payload_json"])
        forged["execution_boundary"] = BOX.model_dump(mode="json")
        connection.execute("UPDATE agent_runs SET payload_json = ? WHERE id = ?",
                           (json.dumps(forged), row["id"]))
    with pytest.raises(AppError) as raised:
        PassportV2Issuer(database).snapshot(change.id)
    assert raised.value.code == "PASSPORT_LAUNCH_INVALID"
