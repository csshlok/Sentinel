"""Person 2 evidence orchestration: one persisted, restart-safe flow.

``EvidenceService`` composes the five ``[KB]`` ports with ``EvidenceStore`` so a
caller (``[SD]``'s routes, the CLI through the API) can drive the retained flow
without knowing about checkpoints, digests or freshness:

    capture_baseline -> launch/attach agent -> capture_current
        -> plan_assurance -> run_assurance -> evaluate -> assurance_facts

It never authorizes anything (authority is enforced upstream through
``PolicyPort``) and never mutates the selected repository. Persistence goes
through ``EvidenceStore`` only, so a restart loses nothing except in-flight agent
processes, which the launcher cannot observe across restarts.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from backend.app.assurance.engine import AssuranceEngine, contract_digest
from backend.app.assurance.models import AssuranceEvaluation
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import (
    AgentAttachRequest, AgentLaunchRequest, AgentRun, AssurancePlan, AssuranceRun,
    ChangeView, ContractModel, DependencyReport, EnvironmentDrift, EnvironmentPassport,
    GitCheckpoint, GitCheckpointComparison,
)
from backend.app.core.errors import AppError
from backend.app.dependencies.tracker import DependencyTracker
from backend.app.environment.tracker import EnvironmentTracker
from backend.app.execution.launcher import AgentLauncher
from backend.app.git.state import GitStateTracker

BASELINE = "baseline"
DEFAULT_PATCH_LIMIT = 200_000
DEFAULT_OUTPUT_LIMIT = 200_000


class EvidenceSnapshot(ContractModel):
    """Everything captured at one point in time, with comparisons to the baseline."""

    checkpoint: GitCheckpoint
    comparison: GitCheckpointComparison | None = None
    environment: EnvironmentPassport
    drift: EnvironmentDrift | None = None
    dependencies: DependencyReport | None = None
    limitations: list[str] = Field(default_factory=list, max_length=64)


class EnvironmentView(ContractModel):
    """The latest environment passport and its drift from the first one captured."""

    passport: EnvironmentPassport | None = None
    baseline_id: UUID | None = None
    drift: EnvironmentDrift | None = None


class EvidenceOverview(ContractModel):
    """What has been captured so far for one Change (read-only)."""

    baseline_captured: bool
    latest_checkpoint_fresh: bool | None = None  # None: no checkpoint, or the repository could not be read
    checkpoints: list[GitCheckpoint] = Field(default_factory=list, max_length=1000)
    environment: EnvironmentPassport | None = None
    dependencies: DependencyReport | None = None
    plan: AssurancePlan | None = None


class AssuranceFacts(ContractModel):
    """The ``LifecycleFacts`` fields owned by ``[KB]``, from persisted, fresh evidence."""

    required_assurance_passed: bool = False
    assurance_fresh: bool = False
    deviations_resolved: bool = False
    required_evidence_complete: bool = False
    reasons: list[str] = Field(default_factory=list, max_length=64)


class EvidenceService:
    def __init__(
        self,
        store: EvidenceStore,
        *,
        git_state: GitStateTracker | None = None,
        launcher: AgentLauncher | None = None,
        environment: EnvironmentTracker | None = None,
        dependencies: DependencyTracker | None = None,
        assurance: AssuranceEngine | None = None,
        patch_limit_bytes: int = DEFAULT_PATCH_LIMIT,
    ) -> None:
        self._store = store
        self._git = git_state or GitStateTracker()
        self._launcher = launcher or AgentLauncher()
        if self._launcher.on_update is None:
            # Persist in-flight runs so they are listed, and stoppable from another request.
            self._launcher.on_update = store.save_agent_run
        self._environment = environment or EnvironmentTracker()
        self._dependencies = dependencies or DependencyTracker()
        self._patch_limit = patch_limit_bytes
        self._assurance = assurance or AssuranceEngine(git_state=self._git,
                                                       patch_limit_bytes=patch_limit_bytes)

    # -- baseline and current evidence --------------------------------------

    def capture_baseline(self, change: ChangeView) -> EvidenceSnapshot:
        """Capture the Git checkpoint and environment passport before the agent runs.

        Refuses to replace an existing baseline: a baseline that can be silently
        redone would make every later comparison meaningless.
        """

        if self._store.named_checkpoint(change.id, BASELINE) is not None:
            raise AppError("BASELINE_EXISTS", "A baseline was already captured for this Change.",
                           status_code=409)
        checkpoint = self._git.capture(change.id, BASELINE, change.repository_path,
                                       self._revision(change), self._patch_limit)
        environment = self._environment.capture(change.id, change.repository_path)
        self._store.save_checkpoint(checkpoint)
        self._store.save_environment(environment)
        return EvidenceSnapshot(checkpoint=checkpoint, environment=environment,
                                limitations=list(environment.limitations))

    def capture_current(self, change: ChangeView, name: str = "current") -> EvidenceSnapshot:
        """Capture current evidence and compare it with the baseline."""

        baseline = self._store.named_checkpoint(change.id, BASELINE)
        base_env = self._store.first_environment(change.id)
        if baseline is None or base_env is None:
            raise AppError("BASELINE_MISSING",
                           "Capture a baseline before capturing current evidence.", status_code=409)
        checkpoint = self._git.capture(change.id, name, change.repository_path,
                                       self._revision(change), self._patch_limit)
        environment = self._environment.capture(change.id, change.repository_path)
        limitations = list(environment.limitations)
        comparison = self._git.compare(baseline, checkpoint)
        drift = self._environment.compare(base_env, environment)
        dependencies = self._dependencies.scan(change.id, checkpoint, change.repository_path)
        if dependencies.unsupported_ecosystems:
            limitations.append("Some dependency sources are unsupported or unreadable.")
        if comparison.head_changed or comparison.branch_moved:
            limitations.append("The branch or HEAD moved since the baseline; dependency "
                               "changes are measured from the current HEAD.")
        self._store.save_checkpoint(checkpoint)
        self._store.save_environment(environment)
        self._store.save_dependency_report(dependencies)
        return EvidenceSnapshot(checkpoint=checkpoint, comparison=comparison,
                                environment=environment, drift=drift, dependencies=dependencies,
                                limitations=limitations)

    def overview(self, change_id: UUID) -> EvidenceOverview:
        checkpoints = self._store.list_checkpoints(change_id)
        stored = self._store.latest_plan(change_id)
        fresh: bool | None = None
        if checkpoints:
            try:
                fresh = self._git.is_current(checkpoints[-1], None, self._patch_limit)
            except AppError:
                fresh = None
        return EvidenceOverview(
            baseline_captured=any(c.name == BASELINE for c in checkpoints),
            latest_checkpoint_fresh=fresh,
            checkpoints=checkpoints[-100:],
            environment=self._store.latest_environment(change_id),
            dependencies=self._store.latest_dependency_report(change_id),
            plan=stored.plan if stored else None)

    def compare_checkpoints(
        self, change_id: UUID, baseline_id: UUID, current_id: UUID
    ) -> GitCheckpointComparison:
        """Compare two persisted checkpoints of the same Change."""

        pair = [self._store.get_checkpoint(baseline_id), self._store.get_checkpoint(current_id)]
        if any(cp is None or cp.change_id != change_id for cp in pair):
            raise AppError("CHECKPOINT_NOT_FOUND",
                           "A checkpoint does not exist for this Change.", status_code=404)
        return self._git.compare(pair[0], pair[1])

    def environment_view(self, change_id: UUID) -> EnvironmentView:
        latest = self._store.latest_environment(change_id)
        first = self._store.first_environment(change_id)
        drift = (self._environment.compare(first, latest)
                 if latest and first and latest.id != first.id else None)
        return EnvironmentView(passport=latest, baseline_id=first.id if first else None, drift=drift)

    def latest_dependency_report(self, change_id: UUID) -> DependencyReport | None:
        return self._store.latest_dependency_report(change_id)

    def latest_plan(self, change_id: UUID) -> AssurancePlan | None:
        stored = self._store.latest_plan(change_id)
        return stored.plan if stored else None

    def adapters(self, repository_path: str | None = None) -> list[dict[str, object]]:
        return self._launcher.adapters(repository_path)

    # -- agent --------------------------------------------------------------

    def launch_agent(
        self, change: ChangeView, request: AgentLaunchRequest,
        output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT,
    ) -> AgentRun:
        """Launch a top-level agent (blocking) and persist the aggregate result."""

        run = self._launcher.launch(change.id, change.repository_path, request, output_limit_bytes)
        self._store.save_agent_run(run)
        return run

    def attach_agent(self, change: ChangeView, request: AgentAttachRequest) -> AgentRun:
        run = self._launcher.attach(change.id, request)
        self._store.save_agent_run(run)
        return run

    def stop_agent(self, run_id: UUID) -> AgentRun:
        """Stop a run started by this process; persist whatever state results."""

        stored = self._store.get_agent_run(run_id)
        try:
            run = self._launcher.stop(run_id)
        except AppError:
            if stored is None:
                raise
            note = "The run is not known to this process (restart); it cannot be stopped."
            run = stored if note in stored.limitations else stored.model_copy(
                update={"limitations": [*stored.limitations, note]})
        self._store.save_agent_run(run)
        return run

    def agent_runs(self, change_id: UUID) -> list[AgentRun]:
        return self._store.list_agent_runs(change_id)

    # -- assurance ----------------------------------------------------------

    def plan_assurance(self, change: ChangeView) -> AssurancePlan:
        """Plan checks from the latest persisted evidence."""

        checkpoint = self._store.latest_checkpoint(change.id)
        if checkpoint is None:
            raise AppError("EVIDENCE_MISSING", "Capture evidence before planning assurance.",
                           status_code=409)
        plan = self._assurance.discover(
            change, checkpoint, self._store.latest_environment(change.id),
            self._dependencies_for(change.id, checkpoint))
        self._store.save_plan(plan, contract_digest(change))
        return plan

    def run_assurance(
        self, change: ChangeView, plan_id: UUID, output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT,
    ) -> list[AssuranceRun]:
        plan = self._load_plan(change, plan_id)
        runs = self._assurance.run(change, plan, change.repository_path, output_limit_bytes)
        self._store.save_runs(runs)
        return runs

    def evaluate(self, change: ChangeView, plan_id: UUID) -> AssuranceEvaluation:
        """Re-inspect the repository and decide what the persisted results still prove."""

        plan = self._load_plan(change, plan_id)
        checkpoint = self._store.get_checkpoint(plan.checkpoint_id)
        runs = self._store.list_runs(plan.id)
        current = self._git.capture(change.id, "evaluation", change.repository_path,
                                    self._revision(change), self._patch_limit)
        baseline_env = self._store.first_environment(change.id)
        latest_env = self._store.latest_environment(change.id)
        drift = (self._environment.compare(baseline_env, latest_env)
                 if baseline_env and latest_env and baseline_env.id != latest_env.id else None)
        return self._assurance.evaluate(
            change, plan, self._latest_runs(runs), current_checkpoint=current,
            dependencies=self._dependencies_for(change.id, checkpoint),
            environment_drift=drift)

    def assurance_facts(self, change: ChangeView) -> AssuranceFacts:
        """The four lifecycle facts, or all-``False`` with a reason when unproven."""

        stored = self._store.latest_plan(change.id)
        if stored is None:
            return AssuranceFacts(reasons=["No assurance plan exists for this Change."])
        try:
            evaluation = self.evaluate(change, stored.plan.id)
        except AppError as exc:
            return AssuranceFacts(reasons=[exc.message])
        return AssuranceFacts(
            required_assurance_passed=evaluation.required_assurance_passed,
            assurance_fresh=evaluation.assurance_fresh,
            deviations_resolved=evaluation.deviations_resolved,
            required_evidence_complete=evaluation.required_evidence_complete,
            reasons=[*evaluation.freshness_reasons,
                     *[f"Required check '{c}' has no passing result." for c in evaluation.missing_required],
                     *[f"Check '{c}' failed." for c in evaluation.failed]][:64])

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _revision(change: ChangeView) -> int:
        return max(1, change.evidence_revision)

    def _dependencies_for(self, change_id: UUID, checkpoint: GitCheckpoint | None):
        return self._store.latest_dependency_report(change_id)

    def _load_plan(self, change: ChangeView, plan_id: UUID) -> AssurancePlan:
        """Load a persisted plan and rebind it to its evidence (restart-safe)."""

        stored = self._store.get_plan(plan_id)
        if stored is None or stored.plan.change_id != change.id:
            raise AppError("ASSURANCE_PLAN_NOT_FOUND",
                           "The assurance plan does not exist for this Change.", status_code=404)
        checkpoint = self._store.get_checkpoint(stored.plan.checkpoint_id)
        if checkpoint is None:
            raise AppError("EVIDENCE_MISSING", "The plan's checkpoint is missing.", status_code=409)
        self._assurance.remember(change, stored.plan, checkpoint, stored.contract_sha256)
        return stored.plan

    @staticmethod
    def _latest_runs(runs: list[AssuranceRun]) -> list[AssuranceRun]:
        """Latest result per check; earlier attempts are history, not evidence."""

        latest: dict[str, AssuranceRun] = {}
        for run in runs:
            latest[run.check_id] = run
        return list(latest.values())
