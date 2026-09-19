"""Owner-local end-to-end flows for the whole Person 2 (``[KB]``) stream.

Every step uses the concrete production classes against real disposable Git
repositories, real subprocesses (including a real pytest and a real Node test
run) and a real SQLite round trip. Nothing here touches shared wiring or another
owner's modules.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.assurance.engine import AssuranceEngine
from backend.app.assurance.models import DeviationCategory
from backend.app.contracts.models import (
    AgentLaunchRequest, AgentRunStatus, AssuranceStatus, ChangeContract, ChangeView,
    EvidenceStatus, ReviewState, RiskLevel,
)
from backend.app.dependencies.tracker import DependencyTracker
from backend.app.environment.tracker import EnvironmentTracker
from backend.app.execution.launcher import AgentLauncher
from backend.app.git.state import GitStateTracker
from backend.tests.support_kb import git, make_repo, write

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CANARY = "kb-e2e-canary-TOKEN-value-424242"

PY_FILES = {
    "pyproject.toml": '[project]\nname = "demo"\ndependencies = ["flask==2.0.0"]\n'
                      "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
    "requirements.txt": "flask==2.0.0\n",
    "app.py": "def add(a, b):\n    return a + b\n",
    "tests/test_app.py": "from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "docs/readme.md": "docs\n",
}
AGENT_EDIT = (
    "import pathlib\n"
    "p = pathlib.Path('app.py')\n"
    "p.write_text('def add(a, b):\\n    return a + b + 0\\n')\n"
    "pathlib.Path('requirements.txt').write_text('flask==3.0.0\\nrequests>=2\\n')\n"
    "pathlib.Path('notes.txt').write_text('agent notes\\n')\n"
    "print('edited')\n"
)


def change_view(repo, **contract):
    return ChangeView(id=uuid4(), title="demo change", intent="demo", repository_path=str(repo),
                      created_at=NOW, updated_at=NOW, review_state=ReviewState.NO_CHANGES,
                      risk_level=RiskLevel.LOW, contract=ChangeContract(**contract))


def roundtrip_through_sqlite(*models):
    """Persist every evidence model as JSON and prove it reloads identically."""

    db = sqlite3.connect(":memory:")
    db.execute("create table evidence (id integer primary key, kind text, body text)")
    for model in models:
        db.execute("insert into evidence (kind, body) values (?, ?)",
                   (type(model).__name__, model.model_dump_json()))
    rows = db.execute("select kind, body from evidence order by id").fetchall()
    db.close()
    for model, (kind, body) in zip(models, rows):
        assert kind == type(model).__name__
        assert type(model).model_validate_json(body) == model
    return [body for _, body in rows]


def test_python_change_flow_from_baseline_to_fresh_assurance(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_E2E_CANARY_TOKEN", CANARY)
    repo = make_repo(tmp_path / "python repo", PY_FILES)
    change = change_view(repo, required_checks=["pytest"], allowed_paths=["**"],
                         forbidden_paths=["secrets/**"], expected_outcomes=["upgrade flask"])
    git_state, environment = GitStateTracker(), EnvironmentTracker(
        tools={"git": ["--version"], "python": ["--version"]}, sensitive_keys=("KB_E2E_CANARY_TOKEN",))
    launcher, dependencies, engine = AgentLauncher(), DependencyTracker(), AssuranceEngine()

    # 1-2. Baseline evidence before the agent runs.
    baseline_cp = git_state.capture(change.id, "baseline", str(repo), 1, 100_000)
    baseline_env = environment.capture(change.id, str(repo))
    assert baseline_cp.summary.is_clean and baseline_env.status is EvidenceStatus.CURRENT

    # 3. Launch a real top-level agent process that edits the repository.
    run = launcher.launch(change.id, str(repo), AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", AGENT_EDIT], timeout_seconds=30), 10_000)
    assert run.status is AgentRunStatus.PASSED and run.stdout.strip() == "edited"
    assert run.descendant_control_available is False and run.limitations

    # 4. Current evidence and comparison.
    current_cp = git_state.capture(change.id, "current", str(repo), 2, 100_000)
    comparison = git_state.compare(baseline_cp, current_cp)
    assert comparison.added_paths == ["app.py", "notes.txt", "requirements.txt"]
    assert not comparison.head_changed and not comparison.branch_moved
    current_env = environment.capture(change.id, str(repo))
    drift = environment.compare(baseline_env, current_env)
    assert [f.key for f in drift.changed] == ["repo.manifests"] or drift.changed == []
    assert drift.causal_attribution_available is False
    report = dependencies.scan(change.id, current_cp, str(repo))
    changes = {(c.package, c.source_path): c for c in report.changes}
    assert (changes[("flask", "requirements.txt")].old_version,
            changes[("flask", "requirements.txt")].new_version) == ("2.0.0", "3.0.0")
    assert changes[("requests", "requirements.txt")].old_version is None
    assert all(c.causal_attribution_available is False for c in report.changes)

    # 5. Evidence-selected assurance, executed for real.
    plan = engine.discover(change, current_cp, current_env, report)
    pytest_check = next(c for c in plan.checks if c.id == "pytest")
    assert pytest_check.required
    runs = engine.run(change, plan, str(repo), 200_000)
    assert [r.status for r in runs if r.check_id == "pytest"] == [AssuranceStatus.PASSED]
    evaluation = engine.evaluate(change, plan, runs, dependencies=report, environment_drift=drift)
    assert evaluation.fresh, evaluation.freshness_reasons     # running checks left the repository untouched
    assert evaluation.required_assurance_passed and evaluation.assurance_fresh
    assert evaluation.deviations_resolved
    assert "passed" in next(r for r in evaluation.results if r.check_id == "pytest").summary
    assert any(d.category is DeviationCategory.DEPENDENCY_CHANGE for d in evaluation.deviations)
    assert any(g.startswith("Untracked file contents") for g in evaluation.coverage_gaps)

    # 6. Any later edit invalidates every earlier result.
    write(repo, "app.py", "def add(a, b):\n    return b + a\n")
    stale = engine.evaluate(change, plan, runs)
    assert stale.status is EvidenceStatus.STALE and not stale.required_assurance_passed
    assert not git_state.is_current(current_cp)
    rerun = engine.run(change, plan, str(repo), 1000)
    assert {r.status for r in rerun} == {AssuranceStatus.SKIPPED}

    # 7. Everything is JSON/SQLite-ready and no canary secret leaked anywhere.
    bodies = roundtrip_through_sqlite(
        baseline_cp, current_cp, comparison, baseline_env, current_env, drift, report, plan,
        *runs, evaluation, run)
    blob = "\n".join(bodies) + repr([baseline_env, current_env])
    assert CANARY not in blob
    assert any(f.key == "env.KB_E2E_CANARY_TOKEN" and f.sensitive for f in current_env.facts)


def test_failing_required_check_blocks_and_recovery_is_visible(tmp_path):
    repo = make_repo(tmp_path / "repo", PY_FILES)
    change = change_view(repo, required_checks=["pytest"])
    git_state, engine = GitStateTracker(), AssuranceEngine()
    write(repo, "app.py", "def add(a, b):\n    return a - b\n")           # breaks the test
    cp = git_state.capture(change.id, "cp", str(repo), 1, 100_000)
    plan = engine.discover(change, cp, None, None)
    runs = engine.run(change, plan, str(repo), 100_000)
    result = next(r for r in runs if r.check_id == "pytest")
    assert result.status is AssuranceStatus.FAILED and result.exit_code == 1
    assert "assert" in result.stdout
    evaluation = engine.evaluate(change, plan, runs)
    assert evaluation.fresh and not evaluation.required_assurance_passed
    assert evaluation.failed == ["pytest"]
    assert "Environment evidence is missing." in evaluation.coverage_gaps
    assert evaluation.status is EvidenceStatus.PARTIAL

    write(repo, "app.py", "def add(a, b):\n    return a + b\n")            # fix, then re-plan
    cp2 = git_state.capture(change.id, "cp2", str(repo), 2, 100_000)
    plan2 = engine.discover(change, cp2, None, None)
    runs2 = engine.run(change, plan2, str(repo), 100_000)
    assert engine.evaluate(change, plan2, runs2).required_assurance_passed
    # The first plan's evidence is now stale and cannot be reused.
    assert not engine.evaluate(change, plan, runs).fresh


def test_contract_violation_by_agent_is_a_blocking_deviation(tmp_path):
    repo = make_repo(tmp_path / "repo", {**PY_FILES, "secrets/key.pem": "old\n"})
    change = change_view(repo, allowed_paths=["*.py", "tests/**"], forbidden_paths=["secrets/**"])
    git_state, engine = GitStateTracker(), AssuranceEngine()
    script = ("import pathlib\npathlib.Path('secrets/key.pem').write_text('rotated')\n"
              "pathlib.Path('docs/readme.md').write_text('edited')\n")
    run = AgentLauncher().launch(change.id, str(repo), AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", script], timeout_seconds=30), 1000)
    assert run.status is AgentRunStatus.PASSED
    cp = git_state.capture(change.id, "cp", str(repo), 1, 100_000)
    plan = engine.discover(change, cp, None, None)
    evaluation = engine.evaluate(change, plan, [], current_checkpoint=cp)
    blocking = {(d.category, d.subject) for d in evaluation.deviations if d.severity.value == "BLOCKING"}
    assert (DeviationCategory.FORBIDDEN_PATH, "secrets/key.pem") in blocking
    assert (DeviationCategory.OUTSIDE_ALLOWED_PATHS, "docs/readme.md") in blocking
    assert not evaluation.deviations_resolved
    assert evaluation.model_dump() == engine.evaluate(change, plan, [], current_checkpoint=cp).model_dump()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_node_change_flow_with_real_node_test_runner(tmp_path):
    files = {
        "package.json": json.dumps({"name": "demo", "version": "1.0.0",
                                    "scripts": {"test": "node --test"},
                                    "dependencies": {}}),
        "package-lock.json": json.dumps({"name": "demo", "lockfileVersion": 3,
                                         "packages": {"": {"name": "demo"}}}),
        "src/sum.js": "exports.sum = (a, b) => a + b;\n",
        "test/sum.test.js": ("const test = require('node:test');\nconst assert = require('node:assert');\n"
                             "const { sum } = require('../src/sum.js');\n"
                             "test('sum', () => assert.strictEqual(sum(1, 2), 3));\n"),
    }
    repo = make_repo(tmp_path / "node repo", files)
    change = change_view(repo, required_checks=["npm test"])
    git_state, engine = GitStateTracker(), AssuranceEngine()

    write(repo, "src/sum.js", "exports.sum = (a, b) => b + a;\n")
    write(repo, "package.json", json.dumps({"name": "demo", "version": "1.0.0",
                                            "scripts": {"test": "node --test"},
                                            "dependencies": {"left-pad": "1.3.0"}}))
    cp = git_state.capture(change.id, "cp", str(repo), 1, 100_000)
    report = DependencyTracker().scan(change.id, cp, str(repo))
    left_pad = next(c for c in report.changes if c.package == "left-pad")
    assert left_pad.new_version == "1.3.0" and left_pad.direct is True
    assert any("Manifest" not in n for n in left_pad.risk_notes) or left_pad.risk_notes == []
    plan = engine.discover(change, cp, None, report)
    check = next(c for c in plan.checks if c.id == "node-test")
    assert check.required and check.executable == "npm"
    runs = engine.run(change, plan, str(repo), 100_000)
    node_run = next(r for r in runs if r.check_id == "node-test")
    assert node_run.status is AssuranceStatus.PASSED, node_run.stderr + node_run.stdout
    evaluation = engine.evaluate(change, plan, runs, dependencies=report)
    assert evaluation.fresh and evaluation.required_assurance_passed
    assert "1 pass" in next(r for r in evaluation.results if r.check_id == "node-test").summary

    write(repo, "src/sum.js", "exports.sum = (a, b) => a - b;\n")           # break it
    cp2 = git_state.capture(change.id, "cp2", str(repo), 2, 100_000)
    plan2 = engine.discover(change, cp2, None, None)
    runs2 = engine.run(change, plan2, str(repo), 100_000)
    failed = next(r for r in runs2 if r.check_id == "node-test")
    assert failed.status is AssuranceStatus.FAILED
    assert not engine.evaluate(change, plan2, runs2).required_assurance_passed


def test_launcher_cancel_and_attach_metadata_feed_the_same_records(tmp_path):
    import threading
    import time
    repo = make_repo(tmp_path / "repo")
    change = change_view(repo)
    launcher = AgentLauncher()
    holder = {}

    def go():
        holder["run"] = launcher.launch(change.id, str(repo), AgentLaunchRequest(
            adapter="generic", executable="python", timeout_seconds=120,
            args=["-c", "import time; time.sleep(60)"]), 1000)

    thread = threading.Thread(target=go)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not launcher._runs:
        time.sleep(0.02)
    time.sleep(0.3)
    stopped = launcher.stop(next(iter(launcher._runs)))
    thread.join(10)
    assert stopped.status is AgentRunStatus.CANCELLED and holder["run"].status is AgentRunStatus.CANCELLED
    from backend.app.contracts.models import AgentAttachRequest
    attached = launcher.attach(change.id, AgentAttachRequest(adapter="claude", external_run_id="ext-42"))
    assert attached.status is AgentRunStatus.ATTACHED
    roundtrip_through_sqlite(stopped, attached)
    assert os.path.isdir(repo)
    assert git(repo, "status", "--porcelain") == ""
