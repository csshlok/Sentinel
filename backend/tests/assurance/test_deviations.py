from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.assurance.deviations import analyze_deviations, matches
from backend.app.assurance.models import DeviationCategory as C, DeviationSeverity as S
from backend.app.contracts.models import (
    ChangeContract, ChangedPath, ChangedPathStatus, ChangeView, DependencyChange,
    DependencyReport, EnvironmentDrift, EnvironmentFact, GitCheckpoint, GitSummary,
    PathCategory, ReviewState, RiskLevel,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
SHA = "a" * 40


def entry(path, status=ChangedPathStatus.MODIFIED, old=None):
    return ChangedPath(path=path, old_path=old, status=status, staged=False, unstaged=True,
                       category=PathCategory.SOURCE)


def checkpoint(*entries):
    summary = GitSummary(repository_root="C:/r", branch="main", head_sha=SHA,
                         is_clean=not entries, files=list(entries), total_additions=0,
                         total_deletions=0, patch="", refreshed_at=NOW)
    return GitCheckpoint(id=uuid4(), change_id=uuid4(), name="c", repository_root="C:/r",
                         branch="main", head_sha=SHA, status_digest="0" * 64, summary=summary,
                         evidence_revision=1, captured_at=NOW)


def view(risk=RiskLevel.LOW, **contract):
    return ChangeView(id=uuid4(), title="t", intent="i", repository_path="C:/r", created_at=NOW,
                      updated_at=NOW, review_state=ReviewState.NO_CHANGES, risk_level=risk,
                      contract=ChangeContract(**contract))


@pytest.mark.parametrize(("path", "pattern", "expected"), [
    ("src/a.py", "src/**", True), ("src/a/b/c.py", "src/**", True), ("src", "src/**", False),
    ("srcx/a.py", "src/**", False), ("a.py", "**", True), ("a/b.py", "**/*.py", True),
    ("a.py", "**/*.py", True), ("a.txt", "**/*.py", False), ("a/b.py", "*.py", True),
    ("src/a.py", "src/*.py", True), ("src/x/a.py", "src/*.py", False),
    ("src/a.py", "src/?.py", True), ("src/ab.py", "src/?.py", False),
    ("docs/x.md", "docs/", True), ("a/docs/x.md", "docs/", True), ("docs", "docs", True),
    ("SRC/A.PY", "src/*.py", True), ("src\\a.py", "src/*.py", True),
    ("./src/a.py", "./src/**", False), ("a.py", "./a.py", True),
    ("src/a.py", "src/a.py", True), ("src/a.pyc", "src/a.py", False),
    ("a+b(1).py", "a+b(1).py", True), ("lib/x/y/z.py", "lib/**/z.py", True),
    ("lib/z.py", "lib/**/z.py", True),
])
def test_glob_semantics(path, pattern, expected):
    assert matches(path, pattern) is expected


def test_default_contract_allows_everything_and_flags_nothing():
    findings = analyze_deviations(view(), checkpoint(entry("a/b.py"), entry("c.md")))
    assert findings == []


def test_forbidden_and_outside_allowed_including_rename_source():
    change = view(allowed_paths=["src/**"], forbidden_paths=["src/secret/**", "*.pem"])
    cp = checkpoint(entry("src/ok.py"), entry("src/secret/k.py"), entry("docs/x.md"),
                    entry("src/new.py", ChangedPathStatus.RENAMED, old="key.pem"))
    findings = analyze_deviations(change, cp)
    pairs = {(f.category, f.subject) for f in findings}
    assert (C.FORBIDDEN_PATH, "src/secret/k.py") in pairs
    assert (C.FORBIDDEN_PATH, "key.pem") in pairs
    assert (C.OUTSIDE_ALLOWED_PATHS, "docs/x.md") in pairs
    assert (C.OUTSIDE_ALLOWED_PATHS, "key.pem") in pairs
    assert not any(f.subject == "src/ok.py" for f in findings)
    assert all(f.severity is S.BLOCKING for f in findings)


def test_merge_conflict_and_deterministic_order():
    cp = checkpoint(entry("z.py", ChangedPathStatus.CONFLICTED), entry("a.py", ChangedPathStatus.CONFLICTED))
    findings = analyze_deviations(view(), cp)
    assert [(f.category, f.subject) for f in findings] == [
        (C.MERGE_CONFLICT, "a.py"), (C.MERGE_CONFLICT, "z.py")]
    assert analyze_deviations(view(), cp) == findings


@pytest.mark.parametrize(("risk", "ceiling", "category", "severity"), [
    (RiskLevel.HIGH, RiskLevel.MEDIUM, C.RISK_ABOVE_CEILING, S.BLOCKING),
    (RiskLevel.UNKNOWN, RiskLevel.MEDIUM, C.RISK_NOT_ASSESSED, S.WARNING),
])
def test_risk(risk, ceiling, category, severity):
    findings = analyze_deviations(view(risk, max_risk=ceiling), checkpoint())
    assert [(f.category, f.severity) for f in findings] == [(category, severity)]
    assert analyze_deviations(view(RiskLevel.MEDIUM, max_risk=RiskLevel.MEDIUM), checkpoint()) == []


def test_dependency_and_environment_findings_and_expected_terms():
    change = view(expected_outcomes=["upgrade flask", "python.version may change"])
    deps = DependencyReport(
        id=uuid4(), change_id=change.id, checkpoint_id=uuid4(), captured_at=NOW,
        changes=[DependencyChange(ecosystem="python", package="flask", source_path="requirements.txt"),
                 DependencyChange(ecosystem="node", package="left-pad", source_path="package.json")],
        unsupported_ecosystems=["node: yarn.lock (format not supported)"])
    drift = EnvironmentDrift(
        baseline_id=uuid4(), current_id=uuid4(),
        added=[EnvironmentFact(key="tool.new.version", value="1")],
        changed=[EnvironmentFact(key="python.version", value="3.14")],
        removed=[EnvironmentFact(key="tool.gone.version", value="1")],
        unknown=[EnvironmentFact(key="tool.x.version", status="PARTIAL")])
    findings = analyze_deviations(change, checkpoint(), deps, drift)
    got = {(f.category, f.subject): f.severity for f in findings}
    assert got[(C.DEPENDENCY_CHANGE, "python:flask")] is S.INFO
    assert got[(C.DEPENDENCY_CHANGE, "node:left-pad")] is S.WARNING
    assert got[(C.ENVIRONMENT_DRIFT, "python.version")] is S.INFO
    assert got[(C.ENVIRONMENT_DRIFT, "tool.new.version")] is S.WARNING
    assert got[(C.ENVIRONMENT_DRIFT, "tool.gone.version")] is S.WARNING
    assert got[(C.ENVIRONMENT_DRIFT, "tool.x.version")] is S.WARNING
    assert any(f.category is C.DEPENDENCY_EVIDENCE_GAP for f in findings)
    assert "caus" not in " ".join(f.detail for f in findings).replace("cause is not attributed", "")
    assert [f.severity for f in findings] == sorted(
        (f.severity for f in findings), key=lambda s: {S.BLOCKING: 0, S.WARNING: 1, S.INFO: 2}[s])
