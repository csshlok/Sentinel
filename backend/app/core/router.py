"""Thin HTTP transport over the shared Change service."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status

from backend.app.contracts.models import (
    Actor,
    ActorCreateRequest,
    CapabilitiesResponse,
    ChangeCancelRequest,
    ChangeContractUpdateRequest,
    ChangeCreateRequest,
    ChangeListResponse,
    ChangePassport,
    ChangeTransitionRequest,
    ChangeView,
    CredentialGrant,
    CredentialGrantRequest,
    Delegation,
    DelegationCreateRequest,
    DelegationListResponse,
    OutcomeListResponse,
    OutcomeRefreshRequest,
    ProviderConnectionStatus,
    ProviderConnectRequest,
    ProviderOperation,
    PullRequestActionRequest,
    RecoveryExecuteRequest,
    RecoveryPlan,
    RepositoryInfo,
    RepositoryPathRequest,
    VerificationRequest,
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
        request: VerificationRequest,
        idempotency_key: IdempotencyHeader = None,
    ) -> ChangeView:
        return service.verify(
            change_id, request, idempotency_key=idempotency_key
        )

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
        "/changes/{change_id}/outcomes/refresh",
        response_model=OutcomeListResponse,
        tags=["outcomes"],
    )
    def refresh_outcomes(
        change_id: UUID, request: OutcomeRefreshRequest
    ) -> OutcomeListResponse:
        items = runtime.outcomes.refresh(
            change_id,
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

    return router
