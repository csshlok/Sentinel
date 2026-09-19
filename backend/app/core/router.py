"""Thin HTTP transport over the shared Change service."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response, status

from backend.app.contracts.models import (
    CapabilitiesResponse,
    ChangeCancelRequest,
    ChangeContractUpdateRequest,
    ChangeCreateRequest,
    ChangeListResponse,
    ChangeTransitionRequest,
    ChangeView,
    RepositoryInfo,
    RepositoryPathRequest,
    VerificationRequest,
)
from backend.app.core.change_service import ChangeService


IdempotencyHeader = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


def build_router(service: ChangeService) -> APIRouter:
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

    return router
