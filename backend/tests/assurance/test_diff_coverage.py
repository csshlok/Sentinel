"""Real repository and coverage acceptance cases for diff-linked assurance."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.assurance.diff_coverage import collect_diff_coverage, evaluate_report
from backend.app.assurance.diff_map import map_diff
from backend.app.contracts.models import (
    ChangeView, DiffCoverageRequest, DiffCoverageRule, DiffCoverageResult, ReviewState, utc_now,
)
from backend.app.git.state import GitStateTracker
from backend.app.execution._process import CapturedProcess
from backend.tests.support_kb import git, make_repo, write


def _case(tmp_path: Path, *, unrelated_tests: int = 1) -> tuple[Path, ChangeView, object, object]:
    test_source = (
        "import pytest\nfrom module import old\n\n"
        f"@pytest.mark.parametrize('case', range({unrelated_tests}))\n"
        "def test_old(case):\n    assert old() == 1\n"
    )
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "def old():\n    return 1\n\ndef new():\n    return 1\n",
        "tests/test_old.py": test_source,
    })
    change = ChangeView(id=uuid4(), title="coverage", intent="measure", repository_path=str(root),
                        created_at=utc_now(), updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", "def old():\n    return 1\n\ndef new():\n    return 2\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    return root, change, baseline, tested


def _request(baseline: object, tested: object, *, required: bool = False) -> DiffCoverageRequest:
    return DiffCoverageRequest(baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
                               interpreter_path=sys.executable, test_args=["-q"],
                               rule=DiffCoverageRule(required=required, minimum_percent=80))


def test_unrelated_passing_suite_reports_zero_exercise_and_uncovered_lines(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path, unrelated_tests=200)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    assert result.checks_passed is True
    assert result.diff_exercised == "FAIL"
    assert result.executed_changed_lines == 0
    assert result.changed_executable_lines and result.changed_executable_lines > 0
    assert result.files[0].uncovered_lines
    assert result.freshness == "CURRENT"
    assert result.collection_boundary == "UNCONFINED_IN_PROCESS"
    assert "influence coverage data" in result.collection_caveat
    assert result.collector_version
    assert result.run_ids == []
    assert result.artifact_retained is False


def test_new_passing_tests_cannot_cover_unexecuted_production_diff(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "tests/test_unrelated.py", "import pytest\n\n"
          "@pytest.mark.parametrize('case', range(20))\n"
          "def test_unrelated(case):\n    assert case >= 0\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "FAIL"
    assert result.executed_changed_lines == 0
    assert result.gate_satisfied is False
    assert result.excluded["tests/test_unrelated.py"] == "test code"


def test_new_untracked_untested_source_lists_its_uncovered_lines(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "new_feature.py", "def untested():\n    return 42\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    file = next(item for item in result.files if item.path == "new_feature.py")
    assert file.uncovered_lines == [1, 2] or file.uncovered_lines == [2]
    assert result.diff_exercised == "FAIL"


def test_executed_without_assertion_is_not_verified(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    write(root, "tests/test_old.py", "from module import new\n\ndef test_new():\n    new()\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    assert result.executed_changed_lines and result.executed_changed_lines > 0
    assert result.assertion_quality == "NOT_MEASURED"
    assert result.caveat == "executed ≠ verified"


def test_failed_pytest_can_measure_execution_but_never_open_required_gate(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "tests/test_old.py", "from module import new\n\ndef test_failure():\n"
          "    assert new() == 999\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is False
    assert result.executed_changed_lines and result.executed_changed_lines > 0
    assert result.gate_satisfied is False


def test_changed_pragma_exclusions_count_as_uncovered(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "module.py", "def old():\n    return 1\n\ndef new():  # pragma: no cover\n"
          "    return 2\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "FAIL"
    assert result.gate_satisfied is False
    assert result.files[0].excluded_by_pragma_lines
    assert set(result.files[0].excluded_by_pragma_lines) <= set(result.files[0].uncovered_lines)
    assert result.files[0].reason == "excluded-by-pragma"


def test_rename_and_untracked_source_use_new_paths(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    git(root, "add", "module.py")
    git(root, "commit", "-q", "-m", "new code")
    git(root, "mv", "module.py", "renamed.py")
    write(root, "extra.py", "answer = 42\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert "renamed.py" in mapped.lines
    assert mapped.lines["extra.py"] == {1}


def test_truncated_diff_is_unknown(tmp_path: Path) -> None:
    _, change, baseline, tested = _case(tmp_path)
    tested = tested.model_copy(update={"summary": tested.summary.model_copy(update={"patch_truncated": True})})
    assert map_diff(baseline=baseline, tested=tested).error


def test_wrong_commit_and_required_unknown_fail_closed(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    write(root, "module.py", "def changed():\n    return 3\n")
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "STALE"
    assert result.gate_satisfied is False


def test_test_run_mutation_is_stale(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    write(root, "tests/test_old.py", "from pathlib import Path\n\ndef test_mutate():\n    Path('module.py').write_text('x = 3\\n')\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "STALE"
    assert result.freshness == "STALE"
    assert result.gate_satisfied is False


def test_pytest_does_not_create_cache_files_in_unignored_repository(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        "module.py": "def value():\n    return 1\n",
        "tests/test_module.py": "from module import value\n\ndef test_value():\n"
                                "    assert value() == 1\n",
    })
    change = ChangeView(id=uuid4(), title="cache", intent="measure", repository_path=str(root),
                        created_at=utc_now(), updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", "def value():\n    return 1\n\ndef unused():\n    return 2\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    assert result.checks_passed is True
    assert result.freshness == "CURRENT"
    assert not (root / ".pytest_cache").exists()
    assert not (root / "__pycache__").exists()


def test_deletion_only_file_does_not_require_coverage_record(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        "unused.py": "value = 1\nremoved = 2\n",
        "tests/test_trivial.py": "def test_trivial():\n    assert True\n",
    })
    change = ChangeView(id=uuid4(), title="delete", intent="measure", repository_path=str(root),
                        created_at=utc_now(), updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "unused.py", "value = 1\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    assert map_diff(baseline=baseline, tested=tested).lines == {}
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    assert result.checks_passed is True
    assert result.diff_exercised == "NOT_APPLICABLE"


def test_committed_staged_unstaged_and_classified_files(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    git(root, "add", "module.py")
    git(root, "commit", "-q", "-m", "committed")
    write(root, "staged.py", "staged = 1\n")
    git(root, "add", "staged.py")
    write(root, "module.py", "def old():\n    return 1\n\ndef new():\n    return 3\n")
    write(root, "settings.toml", "enabled = true\n")
    write(root, "generated/output.py", "# Generated by fixture\nvalue = 1\n")
    write(root, "src/build/core.py", "handwritten = 1\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert "module.py" in mapped.lines
    assert "staged.py" in mapped.lines
    assert mapped.excluded["settings.toml"] == "configuration"
    assert mapped.excluded["generated/output.py"] == "generated"
    assert mapped.lines["src/build/core.py"] == {1}


def test_generated_header_cannot_be_omitted_from_required_gate(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "generated/output.py", "# Generated by fixture\nvalue = 1\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert result.excluded["generated/output.py"] == "generated"


def test_oversized_report_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, change, baseline, tested = _case(tmp_path)
    monkeypatch.setattr("backend.app.assurance.diff_coverage.ARTIFACT_LIMIT", 1)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert "oversized" in result.reasons[0]


def test_evidence_config_write_failure_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, change, baseline, tested = _case(tmp_path)
    original = Path.write_text

    def fail_config(path: Path, *args: object, **kwargs: object) -> int:
        if path.name == "coveragerc":
            raise OSError("synthetic evidence directory failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_config)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.checks_passed is None
    assert result.gate_satisfied is False
    assert "OSError" in result.reasons[0]


def test_recursive_report_json_is_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, change, baseline, tested = _case(tmp_path)

    def recursive_json(_: bytes) -> object:
        raise RecursionError("synthetic deeply nested report")

    monkeypatch.setattr("backend.app.assurance.diff_coverage.json.loads", recursive_json)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert "RecursionError" in result.reasons[0]


def test_oversized_line_model_returns_unknown_instead_of_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, change, baseline, tested = _case(tmp_path)

    def oversized_model(**kwargs: object) -> DiffCoverageResult:
        raise ValueError("synthetic result bound")

    monkeypatch.setattr("backend.app.assurance.diff_coverage.evaluate_report", oversized_model)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert "ValueError" in result.reasons[0]


def test_missing_coverage_tool_keeps_checks_passed_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, change, baseline, tested = _case(tmp_path)

    def no_coverage(*args: object, **kwargs: object) -> CapturedProcess:
        return CapturedProcess(returncode=1, stdout=b"", stderr=b"No module named coverage",
                               truncated=False, timed_out=False, incomplete=False,
                               stdout_digest="0" * 64)

    monkeypatch.setattr("backend.app.assurance.diff_coverage.run_verification_command", no_coverage)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is None
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False


def test_malformed_exported_artifact_is_unknown_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.app.execution.commands import run_verification_command as real_command

    root, change, baseline, tested = _case(tmp_path)

    def malformed_export(argv: list[str], **kwargs: object) -> CapturedProcess:
        if "json" in argv:
            Path(argv[argv.index("-o") + 1]).write_text("{malformed", encoding="utf-8")
            return CapturedProcess(returncode=0, stdout=b"", stderr=b"", truncated=False,
                                   timed_out=False, incomplete=False, stdout_digest="0" * 64)
        return real_command(argv, **kwargs)

    monkeypatch.setattr("backend.app.assurance.diff_coverage.run_verification_command", malformed_export)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False


def test_unsupported_source_is_listed_and_unknown_when_alone(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        "tests/test_trivial.py": "def test_trivial():\n    assert True\n",
    })
    change = ChangeView(id=uuid4(), title="ts", intent="measure", repository_path=str(root),
                        created_at=utc_now(), updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "app.ts", "export const value = 1;\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    assert result.diff_exercised == "UNKNOWN"
    assert result.excluded["app.ts"] == "unsupported language"


def test_missing_malformed_and_unsupported_reports_are_unknown(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    request = _request(baseline, tested, required=True)
    initial = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        head_sha=tested.head_sha, status_digest=tested.status_digest, contract_digest="0" * 64,
        started_at=utc_now(), completed_at=utc_now(), collector_status="COLLECTED",
        diff_exercised="UNKNOWN", freshness="CURRENT", gate_satisfied=False,
    )
    for report in ({}, {"files": {}}, {"files": {"module.py": {"executed_lines": "bad"}}}):
        result = evaluate_report(result=initial, changed={"module.py": {4, 5}}, excluded={},
                                 report=report, root=root, rule=request)
        assert result.diff_exercised == "UNKNOWN"
        assert result.gate_satisfied is False
    unsupported = evaluate_report(result=initial, changed={}, excluded={"app.ts": "unsupported language or non-source file"},
                                  report={"files": {}}, root=root, rule=request)
    assert unsupported.diff_exercised == "UNKNOWN"
    empty = evaluate_report(result=initial, changed={}, excluded={}, report={"files": {}},
                            root=root, rule=request)
    assert empty.diff_exercised == "NOT_APPLICABLE"


def test_documentation_only_diff_is_not_applicable_when_policy_allows_it(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    initial = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        head_sha=tested.head_sha, status_digest=tested.status_digest, contract_digest="0" * 64,
        started_at=utc_now(), completed_at=utc_now(), collector_status="COLLECTED",
        checks_passed=True, diff_exercised="UNKNOWN", freshness="CURRENT",
    )
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        rule=DiffCoverageRule(required=True, minimum_percent=80,
                              not_applicable_satisfies=True),
    )
    measured = evaluate_report(result=initial, changed={}, excluded={"README.md": "documentation"},
                               report={"files": {}}, root=root, rule=request)
    assert measured.diff_exercised == "NOT_APPLICABLE"
    assert measured.gate_satisfied is True


def test_advisory_threshold_is_reported_and_used(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    initial = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        head_sha=tested.head_sha, status_digest=tested.status_digest, contract_digest="0" * 64,
        started_at=utc_now(), completed_at=utc_now(), collector_status="COLLECTED",
        checks_passed=True, diff_exercised="UNKNOWN", freshness="CURRENT",
    )
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        rule=DiffCoverageRule(minimum_percent=80),
    )
    measured = evaluate_report(
        result=initial, changed={"module.py": set(range(1, 21))}, excluded={},
        report={"files": {"module.py": {
            "executed_lines": list(range(1, 20)), "missing_lines": [20],
        }}}, root=root, rule=request,
    )
    assert measured.measured_percent == 95
    assert measured.threshold == 80
    assert measured.diff_exercised == "PASS"
    assert measured.gate_satisfied is None
