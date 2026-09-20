"""#16 remainder (THREAT_MODEL_FINDINGS.md): a journal-write failure must not

leave [KB]-owned evidence durably saved while the caller was told the request
failed. `EvidenceService` now shares one SQLite transaction between each
`EvidenceStore` write and its paired `JournalWriter.append` (`Database.
connection_or`), mirroring `IdentityAdminService`/`CredentialAdminService`'s
existing fix (`backend/tests/core/test_runtime_service_atomicity.py`) on
KB's side of the codebase.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.assurance.service import EvidenceService
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (
    AgentLaunchRequest, AgentRunStatus, ChangeContract, ChangeView, ReviewState, RiskLevel,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.environment.tracker import EnvironmentTracker
from backend.tests.support_kb import make_repo

NOW = datetime(2026, 1, 1, tzinfo=UTC)
FILES = {"app.py": "def add(a, b):\n    return a + b\n"}


class _ExplodingJournal:
    """A journal double that always fails, to prove the write it would

    have described does not survive when the append raises."""

    def append(self, *args, **kwargs):
        raise RuntimeError("journal backend unavailable")

    def append_effect(self, *args, **kwargs):
        raise RuntimeError("journal backend unavailable")


class Harness:
    def __init__(self, tmp_path):
        self.db = Database(tmp_path / "state" / "db.sqlite3")
        self.db.initialize()
        self.repo = make_repo(tmp_path / "repo", FILES)
        self.change_id = uuid4()
        ChangeRepository(self.db).create(StoredChange(
            id=self.change_id, title="t", intent="i", repository_path=str(self.repo),
            created_at=NOW, updated_at=NOW, last_refreshed_at=None, git_summary=None,
            verification=None))

    def view(self, revision: int = 0) -> ChangeView:
        return ChangeView(id=self.change_id, title="t", intent="i", repository_path=str(self.repo),
                          created_at=NOW, updated_at=NOW, review_state=ReviewState.NO_CHANGES,
                          risk_level=RiskLevel.LOW, contract=ChangeContract(), evidence_revision=revision)

    def failing_service(self) -> EvidenceService:
        return EvidenceService(
            EvidenceStore(self.db), journal=_ExplodingJournal(),
            environment=EnvironmentTracker(tools={"python": ["--version"]}))

    def working_service(self) -> EvidenceService:
        return EvidenceService(
            EvidenceStore(self.db),
            environment=EnvironmentTracker(tools={"python": ["--version"]}))


def test_a_journal_failure_rolls_back_baseline_checkpoint_and_environment(tmp_path):
    h = Harness(tmp_path)
    service = h.failing_service()

    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        service.capture_baseline(h.view())

    with h.db.connection() as connection:
        checkpoints = connection.execute("SELECT 1 FROM git_checkpoints").fetchall()
        environments = connection.execute("SELECT 1 FROM environment_passports").fetchall()
    assert checkpoints == []
    assert environments == []


def test_a_journal_failure_rolls_back_current_evidence_capture(tmp_path):
    h = Harness(tmp_path)
    # Establish a real baseline through a working journal first.
    h.working_service().capture_baseline(h.view())

    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        h.failing_service().capture_current(h.view(revision=1))

    with h.db.connection() as connection:
        checkpoints = connection.execute("SELECT 1 FROM git_checkpoints").fetchall()
        dependency_reports = connection.execute("SELECT 1 FROM dependency_reports").fetchall()
    # Only the earlier, successfully-journaled baseline checkpoint survives.
    assert len(checkpoints) == 1
    assert dependency_reports == []


def test_agent_launch_persistence_is_not_covered_by_this_fix(tmp_path):
    """Documents a real limit of this fix, rather than asserting a guarantee
    that doesn't hold: `AgentLauncher.launch` persists the run itself via
    `on_update` (bound directly to `store.save_agent_run`, no connection)
    as soon as `_notify` fires internally -- including the terminal state,
    committed in its own transaction before `EvidenceService.launch_agent`
    regains control. So unlike the checkpoint/environment/dependency/plan
    cases above, a later journal failure here cannot roll the row back; the
    caller still correctly sees the raised error (the response is not a
    lie), but the run row is durably saved regardless. Closing this for
    real needs `on_update` itself to participate in a shared transaction --
    a launcher-level change, out of scope here."""

    h = Harness(tmp_path)
    service = h.failing_service()

    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        service.launch_agent(h.view(), AgentLaunchRequest(
            adapter="generic", executable="python", args=["-c", "print('x')"], timeout_seconds=30))

    with h.db.connection() as connection:
        rows = connection.execute("SELECT status FROM agent_runs").fetchall()
    assert [row["status"] for row in rows] == [AgentRunStatus.PASSED.value]


def test_a_journal_failure_rolls_back_assurance_plan_creation(tmp_path):
    h = Harness(tmp_path)
    h.working_service().capture_baseline(h.view())

    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        h.failing_service().plan_assurance(h.view())

    with h.db.connection() as connection:
        rows = connection.execute("SELECT 1 FROM assurance_plans").fetchall()
    assert rows == []
