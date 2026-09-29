"""Real repository and coverage acceptance cases for diff-linked assurance."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.assurance.diff_coverage import (
    _trusted_interpreter_path, collect_diff_coverage, evaluate_report,
)
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


def test_required_gate_cannot_silently_exclude_test_named_production_module(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "module.py", "def old():\n    return 1 + 0\n\ndef new():\n    return 1\n")
    write(root, "pricing_test.py", "def charge():\n    return 999\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.excluded["pricing_test.py"] == "test code"
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False


def test_new_untracked_untested_source_lists_its_uncovered_lines(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "new_feature.py", "def untested():\n    return 42\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested))
    file = next(item for item in result.files if item.path == "new_feature.py")
    assert file.uncovered_lines == [1, 2] or file.uncovered_lines == [2]
    assert result.diff_exercised == "FAIL"


def test_info_exclude_cannot_hide_new_source(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "hidden_logic.py", "def untested():\n    return 42\n")
    (root / ".git" / "info" / "exclude").write_text("hidden_logic.py\n", encoding="utf-8")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert mapped.lines["hidden_logic.py"] == {1, 2}
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert result.excluded["hidden_logic.py"] == "untracked outside checkpoint"


def test_modified_gitignore_cannot_hide_new_source(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, ".gitignore", "__pycache__/\n.pytest_cache/\nhidden_logic.py\n")
    write(root, "hidden_logic.py", "def untested():\n    return 42\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert result.excluded[".gitignore"] == "ignore rules changed"


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


def test_collect_only_addopts_cannot_claim_passing_checks(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--collect-only"\n')
    write(root, "module.py", "def old():\n    return 2\n\ndef new():\n    return 2\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert "addopts=" in result.command
    assert result.checks_passed is False
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


def test_unexecuted_multiline_continuation_never_gets_inferred_credit(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "module.py", "def old():\n    return 1\n\ndef new():\n"
          "    return max(\n        __import__('os').getpid())\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised in {"FAIL", "UNKNOWN"}
    assert result.gate_satisfied is False
    assert (6 in result.files[0].uncovered_lines
            or any("module.py:6" in reason for reason in result.reasons))


@pytest.mark.parametrize("baseline_source,changed_source", [
    (
        "def old():\n    flag = False\n    if flag:\n        return 2\n    return 1\n",
        "def old():\n    flag = False\n    if flag:\n"
        "        # one\n        # two\n        # three\n        # four\n"
        "        return 3\n    return 1\n",
    ),
    (
        "def old():\n    return 1\n\ndef rarely():\n    return 2\n",
        "def old():\n    return 1\n\ndef rarely():\n"
        "    # a\n    # b\n    # c\n    # d\n    return 3\n",
    ),
    (
        "def old():\n    try:\n        return 1\n    except ValueError:\n        return 2\n",
        "def old():\n    try:\n        return 1\n    except (ValueError, TypeError):\n        return 2\n",
    ),
    (
        "def old():\n    match 1:\n        case 1:\n            return 1\n"
        "        case 2:\n            return 2\n",
        "def old():\n    match 1:\n        case 1:\n            return 1\n"
        "        case 2 | 3:\n            return 2\n",
    ),
])
def test_changed_lines_never_inherit_compound_header_execution(
    tmp_path: Path, baseline_source: str, changed_source: str,
) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": baseline_source,
        "tests/test_old.py": "from module import old\n\ndef test_old():\n    assert old() == 1\n",
    })
    change = ChangeView(id=uuid4(), title="line credit", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", changed_source)
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised != "PASS"
    assert result.gate_satisfied is False


def test_self_ignoring_untracked_gitignore_cannot_hide_imported_source(
    tmp_path: Path,
) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "pkg/__init__.py": "",
        "pkg/module.py": "def old():\n    return 1\n",
        "module.py": "from pkg.module import old\n",
        "tests/test_old.py": "from module import old\n\ndef test_old():\n    assert old() == 1\n",
    })
    change = ChangeView(id=uuid4(), title="hidden source", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "pkg/.gitignore", ".gitignore\nhidden_impl.py\n")
    write(root, "pkg/hidden_impl.py", "def charge(x):\n    return x * 2\n")
    write(root, "pkg/module.py", "from pkg import hidden_impl\n\ndef old():\n    return 1\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert mapped.excluded["pkg/.gitignore"] == "ignore rules changed"
    assert mapped.excluded["pkg/hidden_impl.py"] == "untracked outside checkpoint"
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False


def test_repo_pytest_collection_rules_cannot_hide_failing_tests(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "LIMIT = 5\n\ndef old():\n    return 1\n",
        "tests/test_old.py": "from module import LIMIT, old\n\ndef test_old():\n"
                             "    assert old() == 1\n\ndef test_limit():\n"
                             "    assert LIMIT == 5\n",
    })
    change = ChangeView(id=uuid4(), title="pytest config", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", "LIMIT = 50\n\ndef old():\n    return 1\n")
    write(root, "pyproject.toml", '[tool.pytest.ini_options]\npython_functions = "test_old"\n')
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is False
    assert result.gate_satisfied is False
    assert any("sentinel-pytest.ini" in token for token in result.command)


def test_new_test_file_can_satisfy_required_gate_when_it_covers_new_code(
    tmp_path: Path,
) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "def old():\n    return 1\n",
        "tests/test_old.py": "from module import old\n\ndef test_old():\n    assert old() == 1\n",
    })
    change = ChangeView(id=uuid4(), title="new test", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", "def old():\n    return 1\n\ndef new(x):\n    return x + 1\n")
    write(root, "tests/test_new.py", "from module import new\n\ndef test_new():\n"
                                      "    assert new(1) == 2\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "PASS", result.reasons
    assert result.gate_satisfied is True
    assert result.excluded["tests/test_new.py"] == "test code"


def test_collected_test_module_imported_by_production_cannot_hide_logic(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "def old():\n    return 1\n",
        "tests/__init__.py": "",
        "tests/test_old.py": "from module import old\n\ndef test_old():\n    assert old() == 1\n",
    })
    change = ChangeView(id=uuid4(), title="test helper", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "tests/test_helpers.py", "def test_dummy():\n    assert True\n\n"
          "def compute(x):\n    if x > 100:\n"
          "        return __import__('shutil').rmtree('x')\n    return x\n")
    write(root, "module.py", "from tests.test_helpers import compute\n\n"
          "def old():\n    return 1\n\ndef price(x):\n    return compute(x)\n")
    write(root, "tests/test_price.py", "from module import price\n\n"
          "def test_price():\n    assert price(5) == 5\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert any("tests/test_helpers.py" in reason and
               ("production-shaped" in reason or "Production source imports" in reason)
               for reason in result.reasons)


def test_preexisting_ignored_editor_and_environment_files_do_not_block_gate(
    tmp_path: Path,
) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "def old():\n    return 1\n",
        "tests/test_old.py": "from module import old\n\ndef test_old():\n    assert old() == 1\n",
    })
    (root / ".git" / "info" / "exclude").write_text(
        ".vscode/\n.venv/\n", encoding="utf-8")
    write(root, ".vscode/settings.json", "{}\n")
    write(root, ".venv/lib/site-packages/dependency.py", "VALUE = 1\n")
    change = ChangeView(id=uuid4(), title="ignored editor", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    write(root, "module.py", "def old():\n    return 1  # covered edit\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "PASS", result.reasons
    assert result.gate_satisfied is True


def test_zero_executed_tests_cannot_report_diff_exercised_pass(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "module.py", "def old():\n    return 1\n\ndef new():\n"
          "    return 1\n\nFLAG = 1  # executed during collection\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        interpreter_path=sys.executable, test_args=["--collect-only", "-q"],
    )
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=request)
    assert result.checks_passed is None
    assert result.diff_exercised == "UNKNOWN"
    assert any("did not execute any tests" in reason for reason in result.reasons)


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


def test_truncated_tested_checkpoint_is_unknown_before_freshness_comparison(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1)
    assert tested.summary.patch_truncated
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True),
                                   patch_limit=1)
    assert result.diff_exercised == "UNKNOWN"
    assert result.freshness == "UNKNOWN"
    assert "truncated" in result.reasons[0]


def test_wrong_commit_and_required_unknown_fail_closed(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    write(root, "module.py", "def changed():\n    return 3\n")
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.diff_exercised == "STALE"
    assert result.gate_satisfied is False


def test_repository_venv_executable_is_not_trusted(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    binary = root / ".venv" / "Scripts" / "python.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"agent-chosen executable")
    assert not _trusted_interpreter_path(str(binary), root)


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


def test_deleted_binary_asset_does_not_abort_python_mapping(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        "logo.png": "PNG\x00binary",
        "module.py": "VALUE = 1\n",
    })
    change = ChangeView(id=uuid4(), title="binary delete", intent="measure",
                        repository_path=str(root), created_at=utc_now(), updated_at=utc_now(),
                        review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    (root / "logo.png").unlink()
    write(root, "module.py", "VALUE = 2\n")
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert mapped.excluded["logo.png"] == "binary"
    assert mapped.lines["module.py"] == {1}


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


def test_unmeasured_script_stays_unknown_with_docs_only_gate(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    write(root, "module.py", "def old():\n    return 1\n\ndef new():\n    return 1\n")
    write(root, "deploy.ps1", "Write-Output hello\n")
    write(root, "tool.pyw", "print('hello')\n")
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        rule=DiffCoverageRule(required=True, minimum_percent=80,
                              not_applicable_satisfies=True),
    )
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=request)
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    assert result.excluded["deploy.ps1"] == "unsupported language"


def test_unknown_source_extensions_cannot_use_docs_only_gate(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {
        "tests/test_trivial.py": "def test_trivial():\n    assert True\n",
    })
    change = ChangeView(id=uuid4(), title="unknown source", intent="measure",
                        repository_path=str(root), created_at=utc_now(),
                        updated_at=utc_now(), review_state=ReviewState.MISSING_EVIDENCE)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    for path, content in {
        "Deploy.psm1": "function Invoke-Deploy { return 1 }\n",
        "run.vbs": "WScript.Echo 1\n",
        "Dockerfile": "FROM scratch\n",
        "README.md": "Documentation.\n",
        "package-lock.json": "{}\n",
    }.items():
        write(root, path, content)
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        rule=DiffCoverageRule(required=True, minimum_percent=80,
                              not_applicable_satisfies=True),
    )
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=request)
    assert result.checks_passed is True
    assert result.diff_exercised == "UNKNOWN"
    assert result.gate_satisfied is False
    for path in ("Deploy.psm1", "run.vbs", "Dockerfile"):
        assert result.excluded[path] == "unsupported language"
    assert result.excluded["README.md"] == "documentation"
    assert result.excluded["package-lock.json"] == "lockfile"


@pytest.mark.parametrize("path,classification,phrase", [
    ("Deploy.psm1", "unsupported language", "Unsupported or unmeasured"),
    ("hidden.py", "untracked outside checkpoint", "outside the checkpoint"),
    ("pkg/.gitignore", "ignore rules changed", "ignore rules"),
    ("generated.py", "generated", "Generated Python"),
    ("pricing_test.py", "test code", "not a collected test"),
])
def test_unknown_overrides_explain_their_cause(
    tmp_path: Path, path: str, classification: str, phrase: str,
) -> None:
    root, change, baseline, tested = _case(tmp_path)
    initial = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=baseline.id,
        tested_checkpoint_id=tested.id, head_sha=tested.head_sha,
        status_digest=tested.status_digest, contract_digest="0" * 64,
        started_at=utc_now(), completed_at=utc_now(),
        collector_status="COLLECTED", collector_version="7.0",
        checks_passed=True, diff_exercised="UNKNOWN", freshness="CURRENT",
        gate_satisfied=False,
    )
    result = evaluate_report(
        result=initial, changed={}, excluded={path: classification},
        report={"files": {}}, root=root, rule=_request(baseline, tested, required=True),
    )
    assert result.diff_exercised == "UNKNOWN"
    assert any(phrase in reason and path in reason for reason in result.reasons)


def test_utf8_bom_python_source_is_measured(tmp_path: Path) -> None:
    root, change, baseline, _ = _case(tmp_path)
    (root / "module.py").write_bytes(
        b"\xef\xbb\xbfdef old():\n    return 1  # covered edit\n\n"
        b"def new():\n    return 1\n"
    )
    tested = GitStateTracker().capture(change.id, "tested", str(root), 1, 1_048_576)
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=_request(baseline, tested, required=True))
    assert result.checks_passed is True
    assert result.diff_exercised == "PASS", result.reasons
    assert result.gate_satisfied is True


def test_in_repo_junction_to_external_python_is_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    lexical = root / ".venv" / Path(sys.executable).name
    original_resolve = Path.resolve

    def junction_resolve(self: Path, *args, **kwargs) -> Path:
        if self == lexical:
            return Path(sys.executable).resolve()
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", junction_resolve)
    assert not _trusted_interpreter_path(str(lexical), root)


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


def test_result_revalidates_collector_version_before_persistence(tmp_path: Path) -> None:
    root, change, baseline, tested = _case(tmp_path)
    invalid = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        head_sha=tested.head_sha, status_digest=tested.status_digest, contract_digest="0" * 64,
        started_at=utc_now(), completed_at=utc_now(), collector_status="COLLECTED",
        checks_passed=True, diff_exercised="UNKNOWN", freshness="CURRENT",
    ).model_copy(update={"collector_version": ""})
    with pytest.raises(ValueError, match="collector_version"):
        evaluate_report(result=invalid, changed={"module.py": {5}}, excluded={},
                        report={"files": {"module.py": {
                            "executed_lines": [], "missing_lines": [5],
                        }}}, root=root, rule=_request(baseline, tested, required=True))


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
    write(root, "module.py", "".join(f"LINE_{number} = {number}\n" for number in range(1, 21)))
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
