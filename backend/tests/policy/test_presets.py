"""Preset decisions stay deterministic and deny missing required claims."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from backend.app.assurance.engine import contract_digest
from backend.app.contracts.models import ChangeContract, DiffCoverageRule
from backend.app.policy.presets import PRESET_VERSION, PresetEvidence, evaluate_preset
from backend.tests.passport.test_builder import _database, _seed_change


def test_strict_code_names_each_unknown_requirement_and_is_deterministic() -> None:
    evidence = PresetEvidence()
    first = evaluate_preset(preset_name="strict", change_type="code", evidence=evidence)
    second = evaluate_preset(preset_name="strict", change_type="code", evidence=evidence)
    assert first == second
    assert first.status == "DENY" and first.preset_version == PRESET_VERSION
    assert any("checks" in reason for reason in first.reasons)
    assert any("freshness" in reason for reason in first.reasons)
    assert any("diff coverage" in reason for reason in first.reasons)
    assert any("confined checks" in reason for reason in first.reasons)
    assert any("AppContainer" in reason for reason in first.reasons)


@pytest.mark.parametrize("percent,state", [(79.99, "PASS"), (None, "PASS"),
                                            (100.0, "UNKNOWN"), (float("nan"), "PASS")])
def test_standard_code_denies_unmeasured_or_below_threshold(percent, state) -> None:
    result = evaluate_preset(preset_name="standard", change_type="code",
                             evidence=PresetEvidence(checks_passed=True,
                                                     diff_exercised=state,
                                                     measured_percent=percent,
                                                     freshness="CURRENT"))
    assert result.status == "DENY"
    assert any("diff coverage" in reason for reason in result.reasons)


def test_standard_code_allows_measured_current_checks_without_boundary_claim() -> None:
    result = evaluate_preset(preset_name="standard", change_type="code",
                             evidence=PresetEvidence(checks_passed=True,
                                                     diff_exercised="PASS",
                                                     measured_percent=80,
                                                     freshness="CURRENT"))
    assert result.status == "ALLOW" and result.reasons == ()


def test_strict_requires_confined_checks_and_appcontainer_even_with_full_coverage() -> None:
    result = evaluate_preset(preset_name="strict", change_type="code",
                             evidence=PresetEvidence(checks_passed=True,
                                                     diff_exercised="PASS",
                                                     measured_percent=100,
                                                     freshness="CURRENT"))
    assert result.status == "DENY"
    assert result.reasons == (
        "confined checks must be PASS", "observed AppContainer boundary is required")


def test_docs_only_accepts_only_observed_documentation_changes() -> None:
    facts = PresetEvidence(checks_passed=True, freshness="CURRENT",
                           changed_paths=("README.md", "docs/usage.rst"))
    allowed = evaluate_preset(preset_name="docs-only", change_type="docs", evidence=facts)
    assert allowed.status == "ALLOW"
    missing = evaluate_preset(preset_name="docs-only", change_type="docs",
                              evidence=PresetEvidence(checks_passed=True,
                                                      freshness="CURRENT"))
    assert missing.status == "DENY"
    code = evaluate_preset(preset_name="docs-only", change_type="docs",
                           evidence=PresetEvidence(checks_passed=True, freshness="CURRENT",
                                                   changed_paths=("README.md", "src/main.py")))
    assert code.status == "DENY"
    mislabelled = evaluate_preset(preset_name="docs-only", change_type="code", evidence=facts)
    assert mislabelled.status == "DENY"


def test_strict_docs_waits_for_confined_checks() -> None:
    result = evaluate_preset(preset_name="strict", change_type="docs",
                             evidence=PresetEvidence(checks_passed=True,
                                                     freshness="CURRENT",
                                                     changed_paths=("README.md",)))
    assert result.status == "DENY"
    assert "confined checks must be PASS" in result.reasons
    assert "observed AppContainer boundary is required" in result.reasons


def test_stale_freshness_and_unknown_preset_deny_by_name() -> None:
    stale = evaluate_preset(preset_name="standard", change_type="docs",
                            evidence=PresetEvidence(checks_passed=True, freshness="STALE",
                                                    changed_paths=("README.md",)))
    assert stale.status == "DENY" and "STALE" in " ".join(stale.reasons)
    unknown = evaluate_preset(preset_name="other", change_type="code",
                              evidence=PresetEvidence(checks_passed=True))
    assert unknown.status == "DENY"


def test_v3_preset_requires_both_fields_and_old_contract_digests_are_stable(tmp_path) -> None:
    with pytest.raises(ValidationError, match="require schema version 3 together"):
        ChangeContract(schema_version=2, policy_preset_name="strict",
                       policy_change_type="code")
    with pytest.raises(ValidationError, match="require schema version 3 together"):
        ChangeContract(schema_version=3, policy_preset_name="strict")
    change = _seed_change(_database(tmp_path))
    for contract in (ChangeContract(),
                     ChangeContract(schema_version=2, diff_coverage_rule=DiffCoverageRule())):
        original_fields = contract.model_dump(mode="json")
        original_fields.pop("policy_preset_name")
        original_fields.pop("policy_change_type")
        if contract.schema_version == 1:
            original_fields.pop("diff_coverage_rule")
        old_digest = hashlib.sha256(json.dumps(
            original_fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert contract_digest(change.model_copy(update={"contract": contract})) == old_digest
