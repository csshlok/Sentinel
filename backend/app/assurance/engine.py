"""Assurance engine (``AssurancePort``).

Builds an evidence-selected plan, runs the bounded checks and decides whether the
resulting evidence is fresh. Passing checks describe only the commands that ran;
they are not proof of correctness. Plans and their evidence bindings are held in
memory: a composition layer that persists them must call ``remember`` after a
restart or ``run`` refuses to execute against unknown evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from backend.app.assurance import discovery as disc
from backend.app.assurance.deviations import analyze_deviations
from backend.app.assurance.models import (
    AssuranceEvaluation, CheckResult, DeviationFinding, DeviationSeverity,
)
from backend.app.contracts.models import (
    AssuranceCheck, AssurancePlan, AssuranceRun, AssuranceStatus, ChangeView,
    DependencyReport, EnvironmentDrift, EnvironmentPassport, EvidenceStatus,
    GitCheckpoint, VerificationRequest, VerificationResult, VerificationStatus, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.execution._process import minimal_environment
from backend.app.execution.resolve import find_executable, native_command
from backend.app.execution.runner import BoundedVerificationRunner
from backend.app.git import reader
from backend.app.git.state import GitStateTracker

DEFAULT_CHECK_TIMEOUT = 300
MAX_REMEMBERED_PLANS = 256
_PY_SOURCE = {".py", ".pyi"}
_NODE_SOURCE = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_STATUS = {
    VerificationStatus.PASSED: AssuranceStatus.PASSED,
    VerificationStatus.FAILED: AssuranceStatus.FAILED,
    VerificationStatus.TIMED_OUT: AssuranceStatus.TIMED_OUT,
    VerificationStatus.ERROR: AssuranceStatus.ERROR,
}


def contract_digest(change: ChangeView) -> str:
    body = json.dumps(change.contract.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class _Binding:
    checkpoint: GitCheckpoint
    contract_sha256: str
    check_ids: tuple[str, ...]
    gaps: tuple[str, ...]


class AssuranceEngine:
    """Concrete ``AssurancePort``."""

    def __init__(
        self,
        runner=None,
        git_state: GitStateTracker | None = None,
        *,
        patch_limit_bytes: int | None = None,
        check_timeout_seconds: int = DEFAULT_CHECK_TIMEOUT,
    ) -> None:
        if type(check_timeout_seconds) is not int or not 1 <= check_timeout_seconds <= 300:
            raise ValueError("The check timeout must be between 1 and 300 seconds.")
        self._runner = runner or BoundedVerificationRunner()
        self._git_state = git_state or GitStateTracker()
        self._patch_limit = patch_limit_bytes
        self._timeout = check_timeout_seconds
        self._plans: dict[UUID, _Binding] = {}
        self._lock = threading.Lock()

    # -- discover -----------------------------------------------------------

    def discover(
        self,
        change: ChangeView,
        checkpoint: GitCheckpoint,
        environment: EnvironmentPassport | None,
        dependencies: DependencyReport | None,
    ) -> AssurancePlan:
        root = checkpoint.repository_root
        paths = reader.list_paths(root, checkpoint.head_sha.lower())
        found = disc.discover(root, paths)
        gaps: list[str] = list(found.gaps)
        required_terms = [t.strip().lower() for t in change.contract.required_checks]

        changed = [f.path for f in checkpoint.summary.files]
        families = self._changed_families(changed, dependencies)

        selected: dict[str, tuple[disc.Candidate, bool, list[str]]] = {}

        def choose(candidate: disc.Candidate, required: bool, reason: str) -> None:
            _, was_required, reasons = selected.get(candidate.id, (candidate, False, []))
            if reason not in reasons:
                reasons.append(reason)
            selected[candidate.id] = (candidate, was_required or required, reasons)

        for candidate in found.candidates:
            aliases = candidate.aliases()
            if any(term in aliases for term in required_terms):
                choose(candidate, True, "Required by the Change Contract.")
            evidence = families.get(candidate.family)
            if evidence is None:
                continue
            if candidate.kind in {"test", "lint", "typecheck"} and evidence["source"]:
                choose(candidate, False,
                       f"{evidence['source']} changed {candidate.family} source or test path(s).")
            elif candidate.kind == "test" and evidence["dependency"]:
                choose(candidate, False, f"{candidate.family} dependencies changed.")
            elif candidate.kind == "build" and (evidence["source"] or evidence["dependency"]
                                                or evidence["config"]):
                choose(candidate, False,
                       f"{candidate.family} source, configuration or dependencies changed.")
            elif candidate.kind == "security" and evidence["dependency"]:
                choose(candidate, False, f"{candidate.family} dependencies changed.")

        known = {alias for c in found.candidates for alias in c.aliases()}
        for term, original in zip(required_terms, change.contract.required_checks):
            if term not in known:
                gaps.append(f"Required check '{original}' was not discovered in this repository.")

        for family, evidence in sorted(families.items()):
            if evidence["source"] and not any(
                    c.family == family and c.kind == "test" for c in found.candidates):
                gaps.append(f"Changed {family} source has no discovered test runner.")

        checks: list[AssuranceCheck] = []
        kinds = {c.id: c.kind for c in found.candidates}
        for candidate, required, reasons in selected.values():
            checks.append(AssuranceCheck(
                id=candidate.id, name=candidate.name, executable=candidate.executable,
                args=list(candidate.args), required=required,
                rationale=" ".join(reasons + [candidate.rationale])[:4000]))
            if find_executable(candidate.executable, minimal_environment(), Path(root)) is None:
                gaps.append(
                    f"Tool '{candidate.executable}' was not found; check '{candidate.id}' cannot run.")
        checks.sort(key=lambda c: (not c.required, disc._KIND_ORDER[kinds[c.id]], c.id))

        if not changed and not checks:
            gaps.append("No changed paths and no required checks; no assurance was selected.")
        if environment is None:
            gaps.append("Environment evidence is missing.")
        elif environment.status is not EvidenceStatus.CURRENT:
            gaps.append(f"Environment evidence is {environment.status.value.lower()}: "
                        f"{len(environment.limitations)} limitation(s) recorded.")
        if dependencies is None:
            gaps.append("Dependency evidence is missing.")
        else:
            gaps.extend(f"Dependency evidence unsupported: {item}"
                        for item in dependencies.unsupported_ecosystems)
        if checkpoint.summary.patch_truncated:
            gaps.append("Patch evidence was truncated; deviation analysis covers paths only.")
        if checkpoint.summary.untracked_patch_omitted:
            gaps.append("Untracked file contents are not part of the patch evidence.")
        if any(c.executable == "python" for c in checks):
            gaps.append("Checks run with the runtime's interpreter and PATH, not a repository "
                        "virtual environment.")
        gaps = list(dict.fromkeys(gaps))[:256]

        plan = AssurancePlan(id=uuid4(), change_id=change.id, checkpoint_id=checkpoint.id,
                             checks=checks[:256], coverage_gaps=gaps, created_at=utc_now())
        self.remember(change, plan, checkpoint)
        return plan

    def remember(self, change: ChangeView, plan: AssurancePlan, checkpoint: GitCheckpoint) -> None:
        """Bind ``plan`` to the checkpoint and contract it was built from."""

        if plan.checkpoint_id != checkpoint.id:
            raise AppError("ASSURANCE_CHECKPOINT_MISMATCH",
                           "The checkpoint does not belong to the plan.", status_code=409)
        with self._lock:
            self._plans[plan.id] = _Binding(
                checkpoint, contract_digest(change), tuple(c.id for c in plan.checks),
                tuple(plan.coverage_gaps))
            while len(self._plans) > MAX_REMEMBERED_PLANS:
                del self._plans[next(iter(self._plans))]

    # -- run ----------------------------------------------------------------

    def run(
        self, change: ChangeView, plan: AssurancePlan, repository_path: str,
        output_limit_bytes: int,
    ) -> list[AssuranceRun]:
        binding = self._binding(plan)
        reasons = self._stale_reasons(change, plan, binding, repository_path)
        root = disc.require_repository_path(repository_path)
        runs: list[AssuranceRun] = []
        for check in plan.checks:
            if reasons:
                runs.append(self._skipped(
                    change, plan, check,
                    "Evidence is stale; the check was not run: " + "; ".join(reasons)))
                continue
            runs.append(self._execute(change, plan, check, root, output_limit_bytes))
        return runs

    def _execute(self, change, plan, check, root, limit) -> AssuranceRun:
        executable, args = native_command(
            check.executable, list(check.args), minimal_environment(), Path(root))
        try:
            request = VerificationRequest(executable=executable, args=args,
                                          timeout_seconds=self._timeout)
            result = self._runner.run(root, request, limit)
        except AppError as exc:
            now = utc_now()
            return AssuranceRun(
                id=uuid4(), change_id=change.id, plan_id=plan.id, checkpoint_id=plan.checkpoint_id,
                check_id=check.id, status=AssuranceStatus.ERROR, exit_code=None, duration_ms=0,
                stderr=exc.message, started_at=now, completed_at=now)
        return self._from_result(change, plan, check, result)

    @staticmethod
    def _from_result(change, plan, check, result: VerificationResult) -> AssuranceRun:
        return AssuranceRun(
            id=uuid4(), change_id=change.id, plan_id=plan.id, checkpoint_id=plan.checkpoint_id,
            check_id=check.id, status=_STATUS[result.status], exit_code=result.exit_code,
            duration_ms=result.duration_ms, stdout=result.stdout, stderr=result.stderr,
            output_truncated=result.output_truncated, started_at=result.started_at,
            completed_at=result.completed_at)

    @staticmethod
    def _skipped(change, plan, check, message) -> AssuranceRun:
        now = utc_now()
        return AssuranceRun(
            id=uuid4(), change_id=change.id, plan_id=plan.id, checkpoint_id=plan.checkpoint_id,
            check_id=check.id, status=AssuranceStatus.SKIPPED, duration_ms=0,
            stderr=message[:2000], started_at=now, completed_at=now)

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        change: ChangeView,
        plan: AssurancePlan,
        runs: list[AssuranceRun],
        *,
        current_checkpoint: GitCheckpoint | None = None,
        dependencies: DependencyReport | None = None,
        environment_drift: EnvironmentDrift | None = None,
    ) -> AssuranceEvaluation:
        """Decide freshness, required-check outcome and contract deviations."""

        binding = self._binding(plan)
        reasons = self._stale_reasons(change, plan, binding, binding.checkpoint.repository_root,
                                      current=current_checkpoint)
        by_check: dict[str, AssuranceRun] = {}
        for run in runs:
            if run.plan_id != plan.id or run.checkpoint_id != plan.checkpoint_id:
                reasons.append(f"Run for check '{run.check_id}' belongs to different evidence.")
                continue
            by_check[run.check_id] = run
        results: list[CheckResult] = []
        missing: list[str] = []
        failed: list[str] = []
        passed_any = False
        for check in plan.checks:
            run = by_check.get(check.id)
            status = run.status if run else AssuranceStatus.PENDING
            if status is AssuranceStatus.PASSED:
                passed_any = True
            elif status in {AssuranceStatus.FAILED, AssuranceStatus.TIMED_OUT, AssuranceStatus.ERROR}:
                failed.append(check.id)
            elif check.required:
                missing.append(check.id)   # pending, running or skipped: no result to rely on
            results.append(CheckResult(
                check_id=check.id, required=check.required, status=status,
                exit_code=run.exit_code if run else None,
                summary=summarize(check.id, run) if run else ""))
        required_checks = [c for c in plan.checks if c.required]
        if required_checks:
            required_ok = all(
                by_check.get(c.id) is not None and by_check[c.id].status is AssuranceStatus.PASSED
                for c in required_checks)
        else:
            # Nothing was contractually required: still demand at least one clean pass.
            required_ok = passed_any and not failed
        reasons = list(dict.fromkeys(reasons))
        fresh = not reasons
        deviations = analyze_deviations(
            change, current_checkpoint or binding.checkpoint, dependencies, environment_drift)
        blocking = any(d.severity is DeviationSeverity.BLOCKING for d in deviations)
        gaps = list(binding.gaps) + [f"Required check '{m}' has no passing result." for m in missing]
        evidence_gaps = [g for g in gaps if g.startswith(("Required check", "Tool '"))]
        if not fresh:
            status = EvidenceStatus.STALE
        elif not by_check:
            status = EvidenceStatus.MISSING
        elif missing or gaps:
            status = EvidenceStatus.PARTIAL
        else:
            status = EvidenceStatus.CURRENT
        return AssuranceEvaluation(
            plan_id=plan.id, checkpoint_id=plan.checkpoint_id, status=status, fresh=fresh,
            freshness_reasons=reasons[:32], results=results, missing_required=missing,
            failed=failed, coverage_gaps=gaps[:512], deviations=deviations,
            required_assurance_passed=required_ok and fresh,
            assurance_fresh=fresh, deviations_resolved=not blocking,
            required_evidence_complete=not evidence_gaps and fresh,
        )

    def analyze_deviations(
        self, change, checkpoint, dependencies=None, environment_drift=None
    ) -> list[DeviationFinding]:
        return analyze_deviations(change, checkpoint, dependencies, environment_drift)

    # -- helpers ------------------------------------------------------------

    def _binding(self, plan: AssurancePlan) -> _Binding:
        with self._lock:
            binding = self._plans.get(plan.id)
        if binding is None or binding.check_ids != tuple(c.id for c in plan.checks):
            raise AppError(
                "ASSURANCE_PLAN_UNKNOWN",
                "The plan is unknown or was modified; discover it again before running checks.",
                status_code=409)
        return binding

    def _stale_reasons(
        self, change: ChangeView, plan: AssurancePlan, binding: _Binding,
        repository_path: str, current: GitCheckpoint | None = None,
    ) -> list[str]:
        reasons: list[str] = []
        if change.id != plan.change_id:
            reasons.append("The plan belongs to a different Change.")
        if contract_digest(change) != binding.contract_sha256:
            reasons.append("The Change Contract changed after the plan was made.")
        try:
            if current is not None:
                if current.status_digest != binding.checkpoint.status_digest:
                    reasons.append("The repository changed after the checkpoint.")
            elif not self._git_state.is_current(
                    binding.checkpoint, repository_path, self._patch_limit):
                reasons.append("The repository changed after the checkpoint.")
        except AppError:
            reasons.append("The repository could not be re-inspected to confirm freshness.")
        return reasons

    @staticmethod
    def _changed_families(changed: list[str], dependencies: DependencyReport | None):
        result = {name: {"source": 0, "dependency": 0, "config": 0} for name in ("python", "node")}
        for path in changed:
            pure = PurePosixPath(path)
            if pure.suffix.lower() in _PY_SOURCE:
                result["python"]["source"] += 1
            elif pure.suffix.lower() in _NODE_SOURCE:
                result["node"]["source"] += 1
            name = pure.name.lower()
            if name in {"package.json", "tsconfig.json"} or name.startswith(
                    ("vite.config", "webpack.config")):
                result["node"]["config"] += 1
            if name in {"pyproject.toml", "setup.cfg"}:
                result["python"]["config"] += 1
        if dependencies is not None:
            for dep in dependencies.changes:
                if dep.ecosystem in result:
                    result[dep.ecosystem]["dependency"] += 1
        return {family: counts for family, counts in result.items() if any(counts.values())}


_PYTEST = re.compile(r"=+\s*(.*?(?:passed|failed|error|skipped|no tests ran).*?)\s+in\s+[\d.]+s", re.I)
_NODE_TAP = re.compile(r"^(?:#|ℹ)\s+(pass|fail|cancelled)\s+(\d+)", re.M)  # TAP or spec reporter
_JEST = re.compile(r"^Tests:\s+(.+)$", re.M)


def summarize(check_id: str, run: AssuranceRun) -> str:
    """Bounded one-line structured summary from well-known reporter output."""

    text = run.stdout + "\n" + run.stderr
    if check_id == "pytest":
        match = _PYTEST.findall(text)
        if match:
            return match[-1].strip()[:300]
    if check_id in {"node-test", "jest", "vitest", "mocha"}:
        tap = _NODE_TAP.findall(text)
        if tap:
            return ", ".join(f"{count} {name}" for name, count in tap)[:300]
        jest = _JEST.findall(text)
        if jest:
            return jest[-1].strip()[:300]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1][:300] if lines else ""
