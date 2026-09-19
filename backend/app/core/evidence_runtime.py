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

from uuid import UUID

from backend.app.assurance.models import AssuranceEvaluation
from backend.app.assurance.service import (
    AssuranceFacts, EvidenceOverview, EvidenceService, EvidenceSnapshot,
)
from backend.app.contracts.models import (
    AgentAdapterInfo, AgentAttachRequest, AgentLaunchRequest, AgentRun, AssurancePlan,
    AssuranceRun, ChangeView,
)
from backend.app.contracts.ports import PolicyPort
from backend.app.core.change_service import ChangeService
from backend.app.core.errors import AppError, policy_denied

LAUNCH_SCOPE = "agent.launch"
ATTACH_SCOPE = "agent.attach"
STOP_SCOPE = "agent.stop"
ASSURANCE_RUN_SCOPE = "assurance.run"


class EvidenceAdminService:
    def __init__(
        self, evidence: EvidenceService, policy: PolicyPort, change_service: ChangeService
    ) -> None:
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

    def capture_baseline(self, change_id: UUID) -> EvidenceSnapshot:
        return self.evidence.capture_baseline(self.change_service.get(change_id))

    def capture_current(self, change_id: UUID) -> EvidenceSnapshot:
        return self.evidence.capture_current(self.change_service.get(change_id))

    # -- agents -------------------------------------------------------------

    def adapters(self, change_id: UUID | None = None) -> list[AgentAdapterInfo]:
        path = self.change_service.get(change_id).repository_path if change_id else None
        return [AgentAdapterInfo.model_validate(item) for item in self.evidence.adapters(path)]

    def launch_agent(
        self, change_id: UUID, actor_id: UUID, request: AgentLaunchRequest,
        output_limit_bytes: int,
    ) -> AgentRun:
        change = self.change_service.get(change_id)
        self._authorize(actor_id, change, LAUNCH_SCOPE,
                        {"adapter": request.adapter, "executable": request.executable})
        return self.evidence.launch_agent(change, request, output_limit_bytes)

    def attach_agent(
        self, change_id: UUID, actor_id: UUID, request: AgentAttachRequest
    ) -> AgentRun:
        change = self.change_service.get(change_id)
        self._authorize(actor_id, change, ATTACH_SCOPE, {"adapter": request.adapter})
        return self.evidence.attach_agent(change, request)

    def stop_agent(self, change_id: UUID, run_id: UUID, actor_id: UUID) -> AgentRun:
        change = self.change_service.get(change_id)
        self._authorize(actor_id, change, STOP_SCOPE, {"run_id": str(run_id)})
        if all(run.id != run_id for run in self.evidence.agent_runs(change_id)):
            raise AppError("AGENT_RUN_NOT_FOUND", "The agent run does not exist for this Change.",
                           status_code=404)
        return self.evidence.stop_agent(run_id)

    def list_agent_runs(self, change_id: UUID) -> list[AgentRun]:
        self.change_service.get(change_id)
        return self.evidence.agent_runs(change_id)

    # -- assurance ----------------------------------------------------------

    def plan_assurance(self, change_id: UUID) -> AssurancePlan:
        return self.evidence.plan_assurance(self.change_service.get(change_id))

    def latest_plan(self, change_id: UUID) -> AssurancePlan:
        self.change_service.get(change_id)
        plan = self.evidence.latest_plan(change_id)
        if plan is None:
            raise AppError("ASSURANCE_PLAN_NOT_FOUND",
                           "No assurance plan exists for this Change.", status_code=404)
        return plan

    def run_assurance(
        self, change_id: UUID, plan_id: UUID, actor_id: UUID, output_limit_bytes: int
    ) -> list[AssuranceRun]:
        change = self.change_service.get(change_id)
        self._authorize(actor_id, change, ASSURANCE_RUN_SCOPE, {"plan_id": str(plan_id)})
        return self.evidence.run_assurance(change, plan_id, output_limit_bytes)

    def evaluate(self, change_id: UUID, plan_id: UUID) -> AssuranceEvaluation:
        return self.evidence.evaluate(self.change_service.get(change_id), plan_id)

    def facts(self, change_id: UUID) -> AssuranceFacts:
        return self.evidence.assurance_facts(self.change_service.get(change_id))
