"""Phase 5 (05-04): Passport v2 signs ``confined_checks`` from persisted check-run records.

PASS only when the check run behind the evaluated diff-coverage evidence has a
row AND hash-verified ``check.confined_run`` journal events with verified token
facts. An UNCONFINED run (claimed, or journaled ``check.unconfined_run``) or a
failed verification is FAIL; no run, a legacy row, or a missing record is
UNKNOWN. The preset evaluator receives the same value. Older bundles (no
``confined_checks`` key) still verify.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.assurance.engine import contract_digest
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (
    ChangeContract,
    DiffCoverageResult,
    JournalEventType,
    PassportV2Payload,
)
from backend.app.core.journal import JournalWriter
from backend.app.execution.check_repository import (
    CheckRunRecord,
    CheckRunRepository,
    CheckRunState,
    RuntimeGrant,
    confined_checks_fact,
)
from backend.app.git.state import GitStateTracker
from backend.app.passport.cng import CngKey, verify_signature
from backend.app.passport.v2 import PassportV2Issuer, canonical_payload
from backend.app.passport.verify import _validate_claims
from backend.app.policy.presets import PresetEvidence, evaluate_preset
from backend.tests.passport.test_builder import _database, _seed_change
from backend.tests.support_kb import make_repo

SID = "S-1-15-2-9-8-7-6-5-4-3"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _facts(**overrides):
    return {"profile_name": "sentinel.check.x", "package_sid": SID, "is_appcontainer": True,
            "integrity_rid": "0x1000", "capability_sids": [], "job_verified": True,
            "verified_at": "2026-10-01T12:00:00+00:00", **overrides}


def _row(database, change_id: UUID, run_id: UUID, *, facts) -> None:
    CheckRunRepository(database).insert(CheckRunRecord(
        id=run_id, change_id=change_id, profile_name=f"sentinel.check.{run_id}",
        package_sid=SID, state=CheckRunState.CLEANED, network=False,
        runtime_grants=(RuntimeGrant("C:\\cache\\py", "b" * 64),), created_at=NOW,
        updated_at=NOW, tree_digest="a" * 64, facts=facts, exit_code=0, timed_out=False))


def _confined_event(database, change_id: UUID, run_id: UUID, **overrides) -> None:
    JournalWriter(database).append(
        change_id, JournalEventType.CHECK_CONFINED_RUN, subject_type="check_run",
        subject_id=run_id, payload={
            "check_run_id": str(run_id), "package_sid": SID, "is_appcontainer": True,
            "integrity_rid": "0x1000", "job_verified": True, "capabilities": [],
            "capability_sids": [], "network": False, "argv_sha256": "c" * 64,
            "tree_manifest_digest": "a" * 64, "runtime_manifest_digests": ["b" * 64],
            "exit_code": 0, "timed_out": False, "boundary": "APPCONTAINER", **overrides})


def _unconfined_event(database, change_id: UUID, run_id: UUID) -> None:
    JournalWriter(database).append(
        change_id, JournalEventType.CHECK_UNCONFINED_RUN, subject_type="check_run",
        subject_id=run_id, payload={"check_run_id": str(run_id), "executable": "cargo",
                                    "argv_sha256": "d" * 64, "exit_code": 0,
                                    "timed_out": False, "boundary": "UNCONFINED"})


def _coverage(database, change, *, run_id: UUID | None, boundary: str | None,
              head_sha: str = "a" * 40, status_digest: str = "b" * 64,
              digest: str = "c" * 64) -> None:
    EvidenceStore(database).save_diff_coverage(DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=uuid4(), tested_checkpoint_id=uuid4(),
        head_sha=head_sha, status_digest=status_digest, contract_digest=digest,
        started_at=NOW, completed_at=NOW, collector_status="COLLECTED", checks_passed=True,
        diff_exercised="PASS", freshness="CURRENT", changed_executable_lines=1,
        executed_changed_lines=1, measured_percent=100, check_run_id=run_id,
        boundary=boundary,
        collection_boundary=("APPCONTAINER_IN_PROCESS" if boundary == "APPCONTAINER"
                             else "UNCONFINED_IN_PROCESS")))


@pytest.fixture
def seeded(tmp_path: Path):
    database = _database(tmp_path)
    change = _seed_change(database)
    return database, change


def _claim(database, change) -> PassportV2Payload:
    return PassportV2Issuer(database).snapshot(change.id)


# ----------------------------------------------------------------- the fact itself

def test_no_check_run_is_unknown(seeded) -> None:
    database, change = seeded
    payload = _claim(database, change)
    assert payload.confined_checks == "UNKNOWN"


def test_legacy_coverage_without_a_run_is_unknown(seeded) -> None:
    database, change = seeded
    _coverage(database, change, run_id=None, boundary=None)
    payload = _claim(database, change)
    assert payload.confined_checks == "UNKNOWN"
    assert any(line.startswith("Confined checks UNKNOWN") for line in payload.limitations)


def test_verified_box_run_is_pass(seeded) -> None:
    database, change = seeded
    run_id = uuid4()
    _row(database, change.id, run_id, facts=_facts())
    _confined_event(database, change.id, run_id)
    _confined_event(database, change.id, run_id)  # coverage run + coverage json export
    _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    payload = _claim(database, change)
    assert payload.confined_checks == "PASS"
    assert payload.diff_coverage.collection_boundary == "APPCONTAINER_IN_PROCESS"
    assert not any(line.startswith("Confined checks") for line in payload.limitations)


@pytest.mark.parametrize("with_coverage", [True, False])
def test_any_unconfined_run_of_the_change_is_fail(seeded, with_coverage) -> None:
    """A delegated unconfined verify run makes the Change's confined_checks FAIL (05-05).

    Even when it is not the run behind the coverage evidence (and even when no
    coverage exists), a check of this Change ran at user authority.
    """

    database, change = seeded
    run_id = uuid4()
    if with_coverage:
        _row(database, change.id, run_id, facts=_facts())
        _confined_event(database, change.id, run_id)
        _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    _unconfined_event(database, change.id, uuid4())  # e.g. a separate `cargo test` verify
    payload = _claim(database, change)
    assert payload.confined_checks == "FAIL"
    assert any("UNCONFINED" in line for line in payload.limitations)


def test_unconfined_run_is_fail(seeded) -> None:
    database, change = seeded
    run_id = uuid4()
    _unconfined_event(database, change.id, run_id)
    _coverage(database, change, run_id=run_id, boundary="UNCONFINED")
    assert _claim(database, change).confined_checks == "FAIL"


def test_unconfined_event_overrides_an_appcontainer_claim(seeded) -> None:
    database, change = seeded
    run_id = uuid4()
    _row(database, change.id, run_id, facts=_facts())
    _confined_event(database, change.id, run_id)
    _unconfined_event(database, change.id, run_id)
    _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    assert _claim(database, change).confined_checks == "FAIL"


@pytest.mark.parametrize("facts", [_facts(is_appcontainer=False), _facts(job_verified=False),
                                   {"profile_name": "x"}])
def test_unverified_row_facts_are_fail(seeded, facts) -> None:
    database, change = seeded
    run_id = uuid4()
    _row(database, change.id, run_id, facts=facts)
    _confined_event(database, change.id, run_id)
    _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    assert _claim(database, change).confined_checks == "FAIL"


@pytest.mark.parametrize("overrides", [
    {"job_verified": False}, {"is_appcontainer": False}, {"boundary": "UNCONFINED"},
    {"package_sid": "S-1-15-2-0"},
])
def test_a_journaled_run_that_fails_verification_is_fail(seeded, overrides) -> None:
    database, change = seeded
    run_id = uuid4()
    _row(database, change.id, run_id, facts=_facts())
    _confined_event(database, change.id, run_id)
    _confined_event(database, change.id, run_id, **overrides)  # mixed: one bad run
    _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    assert _claim(database, change).confined_checks == "FAIL"


def test_missing_row_event_or_launch_record_is_unknown(seeded) -> None:
    database, change = seeded
    no_row, no_event, never_ran = uuid4(), uuid4(), uuid4()
    _confined_event(database, change.id, no_row)
    _row(database, change.id, no_event, facts=_facts())
    _row(database, change.id, never_ran, facts=None)
    _confined_event(database, change.id, never_ran)
    for run_id in (no_row, no_event, never_ran):
        _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
        assert _claim(database, change).confined_checks == "UNKNOWN", run_id


def test_a_run_of_another_change_does_not_count(seeded, tmp_path) -> None:
    database, change = seeded
    other = _seed_change(database)
    run_id = uuid4()
    _row(database, other.id, run_id, facts=_facts())
    _confined_event(database, other.id, run_id)
    _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    assert _claim(database, change).confined_checks == "UNKNOWN"


def test_fact_function_any_fail_wins_and_empty_is_unknown() -> None:
    assert confined_checks_fact([], records={}, events=[])[0] == "UNKNOWN"
    assert confined_checks_fact([(uuid4(), "UNCONFINED"), (None, None)],
                                records={}, events=[])[0] == "FAIL"
    assert confined_checks_fact([(uuid4(), "SOMETHING")], records={}, events=[])[0] == "UNKNOWN"


# ----------------------------------------------------------------- preset evaluation

def _release_change(database, root: Path, change):
    contract = ChangeContract(schema_version=3, policy_preset_name="standard",
                              policy_change_type="release")
    with database.connection() as connection:
        connection.execute(
            "UPDATE changes SET repository_path = ?, contract_json = ? WHERE id = ?",
            (str(root), contract.model_dump_json(), str(change.id)))
    return change.model_copy(update={"contract": contract})


@pytest.mark.parametrize("confined", ["PASS", "UNKNOWN", "FAIL"])
def test_standard_release_allows_only_with_confined_pass(seeded, tmp_path, confined) -> None:
    database, change = seeded
    root = make_repo(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    change = _release_change(database, root, change)
    captured = GitStateTracker().capture(change.id, "measured", str(root), 1, 1_048_576)
    run_id = uuid4()
    if confined == "PASS":
        _row(database, change.id, run_id, facts=_facts())
        _confined_event(database, change.id, run_id)
    elif confined == "FAIL":
        _unconfined_event(database, change.id, run_id)
    _coverage(database, change, run_id=None if confined == "UNKNOWN" else run_id,
              boundary={"PASS": "APPCONTAINER", "FAIL": "UNCONFINED"}.get(confined),
              head_sha=captured.head_sha, status_digest=captured.status_digest,
              digest=contract_digest(change))
    payload = _claim(database, change)
    assert payload.diff_coverage.freshness == "CURRENT"
    assert payload.confined_checks == confined
    if confined == "PASS":
        assert payload.policy_decision == "ALLOW", payload.policy_denials
        assert payload.policy_denials == []
    else:
        assert payload.policy_decision == "DENY"
        assert payload.policy_denials == ["confined checks must be PASS"]


def test_evaluator_gets_the_same_value_strict_still_needs_the_boundary() -> None:
    evidence = dict(checks_passed=True, diff_exercised="PASS", measured_percent=100.0,
                    freshness="CURRENT")
    allowed = evaluate_preset(preset_name="standard", change_type="release",
                              evidence=PresetEvidence(**evidence, confined_checks="PASS"))
    assert allowed.status == "ALLOW"
    strict = evaluate_preset(preset_name="strict", change_type="code",
                             evidence=PresetEvidence(**evidence, confined_checks="PASS"))
    assert strict.status == "DENY"
    assert strict.reasons == ("observed AppContainer boundary is required",)


# ----------------------------------------------------------------- signatures

def test_older_claims_without_the_field_still_normalize(seeded) -> None:
    """``_validate_claims`` drops the additive key when an older bundle lacks it."""

    database, change = seeded
    claims = _claim(database, change).model_dump(mode="json")
    claims.pop("confined_checks")
    passport = {"schema_version": 2, "claims": claims, "signer": {}}
    manifest = {"change_id": str(change.id)}
    # Normalization passes (a mismatch would raise ValueError); the empty member map then
    # fails on the first card lookup.
    with pytest.raises(KeyError):
        _validate_claims(passport, manifest, {}, "0" * 64)
    with pytest.raises(KeyError):
        _validate_claims({**passport, "claims": {**claims, "confined_checks": "UNKNOWN"}},
                         manifest, {}, "0" * 64)
    with pytest.raises(ValueError):  # not a valid claim value
        _validate_claims({**passport, "claims": {**claims, "confined_checks": "PASS ",
                                                 }}, manifest, {}, "0" * 64)


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_issued_signature_covers_confined_checks(seeded) -> None:
    database, change = seeded
    run_id = uuid4()
    _row(database, change.id, run_id, facts=_facts())
    _confined_event(database, change.id, run_id)
    _coverage(database, change, run_id=run_id, boundary="APPCONTAINER")
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        issued = PassportV2Issuer(database, key_name=key_name).issue(change.id)
        assert issued.payload.confined_checks == "PASS"
        assert json.loads(canonical_payload(issued.payload))["confined_checks"] == "PASS"
        spki = base64.b64decode(issued.signer_public_spki_b64)
        signature = base64.b64decode(issued.signature_b64)
        assert verify_signature(spki=spki, message=canonical_payload(issued.payload),
                                signature=signature)
        forged = issued.payload.model_copy(update={"confined_checks": "FAIL"})
        assert not verify_signature(spki=spki, message=canonical_payload(forged),
                                    signature=signature)
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()
