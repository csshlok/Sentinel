"""Collect bounded pytest coverage and evaluate it against an exact diff."""

from __future__ import annotations

import hashlib
import ast
import json
import os
import re
import stat
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from backend.app.assurance.diff_map import _classification, map_diff
from backend.app.contracts.models import (
    ChangeView, DiffCoverageFile, DiffCoverageRequest, DiffCoverageResult, GitCheckpoint, utc_now,
)
from backend.app.assurance.engine import contract_digest
from backend.app.core.errors import AppError
from backend.app.execution.check_box import CheckBox, CheckBoxes
from backend.app.execution.commands import check_boxes_unavailable
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
        Path(os.path.abspath(raw)).relative_to(Path(os.path.abspath(root)))
    except ValueError:
        pass
    else:
        return False  # lexical in-repo path stays untrusted through a junction
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


def _fixture_definition(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            decorator = decorator.func
        if isinstance(decorator, ast.Name) and decorator.id == "fixture":
            return True
        if (isinstance(decorator, ast.Attribute) and decorator.attr == "fixture"
                and isinstance(decorator.value, ast.Name)
                and decorator.value.id == "pytest"):
            return True
    return False


def _test_module_risk(
    *, root: Path, path: str, changed_lines: set[int], report_paths: set[str],
    changed_production_lines: dict[str, set[int]] | None = None,
) -> str | None:
    """Allow changed test code only within collected test or fixture bodies."""
    source = root / path
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 1_048_576:
        return f"Changed test module cannot be inspected: {path}."
    tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=path)
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            allowed.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                node.name.startswith("test_") or _fixture_definition(node)):
            allowed.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
            for decorator in node.decorator_list:
                allowed.update(range(decorator.lineno, (decorator.end_lineno or decorator.lineno) + 1))
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            allowed.add(node.lineno)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                        child.name.startswith(("test_", "setup_", "teardown_"))
                        or _fixture_definition(child)):
                    allowed.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
                    for decorator in child.decorator_list:
                        allowed.update(range(decorator.lineno, (decorator.end_lineno or decorator.lineno) + 1))
    if (tree.body and isinstance(tree.body[0], ast.Expr) and
            isinstance(tree.body[0].value, ast.Constant) and
            isinstance(tree.body[0].value.value, str)):
        doc = tree.body[0]
        allowed.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    lines = source.read_text(encoding="utf-8-sig").splitlines()
    for line in sorted(changed_lines):
        if line in allowed:
            continue
        if line <= len(lines) and (not lines[line - 1].strip() or
                                   lines[line - 1].lstrip().startswith("#")):
            continue
        return f"Changed test module contains production-shaped code: {path}:{line}."
    module = path.removesuffix(".py").replace("/", ".")
    parent, _, leaf = module.rpartition(".")
    for other in report_paths:
        if other == path or not other.endswith(".py") or _classification(other) == "test code":
            continue
        candidate = root / other
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 1_048_576:
            return f"Production imports of changed test module cannot be checked: {other}."
        production = ast.parse(candidate.read_text(encoding="utf-8-sig"), filename=other)
        for node in ast.walk(production):
            if (changed_production_lines is not None and hasattr(node, "lineno") and
                    bool(set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
                         & changed_production_lines.get(other, set()))):
                if ((isinstance(node, ast.Name) and node.id in {
                        "importlib", "import_module", "__import__", "runpy", "exec", "eval",
                        "spec_from_file_location"}) or
                        (isinstance(node, ast.Attribute) and node.attr in {
                            "modules", "import_module", "spec_from_file_location"} and
                         isinstance(node.value, ast.Name) and node.value.id in {"sys", "importlib"}) or
                        (isinstance(node, ast.ImportFrom) and node.module in {"importlib", "runpy"}) or
                        (isinstance(node, ast.Import) and any(alias.name in {"importlib", "runpy"}
                                                         for alias in node.names))):
                    return f"Changed production source uses dynamic module access: {other}:{node.lineno}."
            if isinstance(node, ast.Import) and any(
                    alias.name == module or alias.name.startswith(module + ".")
                    for alias in node.names):
                return f"Production source imports a changed test module: {other} -> {path}."
            if isinstance(node, ast.ImportFrom):
                importing_package = other.removesuffix(".py").replace("/", ".").rpartition(".")[0]
                parts = importing_package.split(".") if importing_package else []
                if node.level > len(parts) + 1:
                    return f"Production relative import cannot be resolved: {other}."
                prefix = ".".join(parts[:len(parts) - node.level + 1]) if node.level else ""
                imported = ".".join(filter(None, (prefix, node.module))) if node.level else node.module
                if imported == module or (imported == parent and
                                          any(alias.name == leaf for alias in node.names)):
                    return f"Production source imports a changed test module: {other} -> {path}."
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__" and (
                    changed_production_lines is None or bool(set(range(
                        node.lineno, (node.end_lineno or node.lineno) + 1)) &
                        changed_production_lines.get(other, set()))):
                return f"Production source uses a dynamic import: {other}:{node.lineno}."
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and (
                    isinstance(node.func.value, ast.Name) and node.func.value.id == "importlib" and
                    node.func.attr == "import_module" and
                    (changed_production_lines is None or bool(set(range(
                        node.lineno, (node.end_lineno or node.lineno) + 1)) &
                        changed_production_lines.get(other, set())))):
                return f"Production source uses a dynamic import: {other}:{node.lineno}."
    return None


