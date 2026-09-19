"""Request-scoped use cases for the Person 2 evidence/execution/assurance stream.

Composes ``[KB]``'s ``EvidenceService`` with ``[SD]``'s Change lookup and the
``[AC]`` policy engine. Read-only evidence capture (baseline, current evidence,
assurance planning and evaluation) needs no delegated authority, like the
existing Git refresh. Anything that executes a command on the user's behalf --
launching an agent, stopping one, attaching declared metadata, running assurance
checks -- is default-denied unless the actor holds a delegation for that exact
scope on that Change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from backend.app.assurance.models import AssuranceEvaluation
from pydantic import TypeAdapter

from backend.app.assurance.service import (
    AssuranceFacts, EnvironmentView, EvidenceOverview, EvidenceService, EvidenceSnapshot,
)
from backend.app.assurance.store import IdempotencyStore
from backend.app.contracts.models import (
    AgentAdapterInfo, AgentAttachRequest, AgentLaunchRequest, AgentRun, AssurancePlan,
    AssuranceRun, ChangeView, DependencyReport, GitCheckpoint, GitCheckpointComparison,
)
from backend.app.contracts.ports import PolicyPort
from backend.app.core.change_service import ChangeService
from backend.app.core.errors import AppError, policy_denied

T = TypeVar("T")
_RUN = TypeAdapter(AgentRun)
_RUNS = TypeAdapter(list[AssuranceRun])
_PLAN = TypeAdapter(AssurancePlan)
_SNAPSHOT = TypeAdapter(EvidenceSnapshot)

LAUNCH_SCOPE = "agent.launch"
ATTACH_SCOPE = "agent.attach"
STOP_SCOPE = "agent.stop"
ASSURANCE_RUN_SCOPE = "assurance.run"


class EvidenceAdminService:
    def __init__(
        self, evidence: EvidenceService, policy: PolicyPort, change_service: ChangeService,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self.idempotency = idempotency
        self.evidence = evidence
        self.policy = policy
        self.change_service = change_service

    def _authorize(self, actor_id: UUID, change: ChangeView, operation: str,
                   parameters: dict[str, object] | None = None) -> None:
        decision = self.policy.evaluate(actor_id, change, operation, parameters or {})
        if not decision.allowed:
            raise policy_denied(decision.reason_code, decision.explanation)

    # -- evidence -----------------------------------------------------------

    def overview(self, change_id: UUID) -> EvidenceOverview:
        self.change_service.get(change_id)
        return self.evidence.overview(change_id)

    def capture_baseline(
        self, change_id: UUID, idempotency_key: str | None = None
    ) -> EvidenceSnapshot:
        change = self.change_service.get(change_id)
        return self._once(f"evidence.baseline:{change_id}", idempotency_key, {},
                          lambda: self.evidence.capture_baseline(change), _SNAPSHOT)

    def capture_current(
        self, change_id: UUID, idempotency_key: str | None = None
    ) -> EvidenceSnapshot:
        change = self.change_service.get(change_id)
        return self._once(f"evidence.current:{change_id}", idempotency_key, {},
                          lambda: self.evidence.capture_current(change), _SNAPSHOT)

    def checkpoints(self, change_id: UUID) -> list[GitCheckpoint]:
        self.change_service.get(change_id)
        return self.evidence.overview(change_id).checkpoints

    def compare_checkpoints(
        self, change_id: UUID, baseline_id: UUID, current_id: UUID
    ) -> GitCheckpointComparison:
        self.change_service.get(change_id)
        return self.evidence.compare_checkpoints(change_id, baseline_id, current_id)

    def environment(self, change_id: UUID) -> EnvironmentView:
        self.change_service.get(change_id)
        return self.evidence.environment_view(change_id)

    def dependencies(self, change_id: UUID) -> DependencyReport:
        self.change_service.get(change_id)
        report = self.evidence.latest_dependency_report(change_id)
        if report is None:
            raise AppError("DEPENDENCY_REPORT_NOT_FOUND",
                           "No dependency report has been captured for this Change.",
                           status_code=404)
        return report

    # -- agents -------------------------------------------------------------

    def adapters(self, change_id: UUID | None = None) -> list[AgentAdapterInfo]:
        path = self.change_service.get(change_id).repository_path if change_id else None
        return [AgentAdapterInfo.model_validate(item) for item in self.evidence.adapters(path)]

    def _once(self, scope: str, key: str | None, body: dict[str, object],
              action: Callable[[], T], adapter: TypeAdapter[T],
              *, authorize: Callable[[], None] | None = None) -> T:
        """Run ``action`` at most once per idempotency key; replays return the stored result.

        ``authorize`` (when given) runs only on the path that actually
        executes ``action`` -- never on a replay short-circuited by the
        stored result. Authorizing before the idempotency claim would spend
        a delegation's limited ``uses`` again on every retry of an already
        -completed request, which defeats both the use limit and the point
        of idempotency; authorizing here keeps the claim as the single gate.
        """

        if key is None or self.idempotency is None:
            if authorize is not None:
                authorize()
            return action()
        digest = hashlib.sha256(json.dumps(
            body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
        stored = self.idempotency.claim(scope, key, digest)
        if stored is not None:
            return adapter.validate_json(stored)
        try:
            if authorize is not None:
                authorize()
            result = action()
        except BaseException:
            self.idempotency.release(scope, key)
            raise
        self.idempotency.complete(scope, key, adapter.dump_json(result).decode("utf-8"))
        return result

    def launch_agent(
        self, change_id: UUID, actor_id: UUID, request: AgentLaunchRequest,
        output_limit_bytes: int, idempotency_key: str | None = None,
    ) -> AgentRun:
        change = self.change_service.get(change_id)
        body = {"actor": str(actor_id), "launch": request.model_dump(mode="json"),
                "limit": output_limit_bytes}
        return self._once(
            f"agent.launch:{change_id}", idempotency_key, body,
            lambda: self.evidence.launch_agent(change, request, output_limit_bytes),
            _RUN,
            authorize=lambda: self._authorize(
                actor_id, change, LAUNCH_SCOPE,
                {"adapter": request.adapter, "executable": request.executable}),
        )

    def attach_agent(
        self, change_id: UUID, actor_id: UUID, request: AgentAttachRequest,
        idempotency_key: str | None = None,
    ) -> AgentRun:
        change = self.change_service.get(change_id)
        body = {"actor": str(actor_id), "attach": request.model_dump(mode="json")}
        return self._once(
            f"agent.attach:{change_id}", idempotency_key, body,
            lambda: self.evidence.attach_agent(change, request), _RUN,
            authorize=lambda: self._authorize(actor_id, change, ATTACH_SCOPE,
                                               {"adapter": request.adapter}),
        )

    def stop_agent(self, change_id: UUID, run_id: UUID, actor_id: UUID) -> AgentRun:
        change = self.change_service.get(change_id)
        self._authorize(actor_id, change, STOP_SCOPE, {"run_id": str(run_id)})
        if all(run.id != run_id for run in self.evidence.agent_runs(change_id)):
            raise AppError("AGENT_RUN_NOT_FOUND", "The agent run does not exist for this Change.",
                           status_code=404)
        return self.evidence.stop_agent(change_id, run_id)

    def list_agent_runs(self, change_id: UUID) -> list[AgentRun]:
        self.change_service.get(change_id)
        return self.evidence.agent_runs(change_id)

    # -- assurance ----------------------------------------------------------

    def plan_assurance(
        self, change_id: UUID, idempotency_key: str | None = None
    ) -> AssurancePlan:
        change = self.change_service.get(change_id)
        return self._once(f"assurance.plan:{change_id}", idempotency_key, {},
                          lambda: self.evidence.plan_assurance(change), _PLAN)

    def latest_plan(self, change_id: UUID) -> AssurancePlan:
        self.change_service.get(change_id)
        plan = self.evidence.latest_plan(change_id)
        if plan is None:
            raise AppError("ASSURANCE_PLAN_NOT_FOUND",
                           "No assurance plan exists for this Change.", status_code=404)
        return plan

    def run_assurance(
        self, change_id: UUID, plan_id: UUID, actor_id: UUID, output_limit_bytes: int,
        idempotency_key: str | None = None,
    ) -> list[AssuranceRun]:
        change = self.change_service.get(change_id)
        body = {"actor": str(actor_id), "plan": str(plan_id), "limit": output_limit_bytes}
        return self._once(
            f"assurance.run:{change_id}", idempotency_key, body,
            lambda: self.evidence.run_assurance(change, plan_id, output_limit_bytes), _RUNS,
            authorize=lambda: self._authorize(actor_id, change, ASSURANCE_RUN_SCOPE,
                                               {"plan_id": str(plan_id)}),
        )

    def evaluate(self, change_id: UUID, plan_id: UUID) -> AssuranceEvaluation:
        return self.evidence.evaluate(self.change_service.get(change_id), plan_id)

    def facts(self, change_id: UUID) -> AssuranceFacts:
        return self.evidence.assurance_facts(self.change_service.get(change_id))
