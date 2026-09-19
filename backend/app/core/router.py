"""Thin HTTP transport over the shared Change service."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status

from backend.app.assurance.models import AssuranceEvaluation
from backend.app.assurance.service import (
    AssuranceFacts,
    EnvironmentView,
    EvidenceOverview,
    EvidenceSnapshot,
)
from backend.app.contracts.models import (
    ActorActionRequest,
    Actor,
    ActorCreateRequest,
    AgentAdapterListResponse,
    AgentAttachActionRequest,
    AgentLaunchActionRequest,
    AgentRun,
    AgentRunListResponse,
    AssurancePlan,
    AssuranceRunActionRequest,
    AssuranceRunListResponse,
    ChainVerificationResult,
    DependencyReport,
    GitCheckpointComparison,
    GitCheckpointListResponse,
    CapabilitiesResponse,
    ChangeCancelRequest,
    ChangeContractUpdateRequest,
    ChangeCreateRequest,
    ChangeForkActionRequest,
    ChangeListResponse,
    ChangePassport,
    ChangeTransitionRequest,
    ChangeView,
    CredentialGrant,
    CredentialGrantRequest,
    Delegation,
    DelegationCreateRequest,
    DelegationListResponse,
    JournalEventListResponse,
    JournalEventType,
    OutcomeListResponse,
    OutcomeRefreshRequest,
    ProviderConnectionStatus,
    ProviderConnectRequest,
    ProviderOperation,
    PullRequestActionRequest,
    PullRequestCloseActionRequest,
    RecoveryExecuteRequest,
    RecoveryPlan,
    ReplayTimeline,
    RepositoryInfo,
    RepositoryPathRequest,
    ToolManifest,
    ToolManifestListResponse,
    ToolTrustDecision,
    ToolDeclareRequest,
    ToolTrustRequest,
    VerificationActionRequest,
)
from backend.app.core.change_service import ChangeService
from backend.app.core.runtime_service import RuntimeServices


IdempotencyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


def build_router(service: ChangeService, runtime: RuntimeServices) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/capabilities",
        response_model=CapabilitiesResponse,
        tags=["system"],
    )
    def capabilities() -> CapabilitiesResponse:
        return service.capabilities()

    @router.post(
        "/repositories/validate",
        response_model=RepositoryInfo,
        tags=["repositories"],
    )
    def validate_repository(request: RepositoryPathRequest) -> RepositoryInfo:
        return service.validate_repository(request.path)

    @router.post(
        "/changes",
        response_model=ChangeView,
        status_code=status.HTTP_201_CREATED,
        tags=["changes"],
    )
    def create_change(
        request: ChangeCreateRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.create(request, idempotency_key=idempotency_key)

    @router.get(
        "/changes",
        response_model=ChangeListResponse,
        tags=["changes"],
    )
    def list_changes(
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ChangeListResponse:
        return service.list(limit=limit, offset=offset)

    @router.get(
        "/changes/{change_id}",
        response_model=ChangeView,
        tags=["changes"],
    )
    def get_change(change_id: UUID) -> ChangeView:
        return service.get(change_id)

    @router.put(
        "/changes/{change_id}/contract",
        response_model=ChangeView,
        tags=["changes"],
    )
    def update_change_contract(
        change_id: UUID,
        request: ChangeContractUpdateRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.update_contract(
            change_id, request, idempotency_key=idempotency_key
        )

    @router.post(
        "/changes/{change_id}/transition",
        response_model=ChangeView,
        tags=["changes"],
    )
    def transition_change(
        change_id: UUID,
        request: ChangeTransitionRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.transition(
            change_id, request, idempotency_key=idempotency_key
        )

    @router.post(
        "/changes/{change_id}/cancel",
        response_model=ChangeView,
        tags=["changes"],
    )
    def cancel_change(
        change_id: UUID,
        request: ChangeCancelRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.cancel(change_id, request, idempotency_key=idempotency_key)

    @router.post(
        "/changes/{change_id}/refresh",
        response_model=ChangeView,
        tags=["changes"],
    )
    def refresh_change(
        change_id: UUID,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.refresh(change_id, idempotency_key=idempotency_key)

    @router.post(
        "/changes/{change_id}/verify",
        response_model=ChangeView,
        tags=["changes"],
    )
    def verify_change(
        change_id: UUID,
        request: VerificationActionRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.verify(
            change_id, request.actor_id, request.verification,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/changes/{change_id}/fork",
        response_model=ChangeView,
        status_code=status.HTTP_201_CREATED,
        tags=["changes"],
    )
    def fork_change(change_id: UUID, request: ChangeForkActionRequest) -> ChangeView:
        return runtime.evidence.fork_change(change_id, request.actor_id, request.fork)

    @router.get(
        "/changes/{change_id}/forks",
        response_model=ChangeListResponse,
        tags=["changes"],
    )
    def list_change_forks(change_id: UUID) -> ChangeListResponse:
        return runtime.evidence.forks(change_id)

    @router.delete(
        "/changes/{change_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["changes"],
    )
    def delete_change(
        change_id: UUID,
        idempotency_key: IdempotencyHeader = None,
    ) -> Response:
        service.delete(change_id, idempotency_key=idempotency_key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/actors",
        response_model=Actor,
        status_code=status.HTTP_201_CREATED,
        tags=["identity"],
    )
    def create_actor(request: ActorCreateRequest) -> Actor:
        return runtime.identity.create_actor(request)

    @router.get("/actors/{actor_id}", response_model=Actor, tags=["identity"])
    def get_actor(actor_id: UUID) -> Actor:
        return runtime.identity.get_actor(actor_id)

    @router.post(
        "/delegations",
        response_model=Delegation,
        status_code=status.HTTP_201_CREATED,
        tags=["identity"],
    )
    def create_delegation(request: DelegationCreateRequest) -> Delegation:
        change = service.get(request.change_id)
        return runtime.identity.create_delegation(
            request, repository_path=change.repository_path
        )

    @router.get(
        "/delegations/{delegation_id}", response_model=Delegation, tags=["identity"]
    )
    def get_delegation(delegation_id: UUID) -> Delegation:
        return runtime.identity.get_delegation(delegation_id)

    @router.post(
        "/delegations/{delegation_id}/revoke",
        response_model=Delegation,
        tags=["identity"],
    )
    def revoke_delegation(delegation_id: UUID) -> Delegation:
        return runtime.identity.revoke_delegation(delegation_id)

    @router.get(
        "/changes/{change_id}/delegations",
        response_model=DelegationListResponse,
        tags=["identity"],
    )
    def list_delegations(change_id: UUID) -> DelegationListResponse:
        items = runtime.identity.list_delegations_for_change(change_id)
        return DelegationListResponse(items=items, count=len(items))

    @router.post(
        "/providers/github/connect",
        response_model=ProviderConnectionStatus,
        tags=["providers"],
    )
    def connect_github(request: ProviderConnectRequest) -> ProviderConnectionStatus:
        runtime.credentials.connect("github", request.token)
        return ProviderConnectionStatus(provider="github", configured=True)

    @router.post(
        "/providers/github/disconnect",
        response_model=ProviderConnectionStatus,
        tags=["providers"],
    )
    def disconnect_github() -> ProviderConnectionStatus:
        runtime.credentials.disconnect("github")
        return ProviderConnectionStatus(provider="github", configured=False)

    @router.get(
        "/providers/github/status",
        response_model=ProviderConnectionStatus,
        tags=["providers"],
    )
    def github_status() -> ProviderConnectionStatus:
        return ProviderConnectionStatus(
            provider="github", configured=runtime.credentials.is_configured("github")
        )

    @router.post(
        "/changes/{change_id}/providers/github/grants",
        response_model=CredentialGrant,
        status_code=status.HTTP_201_CREATED,
        tags=["providers"],
    )
    def issue_github_grant(
        change_id: UUID, request: CredentialGrantRequest
    ) -> CredentialGrant:
        return runtime.credentials.issue_grant(
            request.actor_id, change_id, request.scopes, request.ttl_seconds
        )

    @router.post(
        "/changes/{change_id}/providers/github/grants/{grant_id}/revoke",
        response_model=CredentialGrant,
        tags=["providers"],
    )
    def revoke_github_grant(change_id: UUID, grant_id: UUID) -> CredentialGrant:
        del change_id
        return runtime.credentials.revoke_grant(grant_id)

    @router.post(
        "/changes/{change_id}/providers/github/pulls",
        response_model=ProviderOperation,
        tags=["providers"],
    )
    def create_pull_request(
        change_id: UUID, request: PullRequestActionRequest
    ) -> ProviderOperation:
        return runtime.provider_operations.create_pull_request(
            change_id,
            actor_id=request.actor_id,
            grant_id=request.grant_id,
            base_branch=request.base_branch,
            head_branch=request.head_branch,
            title=request.title,
            idempotency_key=request.idempotency_key,
        )

    @router.post(
        "/changes/{change_id}/providers/github/pulls/close",
        response_model=ProviderOperation,
        tags=["providers"],
    )
    def close_pull_request(
        change_id: UUID, request: PullRequestCloseActionRequest
    ) -> ProviderOperation:
        return runtime.provider_operations.close_pull_request(
            change_id,
            actor_id=request.actor_id,
            grant_id=request.grant_id,
            idempotency_key=request.idempotency_key,
        )

    @router.post(
        "/changes/{change_id}/outcomes/refresh",
        response_model=OutcomeListResponse,
        tags=["outcomes"],
    )
    def refresh_outcomes(
        change_id: UUID, request: OutcomeRefreshRequest
    ) -> OutcomeListResponse:
        items = runtime.outcomes.refresh(
            change_id,
            actor_id=request.actor_id,
            grant_id=request.grant_id,
            required_check_names=request.required_check_names,
        )
        return OutcomeListResponse(items=items, count=len(items))

    @router.get(
        "/changes/{change_id}/outcomes",
        response_model=OutcomeListResponse,
        tags=["outcomes"],
    )
    def list_outcomes(change_id: UUID) -> OutcomeListResponse:
        items = runtime.outcomes.list_for_change(change_id)
        return OutcomeListResponse(items=items, count=len(items))

    @router.post(
        "/changes/{change_id}/recovery/preview",
        response_model=RecoveryPlan,
        status_code=status.HTTP_201_CREATED,
        tags=["recovery"],
    )
    def preview_recovery(change_id: UUID) -> RecoveryPlan:
        return runtime.recovery.preview(change_id)

    @router.post(
        "/changes/{change_id}/recovery/{plan_id}/execute",
        response_model=RecoveryPlan,
        tags=["recovery"],
    )
    def execute_recovery(
        change_id: UUID, plan_id: UUID, request: RecoveryExecuteRequest
    ) -> RecoveryPlan:
        return runtime.recovery.execute(
            change_id,
            plan_id,
            actor_id=request.actor_id,
            approval_token=request.approval_token,
        )

    @router.get(
        "/changes/{change_id}/recovery",
        response_model=RecoveryPlan,
        tags=["recovery"],
    )
    def get_latest_recovery(change_id: UUID) -> RecoveryPlan:
        return runtime.recovery.latest(change_id)

    @router.post(
        "/changes/{change_id}/passport",
        response_model=ChangePassport,
        status_code=status.HTTP_201_CREATED,
        tags=["passport"],
    )
    def build_passport(change_id: UUID) -> ChangePassport:
        return runtime.passport.build(change_id)

    @router.get(
        "/changes/{change_id}/passport",
        response_model=ChangePassport,
        tags=["passport"],
    )
    def get_latest_passport(change_id: UUID) -> ChangePassport:
        return runtime.passport.latest(change_id)

    # -- Person 2 stream: evidence, agents, assurance -------------------------

    @router.get(
        "/changes/{change_id}/evidence",
        response_model=EvidenceOverview,
        tags=["evidence"],
    )
    def get_evidence(change_id: UUID) -> EvidenceOverview:
        return runtime.evidence.overview(change_id)

    @router.post(
        "/changes/{change_id}/evidence/baseline",
        response_model=EvidenceSnapshot,
        status_code=status.HTTP_201_CREATED,
        tags=["evidence"],
    )
    def capture_baseline(
        change_id: UUID, idempotency_key: IdempotencyHeader = None
    ) -> EvidenceSnapshot:
        return runtime.evidence.capture_baseline(change_id, idempotency_key)

    @router.post(
        "/changes/{change_id}/evidence/current",
        response_model=EvidenceSnapshot,
        status_code=status.HTTP_201_CREATED,
        tags=["evidence"],
    )
    def capture_current_evidence(
        change_id: UUID, idempotency_key: IdempotencyHeader = None
    ) -> EvidenceSnapshot:
        return runtime.evidence.capture_current(change_id, idempotency_key)

    @router.get(
        "/changes/{change_id}/git/checkpoints",
        response_model=GitCheckpointListResponse,
        tags=["evidence"],
    )
    def list_git_checkpoints(change_id: UUID) -> GitCheckpointListResponse:
        items = runtime.evidence.checkpoints(change_id)
        return GitCheckpointListResponse(items=items, count=len(items))

    @router.get(
        "/changes/{change_id}/git/compare",
        response_model=GitCheckpointComparison,
        tags=["evidence"],
    )
    def compare_git_checkpoints(
        change_id: UUID, baseline_id: UUID, current_id: UUID
    ) -> GitCheckpointComparison:
        return runtime.evidence.compare_checkpoints(change_id, baseline_id, current_id)

    @router.get(
        "/changes/{change_id}/environment",
        response_model=EnvironmentView,
        tags=["evidence"],
    )
    def get_environment(change_id: UUID) -> EnvironmentView:
        return runtime.evidence.environment(change_id)

    @router.get(
        "/changes/{change_id}/dependencies",
        response_model=DependencyReport,
        tags=["evidence"],
    )
    def get_dependencies(change_id: UUID) -> DependencyReport:
        return runtime.evidence.dependencies(change_id)

    @router.get(
        "/agents/adapters",
        response_model=AgentAdapterListResponse,
        tags=["agents"],
    )
    def list_agent_adapters() -> AgentAdapterListResponse:
        items = runtime.evidence.adapters()
        return AgentAdapterListResponse(items=items, count=len(items))

    @router.get(
        "/changes/{change_id}/agents",
        response_model=AgentRunListResponse,
        tags=["agents"],
    )
    def list_agent_runs(change_id: UUID) -> AgentRunListResponse:
        items = runtime.evidence.list_agent_runs(change_id)
        return AgentRunListResponse(items=items, count=len(items))

    @router.post(
        "/changes/{change_id}/agents/launch",
        response_model=AgentRun,
        status_code=status.HTTP_201_CREATED,
        tags=["agents"],
    )
    def launch_agent(
        change_id: UUID,
        request: AgentLaunchActionRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> AgentRun:
        return runtime.evidence.launch_agent(
            change_id, request.actor_id, request.launch, request.output_limit_bytes,
            idempotency_key=idempotency_key,
        )

    @router.post(
        "/changes/{change_id}/agents/attach",
        response_model=AgentRun,
        status_code=status.HTTP_201_CREATED,
        tags=["agents"],
    )
    def attach_agent(
        change_id: UUID,
        request: AgentAttachActionRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> AgentRun:
        return runtime.evidence.attach_agent(
            change_id, request.actor_id, request.attach, idempotency_key=idempotency_key
        )

    @router.post(
        "/changes/{change_id}/agents/{run_id}/stop",
        response_model=AgentRun,
        tags=["agents"],
    )
    def stop_agent(change_id: UUID, run_id: UUID, request: ActorActionRequest) -> AgentRun:
        return runtime.evidence.stop_agent(change_id, run_id, request.actor_id)

    @router.post(
        "/changes/{change_id}/agents/{run_id}/pause",
        response_model=AgentRun,
        tags=["agents"],
    )
    def pause_agent(change_id: UUID, run_id: UUID, request: ActorActionRequest) -> AgentRun:
        return runtime.evidence.pause_agent(change_id, run_id, request.actor_id)

    @router.post(
        "/changes/{change_id}/agents/{run_id}/resume",
        response_model=AgentRun,
        tags=["agents"],
    )
    def resume_agent(change_id: UUID, run_id: UUID, request: ActorActionRequest) -> AgentRun:
        return runtime.evidence.resume_agent(change_id, run_id, request.actor_id)

    @router.post(
        "/changes/{change_id}/assurance/plan",
        response_model=AssurancePlan,
        status_code=status.HTTP_201_CREATED,
        tags=["assurance"],
    )
    def plan_assurance(
        change_id: UUID, idempotency_key: IdempotencyHeader = None
    ) -> AssurancePlan:
        return runtime.evidence.plan_assurance(change_id, idempotency_key)

    @router.get(
        "/changes/{change_id}/assurance/plan",
        response_model=AssurancePlan,
        tags=["assurance"],
    )
    def get_latest_assurance_plan(change_id: UUID) -> AssurancePlan:
        return runtime.evidence.latest_plan(change_id)

    @router.post(
        "/changes/{change_id}/assurance/{plan_id}/run",
        response_model=AssuranceRunListResponse,
        tags=["assurance"],
    )
    def run_assurance(
        change_id: UUID,
        plan_id: UUID,
        request: AssuranceRunActionRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> AssuranceRunListResponse:
        items = runtime.evidence.run_assurance(
            change_id, plan_id, request.actor_id, request.output_limit_bytes,
            idempotency_key=idempotency_key,
        )
        return AssuranceRunListResponse(items=items, count=len(items))

    @router.get(
        "/changes/{change_id}/assurance/{plan_id}/evaluation",
        response_model=AssuranceEvaluation,
        tags=["assurance"],
    )
    def evaluate_assurance(change_id: UUID, plan_id: UUID) -> AssuranceEvaluation:
        return runtime.evidence.evaluate(change_id, plan_id)

    @router.get(
        "/changes/{change_id}/assurance/facts",
        response_model=AssuranceFacts,
        tags=["assurance"],
    )
    def get_assurance_facts(change_id: UUID) -> AssuranceFacts:
        return runtime.evidence.facts(change_id)

    # -- Event/Effect Journal + Replay (trace-only; see A.7 non-goals) --------

    @router.get(
        "/changes/{change_id}/events",
        response_model=JournalEventListResponse,
        tags=["journal"],
    )
    def list_journal_events(
        change_id: UUID,
        event_type: JournalEventType | None = None,
        since_seq: Annotated[int, Query(ge=1)] = 1,
        limit: Annotated[int, Query(ge=1, le=10_000)] = 1000,
    ) -> JournalEventListResponse:
        service.get(change_id)  # 404s honestly for an unknown Change
        timeline = runtime.replay.reconstruct(change_id)
        items = [
            e for e in timeline.events
            if e.seq >= since_seq and (event_type is None or e.event_type is event_type)
        ][:limit]
        return JournalEventListResponse(items=items, count=len(items))

    @router.get(
        "/changes/{change_id}/replay",
        response_model=ReplayTimeline,
        tags=["journal"],
    )
    def get_replay(change_id: UUID) -> ReplayTimeline:
        service.get(change_id)
        return runtime.replay.reconstruct(change_id)

    @router.get(
        "/changes/{change_id}/replay/verify",
        response_model=ChainVerificationResult,
        tags=["journal"],
    )
    def verify_replay(change_id: UUID) -> ChainVerificationResult:
        service.get(change_id)
        return runtime.replay.verify_chain(change_id)

    @router.get(
        "/changes/{change_id}/replay/export",
        response_model=ReplayTimeline,
        tags=["journal"],
    )
    def export_replay(change_id: UUID) -> ReplayTimeline:
        service.get(change_id)
        return runtime.replay.export(change_id)

    # -- Tool Registry (bounded scope: top-level executable + declared -------
    # manifests only; see B.1/B.10 non-goals echoed in every response) --------

    @router.get(
        "/tools",
        response_model=ToolManifestListResponse,
        tags=["tools"],
    )
    def list_tools() -> ToolManifestListResponse:
        items = runtime.tools.list()
        return ToolManifestListResponse(items=items, count=len(items))

    @router.get(
        "/tools/{tool_id}",
        response_model=ToolManifest,
        tags=["tools"],
    )
    def get_tool(tool_id: UUID) -> ToolManifest:
        return runtime.tools.get(tool_id)

    @router.post(
        "/tools/{tool_id}/trust",
        response_model=ToolTrustDecision,
        tags=["tools"],
    )
    def decide_tool_trust(tool_id: UUID, request: ToolTrustRequest) -> ToolTrustDecision:
        if request.change_id is not None:
            service.get(request.change_id)
        return runtime.tools.decide_trust(
            tool_id, request.actor_id, request.decision.value, request.scope.value,
            request.reason, request.change_id,
        )

    @router.get(
        "/changes/{change_id}/tools",
        response_model=ToolManifestListResponse,
        tags=["tools"],
    )
    def list_tools_for_change(change_id: UUID) -> ToolManifestListResponse:
        service.get(change_id)
        items = runtime.tools.list_for_change(change_id)
        return ToolManifestListResponse(items=items, count=len(items))

    @router.post(
        "/changes/{change_id}/tools/declare",
        response_model=ToolManifest,
        status_code=status.HTTP_201_CREATED,
        tags=["tools"],
    )
    def declare_tool_manifest(change_id: UUID, request: ToolDeclareRequest) -> ToolManifest:
        service.get(change_id)
        return runtime.tools.declare_manifest(change_id, request.manifest_path)

    return router
