"""J1: real-boundary tests for [KB]-owned Event/Effect Journal emission.

Drives a full baseline -> launch -> current -> plan -> run flow through the
real `EvidenceService` (real SQLite, a real disposable Git repository, a real
subprocess launch) and asserts every KB-owned mutation produced exactly one
well-formed, correctly-chained journal event with the right `event_type` and
`subject_id`, matching this codebase's real-boundary testing bar
(`backend/tests/kb_flow`).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.assurance.service import EvidenceService
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (
    AgentAttachRequest, AgentLaunchRequest, AssuranceStatus, ChangeContract, ChangeView,
    JournalEventType, ReviewState, RiskLevel,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.journal import JournalWriter, compute_event_hash
from backend.app.environment.tracker import EnvironmentTracker
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.support_kb import make_repo

NOW = datetime(2026, 1, 1, tzinfo=UTC)
FILES = {
    "pyproject.toml": '[project]\nname = "d"\ndependencies = ["flask==2.0.0"]\n'
                      "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
    "requirements.txt": "flask==2.0.0\n",
    "app.py": "def add(a, b):\n    return a + b\n",
    "tests/test_app.py": "from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}
EDIT = ("import pathlib\n"
        "pathlib.Path('app.py').write_text('def add(a, b):\\n    return b + a\\n')\n"
        "pathlib.Path('requirements.txt').write_text('flask==3.0.0\\n')\nprint('done')\n")
# `execution/resolve.py` deliberately resolves "python"/"python3" to
# `sys.executable` -- the same interpreter running this process -- rather
# than a PATH search, so the launched agent can't silently be a different
# Python than expected. That is the right call for the product, but a
# Windows venv's own `python.exe` is commonly a launcher stub that spawns
# the real interpreter as a *child* and waits on it (real CPython
# behaviour, not specific to any one install), which the tests below would
# otherwise see as unexpected descendants. Point `sys.executable` at the
# real, unwrapped interpreter for the duration of these tests instead of
# passing a path as `executable` (the launcher's adapter allowlist only
# accepts the bare names "python"/"python3", by design -- see
# `AgentLauncher.launch`'s `_normalize` check).
REAL_PYTHON = getattr(sys, "_base_executable", sys.executable)


class Harness:
    def __init__(self, tmp_path, **contract):
        self.db = Database(tmp_path / "state" / "db.sqlite3")
        self.db.initialize()
        self.repo = make_repo(tmp_path / "repo", FILES)
        self.change_id = uuid4()
        self.contract = ChangeContract(**contract)
        ChangeRepository(self.db).create(StoredChange(
            id=self.change_id, title="t", intent="i", repository_path=str(self.repo),
            created_at=NOW, updated_at=NOW, last_refreshed_at=None, git_summary=None,
            verification=None, contract=self.contract))
        self.journal = JournalWriter(self.db)

    def view(self, revision: int = 0) -> ChangeView:
        return ChangeView(id=self.change_id, title="t", intent="i", repository_path=str(self.repo),
                          created_at=NOW, updated_at=NOW, review_state=ReviewState.NO_CHANGES,
                          risk_level=RiskLevel.LOW, contract=self.contract, evidence_revision=revision)

    def service(self) -> EvidenceService:
        return EvidenceService(
            EvidenceStore(self.db), journal=self.journal,
            environment=EnvironmentTracker(tools={"python": ["--version"]}))

    def events(self) -> list:
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM journal_events WHERE change_id = ? ORDER BY seq",
                (str(self.change_id),),
            ).fetchall()
        from backend.app.core.journal import row_to_event
        return [row_to_event(row) for row in rows]


def _assert_chain_valid(events: list) -> None:
    prev_hash = None
    for index, event in enumerate(events):
        assert event.seq == index + 1
        assert event.prev_event_hash == prev_hash
        expected = compute_event_hash(
            prev_event_hash=prev_hash, seq=event.seq, change_id=event.change_id,
            event_type=event.event_type.value, actor_id=event.actor_id,
            subject_type=event.subject_type, subject_id=event.subject_id,
            payload=event.payload, occurred_at=event.occurred_at,
            schema_version=event.schema_version,
        )
        assert expected == event.event_hash
        prev_hash = event.event_hash


def test_full_evidence_flow_produces_a_correctly_chained_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", REAL_PYTHON)
    h = Harness(tmp_path, required_checks=["pytest"])
    service = h.service()
    change = h.view()

    baseline = service.capture_baseline(change)
    run = service.launch_agent(change, AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", EDIT], timeout_seconds=30))
    current = service.capture_current(h.view(revision=1))
    plan = service.plan_assurance(change)
    runs = service.run_assurance(change, plan.id)

    events = h.events()
    _assert_chain_valid(events)

    types = [e.event_type for e in events]
    assert types == [
        JournalEventType.GIT_CHECKPOINT_CAPTURED,        # baseline
        JournalEventType.ENVIRONMENT_PASSPORT_CAPTURED,  # baseline
        JournalEventType.AGENT_LAUNCHED,
        JournalEventType.AGENT_COMPLETED,
        JournalEventType.GIT_CHECKPOINT_CAPTURED,         # current
        JournalEventType.ENVIRONMENT_PASSPORT_CAPTURED,   # current
        JournalEventType.DEPENDENCY_REPORT_CAPTURED,
        JournalEventType.ASSURANCE_PLAN_CREATED,
        *[JournalEventType.ASSURANCE_CHECK_COMPLETED] * len(runs),
    ]

    checkpoint_events = [e for e in events if e.event_type is JournalEventType.GIT_CHECKPOINT_CAPTURED]
    assert checkpoint_events[0].subject_id == baseline.checkpoint.id
    assert checkpoint_events[1].subject_id == current.checkpoint.id

    launched = next(e for e in events if e.event_type is JournalEventType.AGENT_LAUNCHED)
    completed = next(e for e in events if e.event_type is JournalEventType.AGENT_COMPLETED)
    assert launched.subject_id == run.id == completed.subject_id
    assert completed.payload["status"] == run.status.value

    plan_event = next(e for e in events if e.event_type is JournalEventType.ASSURANCE_PLAN_CREATED)
    assert plan_event.subject_id == plan.id

    check_events = [e for e in events if e.event_type is JournalEventType.ASSURANCE_CHECK_COMPLETED]
    assert {e.subject_id for e in check_events} == {r.id for r in runs}
    assert {e.payload["status"] for e in check_events} == {r.status.value for r in runs}


def test_supervised_descendants_emit_bounded_process_events(tmp_path, monkeypatch):
    if not IS_WINDOWS:
        return
    monkeypatch.setattr(sys, "executable", REAL_PYTHON)
    h = Harness(tmp_path)
    child = "import time; time.sleep(0.4)"
    parent = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable, '-c', {child!r}]); p.wait()"
    )
    run = h.service().launch_agent(
        h.view(),
        AgentLaunchRequest(
            adapter="generic", executable="python", args=["-c", parent], timeout_seconds=10,
        ),
    )

    assert len(run.descendant_processes) == 1
    events = h.events()
    assert JournalEventType.AGENT_DESCENDANT_OBSERVED in {event.event_type for event in events}
    assert JournalEventType.AGENT_DESCENDANT_TERMINATED in {event.event_type for event in events}
    observed = next(
        event for event in events
        if event.event_type is JournalEventType.AGENT_DESCENDANT_OBSERVED
    )
    assert observed.payload["pid"] == run.descendant_processes[0].pid
    with h.db.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM descendant_processes WHERE agent_run_id = ?", (str(run.id),)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["pid"] == run.descendant_processes[0].pid


def test_git_checkpoint_effect_chains_before_and_produced_digest(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    change = h.view()
    baseline = service.capture_baseline(change)
    current = service.capture_current(h.view(revision=1))

    with h.db.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_effects WHERE resource_type = 'git_checkpoint' "
            "ORDER BY rowid", (),
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["before_digest"] is None
    assert rows[0]["produced_digest"] == baseline.checkpoint.status_digest
    assert rows[1]["before_digest"] == baseline.checkpoint.status_digest
    assert rows[1]["produced_digest"] == current.checkpoint.status_digest
    assert rows[0]["restoration_class"] == "none"


def test_environment_effect_uses_unknown_restoration_class(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    service.capture_baseline(h.view())

    with h.db.connection() as connection:
        row = connection.execute(
            "SELECT * FROM journal_effects WHERE resource_type = 'environment_passport'"
        ).fetchone()
    assert row["restoration_class"] == "unknown"
    assert row["before_digest"] is None
    assert row["produced_digest"] is not None


def test_agent_attach_and_stop_requested_are_journaled(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    change = h.view()

    attached = service.attach_agent(change, AgentAttachRequest(adapter="claude", external_run_id="e1"))
    service.stop_agent(h.change_id, attached.id)

    events = h.events()
    types = [e.event_type for e in events]
    assert JournalEventType.AGENT_ATTACHED in types
    assert JournalEventType.AGENT_STOP_REQUESTED in types
    attach_event = next(e for e in events if e.event_type is JournalEventType.AGENT_ATTACHED)
    assert attach_event.subject_id == attached.id


def test_journal_is_absent_when_evidence_service_has_no_journal_configured(tmp_path):
    """Backward compatibility: `journal=None` is a real no-op, not a crash."""

    h = Harness(tmp_path)
    service = EvidenceService(EvidenceStore(h.db), environment=EnvironmentTracker(
        tools={"python": ["--version"]}))
    service.capture_baseline(h.view())
    assert h.events() == []


def test_no_orphaned_agent_launched_event_without_a_matching_completed_event(tmp_path):
    """A synchronous launch always returns a terminal AgentRun (AgentLauncher
    catches start failures internally and reports AgentRunStatus.ERROR rather
    than raising), so agent.launched and agent.completed are always emitted
    together -- there is no code path that journals one without the other."""

    h = Harness(tmp_path)
    service = h.service()
    change = h.view()
    service.launch_agent(change, AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", "print('x')"], timeout_seconds=30))

    events = h.events()
    launched = [e for e in events if e.event_type is JournalEventType.AGENT_LAUNCHED]
    completed = [e for e in events if e.event_type is JournalEventType.AGENT_COMPLETED]
    assert len(launched) == len(completed) == 1
    assert launched[0].subject_id == completed[0].subject_id
