"""Thin HTTP transport over the shared Change service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response, status
from starlette.concurrency import run_in_threadpool

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
    ActorListResponse,
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
    DiffCoverageRequest,
    DiffCoverageResult,
    GitCheckpointComparison,
    GitCheckpointListResponse,
    GitHubAppConfigurationStatus,
    GitHubAppFlowRequest,
    GitHubAppFlowResult,
    GitHubCheckPublicationResult,
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
    SignedPassportExport,
    PassportV2Issued,
    PolicyPresetEvaluation,
    ProductVersionResponse,
    SigningPublicKeyResponse,
    ToolManifest,
    ToolManifestListResponse,
    ToolTrustDecision,
    ToolDeclareRequest,
    ToolTrustRequest,
    VerificationActionRequest,
    ChangeWorkspace,
    WorkspaceActionRequest,
    WorkspaceApplyPreview,
    WorkspaceApplyRequest,
    WorkspaceApplyResult,
    WorkspaceSweepReport,
)
from backend.app.core.change_service import ChangeService
from backend.app.core.runtime_service import RuntimeServices
from backend.app.core.errors import AppError, adapter_unavailable
from backend.app.passport.v2 import PassportV2Issuer
from backend.app.passport.bundle import BundleExporter
from backend.app.providers.github_app import GitHubAppManifestFlows, app_provider_name
from backend.app.providers.github_check import GitHubCheckPublisher
from backend.app.providers.http_transport import UrllibHttpTransport
from backend.app.policy.version import product_version


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
    github_app_flows = GitHubAppManifestFlows(runtime.credentials.broker)

    @router.get(
        "/capabilities",
        response_model=CapabilitiesResponse,
        tags=["system"],
    )
    def capabilities() -> CapabilitiesResponse:
        return service.capabilities()

    @router.get("/version", response_model=ProductVersionResponse, tags=["system"])
    def version() -> ProductVersionResponse:
        return ProductVersionResponse(product_version=product_version())

    @router.get(
        "/changes/{change_id}/policy/preset",
        response_model=PolicyPresetEvaluation,
        tags=["policy"],
    )
    async def evaluate_change_preset(change_id: UUID) -> PolicyPresetEvaluation:
        def evaluate() -> PolicyPresetEvaluation:
            service.get(change_id)
            snapshot = PassportV2Issuer(service.repository.database).snapshot(change_id)
            return PolicyPresetEvaluation(
                change_id=change_id,
                preset_name=snapshot.policy_preset_name,
                preset_version=snapshot.policy_preset_version,
                change_type=snapshot.policy_change_type,
                decision=snapshot.policy_decision,
                denials=snapshot.policy_denials,
                freshness=snapshot.diff_coverage.freshness,
            )
        return await run_in_threadpool(evaluate)

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

    @router.get("/actors", response_model=ActorListResponse, tags=["identity"])
    def list_actors(
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ActorListResponse:
        return runtime.identity.list_actors(limit=limit, offset=offset)

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
        "/providers/github/app/flows",
        response_model=GitHubAppFlowResult,
        status_code=status.HTTP_201_CREATED,
        tags=["providers"],
    )
    def create_github_app_flow(request: GitHubAppFlowRequest) -> GitHubAppFlowResult:
        try:
            view = github_app_flows.create(owner=request.owner,
                                           account_kind=request.account_kind)
        except ValueError as exc:
            raise AppError("GITHUB_APP_FLOW_INVALID", str(exc), status_code=422) from exc
        return GitHubAppFlowResult.model_validate(asdict(view))

    @router.get(
        "/providers/github/app/flows/{flow_id}",
        response_model=GitHubAppFlowResult,
        tags=["providers"],
    )
    def get_github_app_flow(flow_id: str) -> GitHubAppFlowResult:
        view = github_app_flows.get(flow_id)
        if view is None:
            raise AppError("GITHUB_APP_FLOW_NOT_FOUND", "GitHub App flow not found.",
                           status_code=404)
        return GitHubAppFlowResult.model_validate(asdict(view))

    @router.get(
        "/providers/github/app/status/{owner}",
        response_model=GitHubAppConfigurationStatus,
        tags=["providers"],
    )
    def github_app_status(owner: str) -> GitHubAppConfigurationStatus:
        try:
            provider = app_provider_name(owner)
        except ValueError as exc:
            raise AppError("GITHUB_APP_OWNER_INVALID", "Invalid GitHub account name.",
                           status_code=422) from exc
        return GitHubAppConfigurationStatus(
            owner=owner, configured=runtime.credentials.is_configured(provider),
        )

    @router.post(
        "/changes/{change_id}/providers/github/checks",
        response_model=GitHubCheckPublicationResult,
        tags=["providers"],
    )
    async def publish_github_check(change_id: UUID, request: Request,
                                   decline_app: bool = False) -> GitHubCheckPublicationResult:
        if await request.body():
            raise AppError("GITHUB_CHECK_PAYLOAD_FORBIDDEN",
                           "GitHub Checks are built only from Sentinel's Change records.",
                           status_code=422)
        def publish() -> GitHubCheckPublicationResult:
            service.get(change_id)
            operation = runtime.provider_operations.operations.get_succeeded_operation(
                change_id, "github.pr.create")
            if operation is None:
                raise AppError("GITHUB_CHECK_PR_MISSING",
                               "Change has no recorded GitHub pull request.", status_code=409)
            grant = runtime.credentials.issue_grant(
                operation.request.actor_id, change_id, ["github.pr.create"], 30)
            try:
                fallback_token = (runtime.credentials.broker.resolve_secret(
                    grant.id, scope="github.pr.create") if decline_app else None)
            finally:
                runtime.credentials.revoke_grant(grant.id)
            try:
                view = GitHubCheckPublisher(
                    service.repository.database, runtime.credentials.broker,
                    UrllibHttpTransport(),
                ).publish(change_id, decline_app=decline_app,
                          fallback_token=fallback_token)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise AppError("GITHUB_CHECK_UNAVAILABLE",
                               "GitHub Check could not be published from current evidence.",
                               status_code=409) from exc
            return GitHubCheckPublicationResult.model_validate(asdict(view))
        return await run_in_threadpool(publish)

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

    @router.post(
        "/changes/{change_id}/passport/export",
        response_model=SignedPassportExport,
        tags=["passport"],
    )
    def export_passport(change_id: UUID) -> SignedPassportExport:
        return runtime.passport.export(change_id)

    @router.post(
        "/changes/{change_id}/passport/v2/issue",
        response_model=PassportV2Issued,
        tags=["passport"],
    )
    async def issue_passport_v2(change_id: UUID, request: Request) -> PassportV2Issued:
        if await request.body():
            raise AppError("PASSPORT_PAYLOAD_FORBIDDEN",
                           "Passport v2 is issued only from Sentinel's Change records.")
        def issue() -> PassportV2Issued:
            service.get(change_id)
            return PassportV2Issuer(service.repository.database).issue(change_id)
        return await run_in_threadpool(issue)

    @router.post(
        "/changes/{change_id}/passport/v2/bundle",
        response_class=Response,
        tags=["passport"],
        responses={200: {"content": {"application/vnd.sentinel.passport+zip": {}}}},
    )
    async def export_passport_v2_bundle(change_id: UUID, request: Request) -> Response:
        if await request.body():
            raise AppError("PASSPORT_PAYLOAD_FORBIDDEN",
                           "Portable Passport is exported only from Sentinel's Change records.")
        def export():
            service.get(change_id)
            return BundleExporter(service.repository.database).export(change_id)
        artifact = await run_in_threadpool(export)
        return Response(
            content=artifact.content,
            media_type="application/vnd.sentinel.passport+zip",
            headers={
                "Content-Disposition": f'attachment; filename="{artifact.filename}"',
                "X-Sentinel-Payload-SHA256": artifact.payload_sha256,
            },
        )

    @router.get(
        "/identity/signing-key",
        response_model=SigningPublicKeyResponse,
        tags=["identity"],
    )
    def get_signing_public_key() -> SigningPublicKeyResponse:
        return SigningPublicKeyResponse(public_key=runtime.passport.public_key())

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

    # -- Claude-owned: Sentinel workspace (AppContainer clone, apply-back) -----

    def _workspace():
        if runtime.workspace is None:
            raise adapter_unavailable("workspace")
        return runtime.workspace

    @router.get(
        "/changes/{change_id}/workspace",
        response_model=ChangeWorkspace,
        tags=["workspace"],
    )
    def get_workspace(change_id: UUID) -> ChangeWorkspace:
        return _workspace().show(change_id)

    @router.post(
        "/changes/{change_id}/workspace/preview",
        response_model=WorkspaceApplyPreview,
        tags=["workspace"],
    )
    def preview_workspace(change_id: UUID) -> WorkspaceApplyPreview:
        return _workspace().preview(change_id)

    @router.post(
        "/changes/{change_id}/workspace/apply",
        response_model=WorkspaceApplyResult,
        tags=["workspace"],
    )
    def apply_workspace(change_id: UUID, request: WorkspaceApplyRequest) -> WorkspaceApplyResult:
        return _workspace().apply(change_id, request)

    @router.post(
        "/changes/{change_id}/workspace/discard",
        response_model=ChangeWorkspace,
        tags=["workspace"],
    )
    def discard_workspace(change_id: UUID, request: WorkspaceActionRequest) -> ChangeWorkspace:
        return _workspace().discard(change_id, request)

    @router.post(
        "/workspaces/sweep",
        response_model=WorkspaceSweepReport,
        tags=["workspace"],
    )
    def sweep_workspaces() -> WorkspaceSweepReport:
        return _workspace().sweep()

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

    @router.post(
        "/changes/{change_id}/assurance/diff-coverage",
        response_model=DiffCoverageResult,
        tags=["assurance"],
    )
    def measure_diff_coverage(
        change_id: UUID, request: DiffCoverageRequest,
    ) -> DiffCoverageResult:
        return runtime.evidence.evidence.measure_diff_coverage(
            service.get(change_id), request, current_change=lambda: service.get(change_id))

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
