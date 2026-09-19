from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.assurance.engine import AssuranceEngine
from backend.app.assurance.models import DeviationCategory
from backend.app.assurance.service import EvidenceService
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (
    AgentAttachRequest, AgentLaunchRequest, AgentRunStatus, AssuranceStatus, ChangeContract,
    ChangeView, EvidenceStatus, ReviewState, RiskLevel,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.environment.tracker import EnvironmentTracker
from backend.app.identity.repository import DelegationRepository
from backend.app.passport.builder import PassportBuilder
from backend.tests.support_kb import git, make_repo, write

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

    def view(self, contract=None, revision=0) -> ChangeView:
        return ChangeView(id=self.change_id, title="t", intent="i", repository_path=str(self.repo),
                          created_at=NOW, updated_at=NOW, review_state=ReviewState.NO_CHANGES,
                          risk_level=RiskLevel.LOW, contract=contract or self.contract,
                          evidence_revision=revision)

    def service(self) -> EvidenceService:
        """A brand-new service over the same database (simulates a restart)."""

        return EvidenceService(
            EvidenceStore(self.db),
            environment=EnvironmentTracker(tools={"python": ["--version"]}))


def test_full_persisted_flow_survives_a_restart(tmp_path):
    h = Harness(tmp_path, required_checks=["pytest"])
    change = h.view()
    first = h.service()

    baseline = first.capture_baseline(change)
    assert baseline.checkpoint.name == "baseline" and baseline.comparison is None
    run = first.launch_agent(change, AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", EDIT], timeout_seconds=30))
    assert run.status is AgentRunStatus.PASSED
    current = first.capture_current(h.view(revision=1))
    assert current.comparison.added_paths == ["app.py", "requirements.txt"]
    flask = next(c for c in current.dependencies.changes if c.package == "flask")
    assert (flask.old_version, flask.new_version) == ("2.0.0", "3.0.0")

    plan = first.plan_assurance(change)
    assert any(c.id == "pytest" and c.required for c in plan.checks)
    runs = first.run_assurance(change, plan.id)
    assert {r.status for r in runs if r.check_id == "pytest"} == {AssuranceStatus.PASSED}
    facts = first.assurance_facts(change)
    assert facts.assurance_fresh and facts.required_assurance_passed and facts.deviations_resolved

    # Restart: a new service, launcher and engine know nothing in memory.
    second = h.service()
    again = second.evaluate(change, plan.id)
    assert again.fresh and again.required_assurance_passed
    assert again.results[0].status is AssuranceStatus.PASSED
    assert second.assurance_facts(change).required_assurance_passed
    assert [r.id for r in second.agent_runs(change.id)] == [run.id]
    assert second.agent_runs(change.id)[0].stdout.strip() == "done"

    # The contract changing after planning is still noticed after a restart.
    edited = h.view(contract=ChangeContract(required_checks=["pytest"], max_risk=RiskLevel.LOW))
    stale = h.service().evaluate(edited, plan.id)
    assert stale.status is EvidenceStatus.STALE
    assert "The Change Contract changed after the plan was made." in stale.freshness_reasons
    assert not h.service().assurance_facts(edited).required_assurance_passed

    # And so is any later repository edit.
    write(h.repo, "app.py", "def add(a, b):\n    return a + b + 0\n")
    later = h.service().assurance_facts(change)
    assert not later.assurance_fresh and not later.required_assurance_passed
    assert any("repository changed" in reason for reason in later.reasons)


def test_committed_agent_edits_are_still_detected_as_evidence(tmp_path):
    """Reproduces the audit finding: baseline-to-current comparison and

    dependency tracking previously compared each checkpoint's own
    working-tree status (or, for dependencies, checkpoint HEAD vs working
    tree) rather than baseline-to-current commit content. When the agent
    *committed* its edits before `capture_current` ran -- the ordinary way
    a real coding agent works -- both the changed-path comparison and the
    dependency upgrade disappeared entirely from the evidence, because by
    capture time the working tree was clean and already matched the new
    commit. This reproduces exactly that: a real `git commit` between
    baseline and current, no uncommitted state left behind.
    """

    h = Harness(tmp_path, required_checks=["pytest"])
    change = h.view()
    service = h.service()

    baseline = service.capture_baseline(change)
    assert baseline.checkpoint.name == "baseline"

    write(h.repo, "app.py", "def add(a, b):\n    return b + a\n")
    write(h.repo, "requirements.txt", "flask==3.0.0\n")
    git(h.repo, "add", "-A")
    git(h.repo, "commit", "-q", "-m", "agent commit")

    current = service.capture_current(h.view(revision=1))

    # The committed file edits must still show up, not disappear because
    # the working tree was clean by the time `current` was captured.
    assert "app.py" in current.comparison.changed_paths
    assert "requirements.txt" in current.comparison.changed_paths
    assert current.comparison.added_paths == []
    assert current.comparison.removed_paths == []

    # The committed dependency upgrade must still be visible.
    flask = next(c for c in current.dependencies.changes if c.package == "flask")
    assert (flask.old_version, flask.new_version) == ("2.0.0", "3.0.0")


def test_a_committed_forbidden_path_edit_is_still_visible_as_a_deviation(tmp_path):
    """The same defect, but for contract-deviation analysis: a forbidden

    -path edit that gets committed before `capture_current` must still be
    caught as a deviation, not silently pass review because the working
    tree looked clean at capture time.
    """

    h = Harness(tmp_path, required_checks=["pytest"], forbidden_paths=["secrets"])
    change = h.view()
    service = h.service()
    service.capture_baseline(change)

    write(h.repo, "secrets/token.txt", "sh-secret-value\n")
    git(h.repo, "add", "-A")
    git(h.repo, "commit", "-q", "-m", "forbidden edit")

    current = service.capture_current(h.view(revision=1))
    assert "secrets/token.txt" in current.comparison.added_paths

    change_with_contract = h.view(
        contract=ChangeContract(required_checks=["pytest"], forbidden_paths=["secrets"]),
        revision=1,
    )
    plan = service.plan_assurance(change_with_contract)
    evaluation = service.evaluate(change_with_contract, plan.id)
    assert any(
        deviation.category is DeviationCategory.FORBIDDEN_PATH
        for deviation in evaluation.deviations
    )


def test_baseline_rules(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    with pytest.raises(AppError) as info:
        service.capture_current(h.view())
    assert info.value.code == "BASELINE_MISSING" and info.value.status_code == 409
    service.capture_baseline(h.view())
    with pytest.raises(AppError) as info:
        h.service().capture_baseline(h.view())
    assert info.value.code == "BASELINE_EXISTS"


def test_planning_needs_evidence_and_facts_default_to_false(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    with pytest.raises(AppError) as info:
        service.plan_assurance(h.view())
    assert info.value.code == "EVIDENCE_MISSING"
    facts = service.assurance_facts(h.view())
    assert not any([facts.required_assurance_passed, facts.assurance_fresh,
                    facts.deviations_resolved, facts.required_evidence_complete])
    assert facts.reasons == ["No assurance plan exists for this Change."]


def test_plan_lookup_is_scoped_to_the_change(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    service.capture_baseline(h.view())
    plan = service.plan_assurance(h.view())
    other = h.view().model_copy(update={"id": uuid4()})
    for call in (service.run_assurance, service.evaluate):
        with pytest.raises(AppError) as info:
            call(other, plan.id)
        assert info.value.code == "ASSURANCE_PLAN_NOT_FOUND"
    with pytest.raises(AppError) as info:
        service.evaluate(h.view(), uuid4())
    assert info.value.status_code == 404


def test_missing_checkpoint_for_plan_is_reported(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    service.capture_baseline(h.view())
    plan = service.plan_assurance(h.view())
    with h.db.connection(immediate=True) as c:
        c.execute("PRAGMA foreign_keys = OFF")
        c.execute("DELETE FROM git_checkpoints")
    with pytest.raises(AppError) as info:
        service.evaluate(h.view(), plan.id)
    assert info.value.code == "EVIDENCE_MISSING"
    assert h.service().assurance_facts(h.view()).reasons == ["The plan's checkpoint is missing."]


def test_agent_run_persistence_attach_and_stop_after_restart(tmp_path):
    h = Harness(tmp_path)
    service = h.service()
    attached = service.attach_agent(h.view(), AgentAttachRequest(adapter="claude", external_run_id="e1"))
    assert attached.status is AgentRunStatus.ATTACHED
    stopped = service.stop_agent(h.change_id, attached.id)
    assert stopped.status is AgentRunStatus.ATTACHED
    restarted = h.service()
    note = restarted.stop_agent(h.change_id, attached.id)  # unknown to the new process
    assert any("restart" in item for item in note.limitations) or any(
        "cannot be stopped" in item for item in note.limitations)
    assert restarted.stop_agent(h.change_id, attached.id).limitations == note.limitations
    with pytest.raises(AppError) as info:
        restarted.stop_agent(h.change_id, uuid4())
    assert info.value.code == "AGENT_RUN_NOT_FOUND"
    assert len(restarted.agent_runs(h.change_id)) == 1


def test_store_is_immutable_for_evidence_and_replaces_agent_runs(tmp_path):
    h = Harness(tmp_path)
    store = EvidenceStore(h.db)
    service = h.service()
    snapshot = service.capture_baseline(h.view())
    store.save_checkpoint(snapshot.checkpoint)                    # idempotent
    assert len(store.list_checkpoints(h.change_id)) == 1
    assert store.get_checkpoint(snapshot.checkpoint.id) == snapshot.checkpoint
    assert store.get_environment(snapshot.environment.id) == snapshot.environment
    assert store.latest_checkpoint(h.change_id) == snapshot.checkpoint
    assert store.get_checkpoint(uuid4()) is None and store.latest_plan(uuid4()) is None
    running = service.attach_agent(h.view(), AgentAttachRequest(adapter="claude", external_run_id="e"))
    store.save_agent_run(running.model_copy(update={"completed_at": NOW}))
    assert store.get_agent_run(running.id).completed_at == NOW


def test_runs_keep_history_but_evaluation_uses_the_latest(tmp_path):
    h = Harness(tmp_path, required_checks=["pytest"])
    change = h.view()
    service = h.service()
    service.capture_baseline(change)
    write(h.repo, "app.py", "def add(a, b):\n    return a - b\n")
    service.capture_current(change)
    plan = service.plan_assurance(change)
    failing = service.run_assurance(change, plan.id)
    assert failing[0].status is AssuranceStatus.SKIPPED or failing[0].status is AssuranceStatus.FAILED
    write(h.repo, "app.py", "def add(a, b):\n    return a + b\n")
    # Fixing the code moved the repository, so the old plan cannot vouch for it.
    assert not service.evaluate(change, plan.id).fresh
    service.capture_current(change)
    plan2 = service.plan_assurance(change)
    service.run_assurance(change, plan2.id)
    assert service.evaluate(change, plan2.id).required_assurance_passed
    assert len(EvidenceStore(h.db).list_runs(plan.id)) >= 1


def test_persisted_rows_feed_the_passport_builder(tmp_path):
    h = Harness(tmp_path, required_checks=["pytest"])
    change = h.view()
    service = h.service()
    service.capture_baseline(change)
    write(h.repo, "app.py", "def add(a, b):\n    return b + a\n")
    service.capture_current(change)
    plan = service.plan_assurance(change)
    service.run_assurance(change, plan.id)
    passport = PassportBuilder(h.db, DelegationRepository(h.db)).build(change)
    kinds = {item.kind for item in passport.evidence}
    assert {"git_checkpoint", "environment_passport", "dependency_report", "assurance_run"} <= kinds
    assert not any("assurance check" in text or "Git checkpoint" in text or "environment passport" in text
                   or "dependency report" in text for text in passport.limitations)


def test_engine_can_be_injected_and_defaults_are_consistent(tmp_path):
    h = Harness(tmp_path)
    engine = AssuranceEngine()
    service = EvidenceService(EvidenceStore(h.db), assurance=engine)
    service.capture_baseline(h.view())
    assert service.plan_assurance(h.view()).checkpoint_id
