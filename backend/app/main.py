"""FastAPI composition root for the local-only Change Assurance API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.assurance.service import EvidenceService
from backend.app.assurance.store import EvidenceStore, IdempotencyStore
from backend.app.contracts.models import ErrorDetail, ErrorEnvelope, HealthResponse
from backend.app.contracts.ports import (
    CredentialStorePort,
    GitInspectionPort,
    LifecycleFactsPort,
    VerificationPort,
)
from backend.app.core.auth import load_or_create_api_token, require_bearer_token
from backend.app.core.change_repository import ChangeRepository
from backend.app.core.change_service import ChangeService
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.core.evidence_runtime import EvidenceAdminService
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.core.lifecycle_facts_service import RuntimeLifecycleFacts
from backend.app.core.router import build_router
from backend.app.core.runtime_repositories import (
    CredentialGrantRepository,
    OutcomeRepository,
    PassportRepository,
    ProviderOperationRepository,
    RecoveryRepository,
)
from backend.app.core.runtime_service import (
    CredentialAdminService,
    IdentityAdminService,
    OutcomeService,
    PassportService,
    ProviderOperationService,
    RecoveryService,
    RuntimeServices,
)
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.windows_store import WindowsCredentialStore
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.identity.repository import ActorRepository, DelegationRepository
from backend.app.outcomes.tracker import OutcomeTracker
from backend.app.passport.builder import PassportBuilder
from backend.app.policy.service import DelegationPolicyEngine
from backend.app.providers.github import GitHubProvider
from backend.app.providers.http_transport import HttpTransport, UrllibHttpTransport
from backend.app.providers.provider_port import GitHubProviderAdapter
from backend.app.recovery.git_recovery import GitRecoveryEngine
from backend.app.verification.runner import SubprocessVerificationRunner


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


_DEFAULT_CONFIGURED_CAPABILITIES = {
    "change_lifecycle",
    "git_inspection",
    "legacy_verification",
    "identity_and_policy",
    "credential_broker",
    "provider_outcomes",
    "recovery",
    "change_passport",
    "git_checkpoints",
    "agent_launcher",
    "environment_passports",
    "dependency_tracking",
    "assurance",
    "cli_and_terminal_ui",
}


def create_app(
    *,
    settings: Settings | None = None,
    git_inspection: GitInspectionPort | None = None,
    verification: VerificationPort | None = None,
    lifecycle_facts: LifecycleFactsPort | None = None,
    credential_store: CredentialStorePort | None = None,
    http_transport: HttpTransport | None = None,
    configured_capabilities: set[str] | None = None,
    evidence: EvidenceService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    api_token = resolved_settings.api_token or load_or_create_api_token(
        resolved_settings.database_path
    )
    database = Database(resolved_settings.database_path)
    journal = JournalWriter(database)
    repository = ChangeRepository(database, journal=journal)
    evidence_service = evidence or EvidenceService(EvidenceStore(database), journal=journal)
    resolved_lifecycle_facts = lifecycle_facts or RuntimeLifecycleFacts(
        DelegationRepository(database),
        ProviderOperationRepository(database),
        OutcomeRepository(database),
        RecoveryRepository(database),
        assurance_facts=evidence_service.assurance_facts,
    )
    service = ChangeService(
        repository=repository,
        git_inspection=git_inspection or GitRepositoryInspector(),
        verification=verification or SubprocessVerificationRunner(),
        lifecycle_facts=resolved_lifecycle_facts,
        settings=resolved_settings,
        configured_capabilities=configured_capabilities
        or set(_DEFAULT_CONFIGURED_CAPABILITIES),
    )
    runtime = _build_runtime_services(
        database,
        service,
        credential_store or WindowsCredentialStore(),
        http_transport or UrllibHttpTransport(),
        evidence_service,
        journal,
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
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
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

    app.include_router(
        build_router(service, runtime),
        dependencies=[Depends(require_bearer_token(api_token))],
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.change_service = service
    app.state.runtime_services = runtime
    app.state.api_token = api_token
    return app


def _build_runtime_services(
    database: Database,
    service: ChangeService,
    credential_store: CredentialStorePort,
    http_transport: HttpTransport,
    evidence_service: EvidenceService,
    journal: JournalWriter | None = None,
) -> RuntimeServices:
    """Wires the AC-owned identity/policy/credential/provider/outcome/recovery/
    passport adapters into request-scoped use-case services (Gate 3 composition)."""

    resolved_journal = journal or JournalWriter(database)
    actors = ActorRepository(database)
    delegations = DelegationRepository(database)
    identity = IdentityAdminService(actors, delegations, journal=resolved_journal)

    broker = CredentialBroker(credential_store, journal=resolved_journal)
    credentials = CredentialAdminService(
        broker, actors, CredentialGrantRepository(database), journal=resolved_journal
    )

    policy = DelegationPolicyEngine(delegations)

    github_provider = GitHubProvider(http_transport)
    provider_adapter = GitHubProviderAdapter(github_provider, broker)
    provider_operations = ProviderOperationService(
        provider_adapter,
        policy,
        service,
        credentials,
        ProviderOperationRepository(database),
        journal=resolved_journal,
    )

    outcome_tracker = OutcomeTracker(github_provider)
    outcomes = OutcomeService(
        outcome_tracker, broker, service, credentials, OutcomeRepository(database),
        journal=resolved_journal,
    )

    recovery_engine = GitRecoveryEngine(database)
    recovery = RecoveryService(
        recovery_engine, policy, service, RecoveryRepository(database),
        journal=resolved_journal,
    )

    passport_builder = PassportBuilder(database, delegations)
    passport = PassportService(passport_builder, service, PassportRepository(database),
                               journal=resolved_journal)

    return RuntimeServices(
        identity=identity,
        credentials=credentials,
        provider_operations=provider_operations,
        outcomes=outcomes,
        recovery=recovery,
        passport=passport,
        evidence=EvidenceAdminService(
            evidence_service, policy, service, IdempotencyStore(database)
        ),
    )


app = create_app()
