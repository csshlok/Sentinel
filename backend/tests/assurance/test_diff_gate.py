"""Persisted Change Contract v2 coverage rule and lifecycle gate tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.assurance.engine import contract_digest
from backend.app.assurance.models import AssuranceEvaluation
from backend.app.assurance.service import EvidenceService
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (
    AssurancePlan, ChangeContract, ChangeView, DiffCoverageResult, DiffCoverageRule,
    EvidenceStatus, ReviewState, utc_now,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.git.state import GitStateTracker
from backend.tests.support_kb import make_repo, write


def _fixture(tmp_path: Path) -> tuple[EvidenceService, ChangeView, object]:
    root = make_repo(tmp_path / "repo", {"module.py": "value = 1\n"})
    database = Database(tmp_path / "state" / "db.sqlite3")
    database.initialize()
    contract = ChangeContract(schema_version=2, diff_coverage_rule=DiffCoverageRule(
        required=True, minimum_percent=80, per_file=True, policy_version="coverage-v1"))
    change = ChangeView(id=uuid4(), title="coverage", intent="gate", repository_path=str(root),
                        created_at=utc_now(), updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE,
                        contract=contract)
    ChangeRepository(database).create(StoredChange(
        id=change.id, title=change.title, intent=change.intent, repository_path=str(root),
        created_at=change.created_at, updated_at=change.updated_at, last_refreshed_at=None,
        git_summary=None, verification=None, contract=contract,
    ))
    checkpoint = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    return EvidenceService(EvidenceStore(database)), change, checkpoint


def _result(change: ChangeView, checkpoint: object, state: str) -> DiffCoverageResult:
    return DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=uuid4(), tested_checkpoint_id=checkpoint.id,
        head_sha=checkpoint.head_sha, status_digest=checkpoint.status_digest,
        contract_digest=contract_digest(change), started_at=utc_now(), completed_at=utc_now(),
        collector_status="COLLECTED", checks_passed=True, diff_exercised=state,
        freshness="CURRENT", gate_satisfied=state == "PASS", threshold=80,
        policy_version="coverage-v1",
    )


def test_rule_requires_contract_v2() -> None:
    with pytest.raises(ValidationError, match="requires Change Contract schema version 2"):
        ChangeContract(diff_coverage_rule=DiffCoverageRule(required=True, minimum_percent=1))
    assert ChangeContract(schema_version=2, diff_coverage_rule=DiffCoverageRule(required=True, minimum_percent=1))


def test_required_zero_threshold_is_rejected() -> None:
    with pytest.raises(ValidationError, match="minimum_percent > 0"):
        DiffCoverageRule(required=True)
    with pytest.raises(ValidationError, match="minimum_percent > 0"):
        DiffCoverageRule(required=True, minimum_percent=0)


def test_v1_contract_digest_remains_compatible(tmp_path: Path) -> None:
    _, change, _ = _fixture(tmp_path)
    old = change.model_copy(update={"contract": ChangeContract()})
    body = old.contract.model_dump(mode="json")
    body.pop("diff_coverage_rule")
    expected = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert contract_digest(old) == expected


def test_required_unknown_does_not_satisfy_persisted_gate(tmp_path: Path) -> None:
    evidence, change, checkpoint = _fixture(tmp_path)
    assert evidence._diff_coverage_gate(change)[0] is False
    evidence.save_diff_coverage(_result(change, checkpoint, "UNKNOWN"))
    restarted = EvidenceService(evidence._store)
    assert restarted._diff_coverage_gate(change)[0] is False
    evidence.save_diff_coverage(_result(change, checkpoint, "PASS"))
    assert restarted._diff_coverage_gate(change)[0] is True
    write(Path(change.repository_path), "module.py", "value = 2\n")
    assert restarted._diff_coverage_gate(change)[0] is False


def test_contract_change_invalidates_prior_pass(tmp_path: Path) -> None:
    evidence, change, checkpoint = _fixture(tmp_path)
    evidence.save_diff_coverage(_result(change, checkpoint, "PASS"))
    changed = change.model_copy(update={"contract": ChangeContract(
        schema_version=2, diff_coverage_rule=DiffCoverageRule(required=True, minimum_percent=90))})
    assert evidence._diff_coverage_gate(changed)[0] is False


def test_required_rule_blocks_otherwise_passing_assurance_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence, change, checkpoint = _fixture(tmp_path)
    plan = AssurancePlan(id=uuid4(), change_id=change.id, checkpoint_id=checkpoint.id,
                         created_at=utc_now())
    evidence._store.save_plan(plan, contract_digest(change))
    passing = AssuranceEvaluation(
        plan_id=plan.id, checkpoint_id=checkpoint.id, status=EvidenceStatus.CURRENT,
        fresh=True, required_assurance_passed=True, assurance_fresh=True,
        deviations_resolved=True, required_evidence_complete=True,
    )
    monkeypatch.setattr(evidence, "evaluate", lambda *_: passing)
    assert evidence.assurance_facts(change).required_assurance_passed is False
    evidence.save_diff_coverage(_result(change, checkpoint, "PASS"))
    assert evidence.assurance_facts(change).required_assurance_passed is True