def evaluate_report(
    *, result: DiffCoverageResult, changed: dict[str, set[int]],
    excluded: dict[str, str], report: dict[str, object], root: Path,
    rule: DiffCoverageRequest,
    collected_test_paths: set[str] | None = None,
    excluded_changed_lines: dict[str, set[int]] | None = None,
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
    override_reasons: list[str] = []
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
    unsupported = any(
        reason.startswith("unsupported language") or reason == "configuration"
        or (reason == "binary" and Path(path).suffix.lower() not in {
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif",
            ".svg", ".woff", ".woff2", ".ttf", ".otf",
        })
        for path, reason in excluded.items()
    )
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
        override_reasons.append("Changed code lines lack exact coverage data: "
                                + ", ".join(unmeasured_code[:8]) + ".")
    if unsupported and state == "PASS":
        state = "UNKNOWN"
    if unsupported:
        paths = [path for path, reason in excluded.items()
                 if reason.startswith("unsupported language") or reason == "configuration"
                 or reason == "binary"]
        override_reasons.append("Unsupported or unmeasured changed files: "
                                + ", ".join(paths[:8]) + ".")
    unbound = [path for path, reason in excluded.items()
               if reason in {"untracked outside checkpoint", "ignore rules changed"}]
    if unbound:
        state = "UNKNOWN"
        override_reasons.append("Changed files are outside the checkpoint or alter ignore rules: "
                                + ", ".join(unbound[:8]) + ".")
    generated = [path for path, reason in excluded.items() if (
        path.lower().endswith(".py") and reason == "generated"
    )]
    if rule.rule.required and generated:
        state = "UNKNOWN"
        override_reasons.append("Generated Python source is unmeasured: "
                                + ", ".join(generated[:8]) + ".")
    uncollected_test_code = [path for path, reason in excluded.items()
                             if path.lower().endswith(".py") and reason == "test code"
                             and path not in (collected_test_paths or set())]
    if rule.rule.required and state in {"PASS", "NOT_APPLICABLE"} and uncollected_test_code:
        state = "UNKNOWN"
    if rule.rule.required and uncollected_test_code:
        override_reasons.append("Changed test-named Python file is not a collected test: "
                                + ", ".join(uncollected_test_code[:8]) + ".")
    if rule.rule.required:
        for path, reason in excluded.items():
            if reason != "test code" or path not in (collected_test_paths or set()):
                continue
            try:
                risk = _test_module_risk(
                    root=root, path=path,
                    changed_lines=(excluded_changed_lines or {}).get(path, set()),
                    report_paths=set(files) | set(changed),
                    changed_production_lines=changed,
                )
            except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError):
                risk = f"Changed test module cannot be classified safely: {path}."
            if risk:
                state = "UNKNOWN"
                override_reasons.append(risk)
    gate = ((state == "PASS" or (state == "NOT_APPLICABLE" and rule.rule.not_applicable_satisfies))
            and result.checks_passed is True) if rule.rule.required else None
    return DiffCoverageResult.model_validate({**result.model_dump(), **{
        "files": measured, "excluded": excluded, "diff_exercised": state,
        "reasons": [*result.reasons, *override_reasons],
        "threshold": rule.rule.minimum_percent or 100.0,
        "measured_percent": (100.0 * executed_total / total) if total else None,
        "changed_executable_lines": total, "executed_changed_lines": executed_total,
        "gate_satisfied": gate,
    }})


def _scratch_file(box: CheckBox, name: str) -> bool:
    """True when ``scratch/<name>`` is a plain regular file (never follows a link)."""

    try:
        info = os.lstat(box.scratch / name)
    except OSError:
        return False
    reparse = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    return stat.S_ISREG(info.st_mode) and not reparse


def _scratch_bytes(box: CheckBox, name: str) -> bytes | None:
    """``scratch/<name>`` up to ARTIFACT_LIMIT; None when missing, oversized or a link."""

    try:
        return box.read_output(name, ARTIFACT_LIMIT)
    except AppError:
        return None


