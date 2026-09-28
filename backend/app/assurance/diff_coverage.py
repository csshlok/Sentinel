"""Collect bounded pytest coverage and evaluate it against an exact diff."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.app.assurance.diff_map import map_diff
from backend.app.contracts.models import (
    ChangeView, DiffCoverageFile, DiffCoverageRequest, DiffCoverageResult, GitCheckpoint, utc_now,
)
from backend.app.assurance.engine import contract_digest
from backend.app.execution.commands import run_verification_command
from backend.app.git.state import GitStateTracker

ARTIFACT_LIMIT = 8_388_608
_PYTHON_EXECUTABLE = re.compile(r"python(?:3(?:\.\d+)?)?w?(?:\.exe)?$", re.I)


def _trusted_interpreter_path(raw: str, root: Path) -> bool:
    """Reject remote, wrapper and repository-chosen executables before probing them."""

    if os.name == "nt" and (raw.startswith(("\\\\", "//", "\\\\?\\"))
                            or not re.match(r"^[A-Za-z]:[\\/]", raw)):
        return False
    path = Path(raw)
    if not path.is_absolute() or _PYTHON_EXECUTABLE.fullmatch(path.name) is None:
        return False
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            return False
        resolved.relative_to(root.resolve())
    except ValueError:
        return True  # trusted local Python outside the agent-writable repository
    except OSError:
        return False
    return False


def _report_path(root: Path, raw: str) -> str | None:
    path = Path(raw)
    try:
        relative = (path if path.is_absolute() else root / path).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return relative.as_posix()


def evaluate_report(
    *, result: DiffCoverageResult, changed: dict[str, set[int]],
    excluded: dict[str, str], report: dict[str, object], root: Path,
    rule: DiffCoverageRequest,
    collected_test_paths: set[str] | None = None,
) -> DiffCoverageResult:
    """Pure report comparison; missing or inconsistent file records remain UNKNOWN."""

    raw_files = report.get("files")
    if not isinstance(raw_files, dict):
        return result.model_copy(update={"reasons": ["Coverage report has no files."],
                                         "excluded": excluded})
    files: dict[str, dict[str, object]] = {}
    for raw, item in raw_files.items():
        if not isinstance(raw, str) or not isinstance(item, dict):
            return result.model_copy(update={"reasons": ["Malformed coverage file record."]})
        path = _report_path(root, raw)
        if path is not None:
            files[path] = item
    measured: list[DiffCoverageFile] = []
    total = executed_total = 0
    unmeasured_code: list[str] = []
    for path, lines in sorted(changed.items()):
        item = files.get(path)
        if item is None:
            return result.model_copy(update={"reasons": [f"Coverage omitted changed source: {path}."],
                                             "excluded": excluded})
        executed = item.get("executed_lines")
        missing = item.get("missing_lines")
        pragma_excluded = item.get("excluded_lines", [])
        if (not isinstance(executed, list) or not isinstance(missing, list)
                or not isinstance(pragma_excluded, list)
                or any(type(n) is not int or n < 1
                       for n in executed + missing + pragma_excluded)):
            return result.model_copy(update={"reasons": [f"Malformed coverage lines: {path}."],
                                             "excluded": excluded})
        source_lines = (root / path).read_text(encoding="utf-8-sig").splitlines()
        executable = set(executed) | set(missing) | set(pragma_excluded)
        target = lines & executable
        excluded_changed = target & set(pragma_excluded)
        hit = target & set(executed) - excluded_changed
        for line in sorted(lines - executable):
            if line > len(source_lines):
                unmeasured_code.append(f"{path}:{line}")
                continue
            stripped = source_lines[line - 1].strip()
            if stripped and not stripped.startswith("#"):
                unmeasured_code.append(f"{path}:{line}")
        total += len(target)
        executed_total += len(hit)
        measured.append(DiffCoverageFile(
            path=path, changed_lines=sorted(lines), executable_lines=sorted(target),
            executed_lines=sorted(hit), uncovered_lines=sorted(target - hit),
            excluded_by_pragma_lines=sorted(excluded_changed),
            reason="excluded-by-pragma" if excluded_changed else None,
        ))
    unsupported = any(v.startswith("unsupported language") for v in excluded.values())
    if not changed and excluded:
        state = "UNKNOWN" if unsupported else "NOT_APPLICABLE"
    elif total == 0:
        state = "UNKNOWN" if unsupported else "NOT_APPLICABLE"
    else:
        minimum = rule.rule.minimum_percent or 100.0
        percent = 100.0 * executed_total / total
        per_file_ok = not rule.rule.per_file or all(
            not f.executable_lines or 100.0 * len(f.executed_lines) / len(f.executable_lines) >= minimum
            for f in measured
        )
        state = "PASS" if percent >= minimum and per_file_ok else "FAIL"
    if unmeasured_code:
        state = "UNKNOWN"
    if unsupported and state == "PASS":
        state = "UNKNOWN"
    if any(reason in {"untracked outside checkpoint", "ignore rules changed"}
           for reason in excluded.values()):
        state = "UNKNOWN"
    if rule.rule.required and any(
        path.lower().endswith(".py") and reason == "generated"
        for path, reason in excluded.items()
    ):
        state = "UNKNOWN"
    uncollected_test_code = [path for path, reason in excluded.items()
                             if path.lower().endswith(".py") and reason == "test code"
                             and path not in (collected_test_paths or set())]
    if rule.rule.required and state in {"PASS", "NOT_APPLICABLE"} and uncollected_test_code:
        state = "UNKNOWN"
    gate = ((state == "PASS" or (state == "NOT_APPLICABLE" and rule.rule.not_applicable_satisfies))
            and result.checks_passed is True) if rule.rule.required else None
    return DiffCoverageResult.model_validate({**result.model_dump(), **{
        "files": measured, "excluded": excluded, "diff_exercised": state,
        "reasons": [*result.reasons, *(["Changed code lines lack exact coverage data: "
                                    + ", ".join(unmeasured_code[:8]) + "."]
                                   if unmeasured_code else []),
                    *(["Changed test-named Python file is not a collected test: "
                       + ", ".join(uncollected_test_code[:8]) + "."]
                      if rule.rule.required and uncollected_test_code else [])],
        "threshold": rule.rule.minimum_percent or 100.0,
        "measured_percent": (100.0 * executed_total / total) if total else None,
        "changed_executable_lines": total, "executed_changed_lines": executed_total,
        "gate_satisfied": gate,
    }})


def collect_diff_coverage(
    *, change: ChangeView, baseline: GitCheckpoint, tested: GitCheckpoint,
    request: DiffCoverageRequest, git_state: GitStateTracker | None = None,
    patch_limit: int = 1_048_576,
) -> DiffCoverageResult:
    """Run coverage in a disposable evidence directory and recapture state afterward."""

    started = utc_now()
    root = Path(tested.repository_root)
    interpreter = (request.rule.interpreter_path or sys.executable) if request.rule.required else (request.interpreter_path or sys.executable)
    test_args = request.rule.test_args if request.rule.required else request.test_args
    command = [interpreter, "-m", "coverage", "run", "-m", "pytest", *test_args]
    result = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        head_sha=tested.head_sha, status_digest=tested.status_digest,
        contract_digest=contract_digest(change), command=command,
        started_at=started, completed_at=started, collector_status="NOT_STARTED",
        diff_exercised="UNKNOWN", freshness="UNKNOWN",
        threshold=request.rule.minimum_percent or 100.0,
        policy_version=request.rule.policy_version,
        collection_caveat=(
            "Tests and coverage share a process at user authority; agent-authored code can "
            "influence coverage data. The external Python interpreter is trusted by path, "
            "not by a verified publisher or binary digest."
        ),
        gate_satisfied=False if request.rule.required else None,
        reasons=["Measurement did not complete."],
    )
    tracker = git_state or GitStateTracker()
    if (baseline.change_id != change.id or tested.change_id != change.id
            or baseline.id != request.baseline_checkpoint_id
            or tested.id != request.tested_checkpoint_id):
        return result.model_copy(update={"reasons": ["Checkpoint identity mismatch."]})
    if tested.summary.patch_truncated or baseline.summary.patch_truncated:
        return result.model_copy(update={"reasons": ["Checkpoint patch was truncated; mapping is unknown."]})
    if not _trusted_interpreter_path(interpreter, root):
        return result.model_copy(update={"reasons": ["Project interpreter is unavailable or disallowed."]})
    try:
        before = tracker.capture(change.id, "diff-pre-run", str(root),
                                 tested.evidence_revision, patch_limit)
    except Exception as exc:
        return result.model_copy(update={"reasons": [f"Pre-run capture failed: {type(exc).__name__}."]})
    if before.head_sha != tested.head_sha or before.status_digest != tested.status_digest:
        return result.model_copy(update={"freshness": "STALE", "diff_exercised": "STALE",
                                         "reasons": ["Repository differs from tested checkpoint."]})
    mapped = map_diff(baseline=baseline, tested=tested)
    if mapped.error:
        return result.model_copy(update={"freshness": "CURRENT", "reasons": [mapped.error]})
    if len(mapped.lines) > 10000 or len(mapped.excluded) > 10000:
        return result.model_copy(update={"freshness": "CURRENT",
                                         "reasons": ["Diff contains too many paths to measure safely."]})
    report: dict[str, object] | None = None
    artifact_digest: str | None = None
    checks_passed: bool | None = None
    collected_test_paths: set[str] = set()
    collector_status = "ERROR"
    reasons: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="sentinel-diff-") as temporary:
            evidence = Path(temporary)
            config = evidence / "coveragerc"
            data = evidence / "coverage.data"
            artifact = evidence / "coverage.json"
            junit = evidence / "pytest-results.xml"
            pytest_config = evidence / "sentinel-pytest.ini"
            config.write_text(f"[run]\nsource = {root.as_posix()}\n", encoding="utf-8")
            pytest_config.write_text(
                "[pytest]\naddopts =\npython_files = test_*.py *_test.py\n"
                "python_classes = Test*\npython_functions = test_*\n"
                "testpaths =\nnorecursedirs = .git .venv venv node_modules "
                ".tox .nox __pycache__\n",
                encoding="utf-8",
            )
            argv = [interpreter, "-X", f"pycache_prefix={evidence / 'pycache'}",
                    "-m", "coverage", "run", "--rcfile", str(config),
                    "--data-file", str(data), "-m", "pytest", "-p", "no:cacheprovider",
                    *test_args, "-c", str(pytest_config), f"--rootdir={root}",
                    "-o", "addopts=", f"--junitxml={junit}"]
            result = result.model_copy(update={"command": argv})
            run = run_verification_command(argv, cwd=root, timeout=300, limit=262_144)
            if run.timed_out or run.incomplete:
                reasons.append("Test command timed out or output capture was incomplete.")
            elif not data.is_file():
                reasons.append("Coverage data is missing; test execution could not be confirmed.")
            else:
                if not junit.is_file() or junit.stat().st_size > ARTIFACT_LIMIT:
                    reasons.append("Pytest execution report is missing or oversized.")
                else:
                    suite = ET.fromstring(junit.read_bytes())
                    if suite.tag == "testsuites":
                        suites = list(suite.findall("testsuite"))
                    elif suite.tag == "testsuite":
                        suites = [suite]
                    else:
                        suites = []
                    executed_tests = sum(int(item.attrib["tests"]) - int(item.attrib.get("skipped", 0))
                                         for item in suites)
                    for case in suite.iter("testcase"):
                        file_attr = case.attrib.get("file")
                        if file_attr:
                            normalized = _report_path(root, file_attr)
                            if normalized:
                                collected_test_paths.add(normalized)
                        classname = case.attrib.get("classname", "")
                        if classname and all(part.isidentifier() for part in classname.split(".")):
                            collected_test_paths.add(classname.replace(".", "/") + ".py")
                    if executed_tests <= 0:
                        reasons.append("Pytest did not execute any tests.")
                    else:
                        checks_passed = run.returncode == 0
                exported = run_verification_command(
                    [interpreter, "-m", "coverage", "json", "--rcfile", str(config),
                     "--data-file", str(data), "-o", str(artifact)],
                    cwd=root, timeout=60, limit=32_768,
                )
                if exported.returncode != 0 or exported.timed_out or exported.incomplete:
                    reasons.append("coverage.py JSON export failed or coverage.py is unavailable.")
                elif not artifact.is_file() or artifact.stat().st_size > ARTIFACT_LIMIT:
                    reasons.append("Coverage report is missing or oversized.")
                else:
                    content = artifact.read_bytes()
                    artifact_digest = hashlib.sha256(content).hexdigest()
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        report = parsed
                        collector_status = "COLLECTED"
                        meta = parsed.get("meta")
                        version = meta.get("version") if isinstance(meta, dict) else None
                        if isinstance(version, str) and 0 < len(version) <= 256:
                            result = result.model_copy(update={"collector_version": version})
                        else:
                            report = None
                            collector_status = "ERROR"
                            reasons.append("Coverage collector version is missing or malformed.")
                    else:
                        reasons.append("Coverage report is malformed.")
    except Exception as exc:
        reasons.append(f"Coverage collection failed: {type(exc).__name__}.")
    try:
        after = tracker.capture(change.id, "diff-post-run", str(root),
                                tested.evidence_revision, patch_limit)
    except Exception as exc:
        return result.model_copy(update={"checks_passed": checks_passed,
                                         "collector_status": collector_status,
                                         "artifact_digest": artifact_digest,
                                         "completed_at": utc_now(),
                                         "reasons": [f"Post-run capture failed: {type(exc).__name__}."]})
    if after.head_sha != tested.head_sha or after.status_digest != tested.status_digest:
        return result.model_copy(update={"checks_passed": checks_passed,
                                         "collector_status": collector_status,
                                         "artifact_digest": artifact_digest,
                                         "completed_at": utc_now(), "freshness": "STALE",
                                         "diff_exercised": "STALE",
                                         "reasons": ["Repository changed during the test run."]})
    result = result.model_copy(update={"checks_passed": checks_passed,
                                       "collector_status": collector_status,
                                       "artifact_digest": artifact_digest,
                                       "completed_at": utc_now(), "freshness": "CURRENT",
                                       "reasons": reasons})
    if report is None:
        return result
    try:
        return evaluate_report(result=result, changed=mapped.lines, excluded=mapped.excluded,
                               report=report, root=root, rule=request,
                               collected_test_paths=collected_test_paths)
    except Exception as exc:
        return result.model_copy(update={
            "collector_status": "ERROR", "diff_exercised": "UNKNOWN",
            "gate_satisfied": False if request.rule.required else None,
            "reasons": [f"Coverage evaluation failed: {type(exc).__name__}."],
        })
