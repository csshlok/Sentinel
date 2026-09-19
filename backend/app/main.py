"""FastAPI composition root for the local-only Change Assurance API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.contracts.models import ErrorDetail, ErrorEnvelope, HealthResponse
from backend.app.contracts.ports import GitInspectionPort, VerificationPort
from backend.app.core.change_repository import ChangeRepository
from backend.app.core.change_service import ChangeService
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.router import build_router
from backend.app.core.unavailable_adapters import (
    UnavailableGitInspection,
    UnavailableVerification,
)


LOGGER = logging.getLogger(__name__)
API_VERSION = "1"


def _error_response(
    *, code: str, message: str, status_code: int, details: dict | None = None
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, details=details or {})
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
    )


def create_app(
    *,
    settings: Settings | None = None,
    git_inspection: GitInspectionPort | None = None,
    verification: VerificationPort | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    database = Database(resolved_settings.database_path)
    repository = ChangeRepository(database)
    service = ChangeService(
        repository=repository,
        git_inspection=git_inspection or UnavailableGitInspection(),
        verification=verification or UnavailableVerification(),
        settings=resolved_settings,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        yield

    app = FastAPI(
        title="Change Assurance API",
        version=API_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.ui_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, error: AppError) -> JSONResponse:
        return _error_response(
            code=error.code,
            message=error.message,
            status_code=error.status_code,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {
                "location": list(item.get("loc", ())),
                "message": item.get("msg", "Invalid value"),
                "type": item.get("type", "validation_error"),
            }
            for item in error.errors()
        ]
        return _error_response(
            code="VALIDATION_ERROR",
            message="The request did not match the API contract.",
            status_code=422,
            details={"errors": safe_errors},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled API error", exc_info=error)
        return _error_response(
            code="INTERNAL_ERROR",
            message="The request could not be completed.",
            status_code=500,
        )

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", api_version=API_VERSION)

    app.include_router(build_router(service))
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.change_service = service
    return app


app = create_app()