def collect_diff_coverage(
    *, change: ChangeView, baseline: GitCheckpoint, tested: GitCheckpoint,
    request: DiffCoverageRequest, git_state: GitStateTracker | None = None,
    patch_limit: int = 1_048_576, checks: CheckBoxes | None = None,
    on_check_run: Callable[[UUID, str], None] | None = None,
) -> DiffCoverageResult:
    """Run coverage in a disposable confined check box and recapture state afterward.

    Phase 5: tests and coverage run in a ``sentinel.check.<run-id>`` box over a
    copy of the repository's tracked and untracked files, with the snapshot of
    the (trusted) requested interpreter; evidence files live in the box's
    scratch directory. Without ``checks`` nothing runs (UNKNOWN). The box's
    check run id and boundary go to ``on_check_run``.
    """

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
            "Tests and coverage share one process inside a disposable Sentinel check box "
            "(AppContainer, no network, a copy of the tracked and untracked files); "
            "agent-authored code can still influence coverage data. The external Python "
            "interpreter is trusted by path, not by a verified publisher or binary digest."
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
        if checks is None:
            raise check_boxes_unavailable()
        # The trusted requested interpreter's snapshot runs in the box (cwd = its tree).
        resolved = checks.resolve_runtime("python", interpreter=interpreter, source_root=root)
        with checks.open(change.id, root, resolved.runtime) as box:
            check_root = box.tree
            evidence = box.scratch
            box_python = resolved.argv_prefix[0]
            config = evidence / "coveragerc"
            data = evidence / "coverage.data"
            artifact = evidence / "coverage.json"
            junit = evidence / "pytest-results.xml"
            pytest_config = evidence / "sentinel-pytest.ini"
            config.write_text(f"[run]\nsource = {check_root.as_posix()}\n", encoding="utf-8")
            pytest_config.write_text(
                "[pytest]\naddopts =\npython_files = test_*.py *_test.py\n"
                "python_classes = Test*\npython_functions = test_*\n"
                "testpaths =\nnorecursedirs = .git .venv venv node_modules "
                ".tox .nox __pycache__\n",
                encoding="utf-8",
            )
            argv = [box_python, "-X", f"pycache_prefix={evidence / 'pycache'}",
                    "-m", "coverage", "run", "--rcfile", str(config),
                    "--data-file", str(data), "-m", "pytest", "-p", "no:cacheprovider",
                    *test_args, "-c", str(pytest_config), f"--rootdir={check_root}",
                    "-o", "addopts=", f"--junitxml={junit}"]
            result = result.model_copy(update={"command": argv})
            run = box.run(argv, timeout=300, limit=262_144)
            if on_check_run is not None:
                on_check_run(run.check_run_id, run.boundary)
            if run.timed_out or run.incomplete:
                reasons.append("Test command timed out or output capture was incomplete.")
            elif not _scratch_file(box, data.name):
                reasons.append("Coverage data is missing; test execution could not be confirmed.")
            else:
                junit_bytes = _scratch_bytes(box, junit.name)
                if junit_bytes is None:
                    reasons.append("Pytest execution report is missing or oversized.")
                else:
                    suite = ET.fromstring(junit_bytes)
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
                            normalized = _report_path(check_root, file_attr)
                            if normalized:
                                collected_test_paths.add(normalized)
                        classname = case.attrib.get("classname", "")
                        if classname and all(part.isidentifier() for part in classname.split(".")):
                            collected_test_paths.add(classname.replace(".", "/") + ".py")
                    if executed_tests <= 0:
                        reasons.append("Pytest did not execute any tests.")
                    else:
                        checks_passed = run.exit_code == 0
                exported = box.run(
                    [box_python, "-m", "coverage", "json", "--rcfile", str(config),
                     "--data-file", str(data), "-o", str(artifact)],
                    timeout=60, limit=32_768,
                )
                content = _scratch_bytes(box, artifact.name)
                if exported.exit_code != 0 or exported.timed_out or exported.incomplete:
                    reasons.append("coverage.py JSON export failed or coverage.py is unavailable.")
                elif content is None:
                    reasons.append("Coverage report is missing or oversized.")
                else:
                    artifact_digest = hashlib.sha256(content).hexdigest()
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        # Report paths are relative to the check tree; key them by repository path.
                        files = parsed.get("files")
                        if isinstance(files, dict) and all(isinstance(key, str) for key in files):
                            parsed["files"] = {(_report_path(check_root, key) or key): value
                                               for key, value in files.items()}
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
    except AppError as exc:
        reasons.append(f"Coverage collection failed: {exc.code}.")
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
    if report is None or checks_passed is None:
        return result
    try:
        return evaluate_report(result=result, changed=mapped.lines, excluded=mapped.excluded,
                               report=report, root=root, rule=request,
                               collected_test_paths=collected_test_paths,
                               excluded_changed_lines=mapped.excluded_lines)
    except Exception as exc:
        return result.model_copy(update={
            "collector_status": "ERROR", "diff_exercised": "UNKNOWN",
            "gate_satisfied": False if request.rule.required else None,
            "reasons": [f"Coverage evaluation failed: {type(exc).__name__}."],
        })
