"""Collect bounded pytest coverage and evaluate it against an exact diff."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from backend.app.assurance.diff_map import map_diff
from backend.app.contracts.models import (
    ChangeView, DiffCoverageFile, DiffCoverageRequest, DiffCoverageResult, GitCheckpoint, utc_now,
)
from backend.app.assurance.engine import contract_digest
from backend.app.execution.commands import run_verification_command
from backend.app.git.state import GitStateTracker

ARTIFACT_LIMIT = 8_388_608
PATCH_LIMIT = 1_048_576


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
        excluded_changed = lines & set(pragma_excluded)
        executable = set(executed) | set(missing) | set(pragma_excluded)
        target = lines & executable
        hit = target & set(executed) - excluded_changed
        total += len(target)
        executed_total += len(hit)
        measured.append(DiffCoverageFile(
            path=path, changed_lines=sorted(lines), executable_lines=sorted(target),
            executed_lines=sorted(hit), uncovered_lines=sorted(target - hit),
            excluded_by_pragma_lines=sorted(excluded_changed),
            reason="excluded-by-pragma" if excluded_changed else None,
        ))
    if not changed and excluded:
        state = "UNKNOWN" if any(v == "unsupported language or non-source file" for v in excluded.values()) else "NOT_APPLICABLE"
    elif total == 0:
        state = "NOT_APPLICABLE"
    else:
        minimum = rule.rule.minimum_percent if rule.rule.required else 100.0
        percent = 100.0 * executed_total / total
        per_file_ok = not rule.rule.per_file or all(
            not f.executable_lines or 100.0 * len(f.executed_lines) / len(f.executable_lines) >= minimum
            for f in measured
        )
        state = "PASS" if percent >= minimum and per_file_ok else "FAIL"
    if rule.rule.required and any(
        path.lower().endswith(".py") and reason == "generated"
        for path, reason in excluded.items()
    ):
        state = "UNKNOWN"
    gate = (state == "PASS" and result.checks_passed is True) if rule.rule.required else None
    return result.model_copy(update={
        "files": measured, "excluded": excluded, "diff_exercised": state,
        "measured_percent": (100.0 * executed_total / total) if total else None,
        "changed_executable_lines": total, "executed_changed_lines": executed_total,
        "gate_satisfied": gate,
    })


def collect_diff_coverage(
    *, change: ChangeView, baseline: GitCheckpoint, tested: GitCheckpoint,
    request: DiffCoverageRequest, git_state: GitStateTracker | None = None,
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
        threshold=request.rule.minimum_percent if request.rule.required else None,
        policy_version=request.rule.policy_version if request.rule.required else None,
        gate_satisfied=False if request.rule.required else None,
        reasons=["Measurement did not complete."],
    )
    tracker = git_state or GitStateTracker()
    if (baseline.change_id != change.id or tested.change_id != change.id
            or baseline.id != request.baseline_checkpoint_id
            or tested.id != request.tested_checkpoint_id):
        return result.model_copy(update={"reasons": ["Checkpoint identity mismatch."]})
    if not Path(interpreter).is_absolute() or not Path(interpreter).is_file():
        return result.model_copy(update={"reasons": ["Project interpreter is unavailable."]})
    try:
        before = tracker.capture(change.id, "diff-pre-run", str(root),
                                 tested.evidence_revision, PATCH_LIMIT)
    except Exception as exc:
        return result.model_copy(update={"reasons": [f"Pre-run capture failed: {type(exc).__name__}."]})
    if before.head_sha != tested.head_sha or before.status_digest != tested.status_digest:
        return result.model_copy(update={"freshness": "STALE", "diff_exercised": "STALE",
                                         "reasons": ["Repository differs from tested checkpoint."]})
    mapped = map_diff(baseline=baseline, tested=tested)
    if mapped.error:
        return result.model_copy(update={"freshness": "CURRENT", "reasons": [mapped.error]})
    report: dict[str, object] | None = None
    artifact_digest: str | None = None
    checks_passed: bool | None = None
    collector_status = "ERROR"
    reasons: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sentinel-diff-") as temporary:
        evidence = Path(temporary)
        config = evidence / "coveragerc"
        data = evidence / "coverage.data"
        artifact = evidence / "coverage.json"
        config.write_text(f"[run]\nsource = {root.as_posix()}\n", encoding="utf-8")
        argv = [interpreter, "-X", f"pycache_prefix={evidence / 'pycache'}",
                "-m", "coverage", "run", "--rcfile", str(config),
                "--data-file", str(data), "-m", "pytest", "-p", "no:cacheprovider", *test_args]
        result = result.model_copy(update={"command": argv, "run_ids": [uuid4()]})
        try:
            run = run_verification_command(argv, cwd=root, timeout=300, limit=262_144)
            checks_passed = run.returncode == 0 and not run.timed_out and not run.incomplete
            if run.timed_out or run.incomplete:
                reasons.append("Test command timed out or output capture was incomplete.")
            else:
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
                    else:
                        reasons.append("Coverage report is malformed.")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            reasons.append(f"Coverage collection failed: {type(exc).__name__}.")
    try:
        after = tracker.capture(change.id, "diff-post-run", str(root),
                                tested.evidence_revision, PATCH_LIMIT)
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
    return evaluate_report(result=result, changed=mapped.lines, excluded=mapped.excluded,
                           report=report, root=root, rule=request)
