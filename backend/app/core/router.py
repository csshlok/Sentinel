"""Thin HTTP transport over ChangeService."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from backend.app.contracts.models import (
    ChangeCreateRequest,
    ChangeListResponse,
    ChangeView,
    RepositoryInfo,
    RepositoryPathRequest,
    VerificationRequest,
)
from backend.app.core.change_service import ChangeService


def build_router(service: ChangeService) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

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
    def create_change(request: ChangeCreateRequest) -> ChangeView:
        return service.create(request)

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

    @router.post(
        "/changes/{change_id}/refresh",
        response_model=ChangeView,
        tags=["changes"],
    )
    def refresh_change(change_id: UUID) -> ChangeView:
        return service.refresh(change_id)

    @router.post(
        "/changes/{change_id}/verify",
        response_model=ChangeView,
        tags=["changes"],
    )
    def verify_change(
        change_id: UUID, request: VerificationRequest
    ) -> ChangeView:
        return service.verify(change_id, request)

    @router.delete(
        "/changes/{change_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["changes"],
    )
    def delete_change(change_id: UUID) -> Response:
        service.delete(change_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router

