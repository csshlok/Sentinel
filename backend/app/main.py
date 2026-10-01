"""FastAPI composition root for the local-only Change Assurance API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.assurance.engine import AssuranceEngine
from backend.app.assurance.service import BASELINE, DEFAULT_PATCH_LIMIT, EvidenceService
from backend.app.assurance.store import EvidenceStore, IdempotencyStore
from backend.app.contracts.models import (
    BackendIdentity, ErrorDetail, ErrorEnvelope, HealthResponse, utc_now,
)
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
from backend.app.core.evidence_store import (
    default_store_directory,
    ensure_no_unmigrated_legacy_store,
    ensure_store_outside_repository,
    prepare_store_directory,
    warn_if_legacy_store_present,
)
from backend.app.core.journal import JournalWriter
from backend.app.core.lifecycle_facts_service import RuntimeLifecycleFacts
from backend.app.core.replay_service import ReplayService
from backend.app.core.router import build_router
from backend.app.core.tool_registry_service import ToolRegistryService
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
    CheckRunService,
    RuntimeServices,
)
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.windows_store import WindowsCredentialStore
from backend.app.execution.check_box import CheckBoxes
from backend.app.execution.check_repository import CheckRunRepository
from backend.app.execution.launcher import AgentLauncher
from backend.app.execution.signature import check_signature
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.identity.repository import ActorRepository, DelegationRepository
from backend.app.outcomes.tracker import OutcomeTracker
from backend.app.passport.builder import PassportBuilder
from backend.app.passport.signing import SigningService
from backend.app.policy.service import DelegationPolicyEngine
from backend.app.providers.github import GitHubProvider
from backend.app.providers.http_transport import HttpTransport, UrllibHttpTransport
from backend.app.providers.provider_port import GitHubProviderAdapter
from backend.app.recovery.git_recovery import GitRecoveryEngine
from backend.app.verification.runner import SubprocessVerificationRunner
from backend.app.workspace.guard import WorkspaceGuardedGitState
from backend.app.workspace.manager import WorkspaceManager
from backend.app.workspace.service import WorkspaceService


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
    "process_supervisor",
    "environment_passports",
    "dependency_tracking",
    "assurance",
    "cli_and_terminal_ui",
    "event_journal",
    "replay",
    "tool_registry",
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
    # Refuse an agent-reachable store before anything (token, database) is written.
    # The configured (unresolved) path is checked too: a junction inside a
    # repository that points at an outside directory still leaves the store
    # reachable through the repository.
    if resolved_settings.configured_database_path is not None:
        ensure_store_outside_repository(resolved_settings.configured_database_path)
    ensure_store_outside_repository(resolved_settings.database_path)
    # A legacy store waiting for `migrate-store` must not be shadowed by a fresh
    # default store (the migration never overwrites an existing target).
    ensure_no_unmigrated_legacy_store(resolved_settings.database_path)
    warn_if_legacy_store_present(resolved_settings.database_path, logger=LOGGER)
    default_directory = default_store_directory()
    if resolved_settings.database_path.parent.resolve() == default_directory.resolve():
        # Only the default directory is re-ACL'd, before the token and database
        # exist so they inherit the restricted DACL. The unresolved default path
        # is passed so a junction planted there is refused, not followed.
        # Operator-chosen directories keep their permissions (the token file
        # is still restricted).
        prepare_store_directory(default_directory, logger=LOGGER)
    api_token = resolved_settings.api_token or load_or_create_api_token(
        resolved_settings.database_path
    )
    database = Database(resolved_settings.database_path)
    journal = JournalWriter(database)
    repository = ChangeRepository(database, journal=journal)
    tool_registry = ToolRegistryService(
        database, journal=journal, signature_checker=check_signature
    )
    resolved_credential_store = credential_store or WindowsCredentialStore()
    # ONE broker: it backs the credential/provider services and is the only
    # code that stages (and deletes) an agent's model credential (D-06).
    broker = CredentialBroker(
        resolved_credential_store, journal=journal,
        grant_lookup=CredentialGrantRepository(database).get,
    )
    evidence_store = EvidenceStore(database)

    def baseline_head(change_id):
        checkpoint = evidence_store.named_checkpoint(change_id, BASELINE)
        return checkpoint.head_sha if checkpoint is not None else None

    workspace_manager = WorkspaceManager(
        database, baseline_head=baseline_head,
        credential_purger=broker.purge_staged_credentials, journal=journal,
    )
    # Phase 5: per-run confined check boxes. Verification, assurance checks and
    # diff-coverage collection all run in them (05-03).
    check_boxes = CheckBoxes(database, journal=journal,
                             evidence_guard=workspace_manager.unapplied_work)
    # claude resolves to the AppContainer profile: it launches only inside
    # this manager's workspace, with the broker's staged credential.
    agent_launcher = AgentLauncher(
        tool_registry=tool_registry, workspaces=workspace_manager, credentials=broker,
    )
    if evidence is None:
        guarded_git_state = WorkspaceGuardedGitState(workspace_manager)
        evidence_service = EvidenceService(
            evidence_store, journal=journal, launcher=agent_launcher,
            git_state=guarded_git_state,
            assurance=AssuranceEngine(checks=check_boxes, git_state=guarded_git_state,
                                      patch_limit_bytes=DEFAULT_PATCH_LIMIT),
        )
    else:
        evidence_service = evidence
    change_delegations = DelegationRepository(database)
    resolved_lifecycle_facts = lifecycle_facts or RuntimeLifecycleFacts(
        change_delegations,
        ProviderOperationRepository(database),
        OutcomeRepository(database),
        RecoveryRepository(database),
        assurance_facts=evidence_service.assurance_facts,
    )
    service = ChangeService(
        repository=repository,
        git_inspection=git_inspection or GitRepositoryInspector(),
        verification=verification or SubprocessVerificationRunner(check_boxes),
        lifecycle_facts=resolved_lifecycle_facts,
        settings=resolved_settings,
        policy=DelegationPolicyEngine(change_delegations),
        configured_capabilities=configured_capabilities
        or set(_DEFAULT_CONFIGURED_CAPABILITIES),
        workspace_guard=workspace_manager.has_live_workspace,
        unapplied_work_guard=workspace_manager.unapplied_work,
    )
    runtime = _build_runtime_services(
        database,
        service,
        resolved_credential_store,
        http_transport or UrllibHttpTransport(),
        evidence_service,
        journal,
        tool_registry,
        broker=broker,
        workspace_manager=workspace_manager,
    )

    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncIterator[None]:
        database.initialize()
        # D-05 startup trigger: reconcile crashed/interrupted workspaces recorded in
        # THIS database. A failing sweep is logged and never blocks startup.
        app_.state.workspace_sweep_report = None
        try:
            report = workspace_manager.sweep()
        except Exception:
            LOGGER.exception("Startup workspace sweep failed")
        else:
            app_.state.workspace_sweep_report = report
            LOGGER.info(
                "Startup workspace sweep: %d cleaned, %d preserved, %d failed",
                len(report.cleaned), len(report.preserved), len(report.failed),
            )
        # Same trigger for confined check boxes: finish every row not CLEANED.
        app_.state.check_sweep_report = None
        try:
            check_report = check_boxes.sweep()
        except Exception:
            LOGGER.exception("Startup check box sweep failed")
        else:
            app_.state.check_sweep_report = check_report
            LOGGER.info(
                "Startup check box sweep: %d cleaned, %d failed",
                len(check_report.cleaned), len(check_report.failed),
            )
        # WR-08: then the runtime cache (orphaned partial copies, long-unused entries).
        app_.state.runtime_cache_sweep_report = None
        try:
            cache_report = check_boxes.sweep_runtime_cache()
        except Exception:
            LOGGER.exception("Startup check runtime cache sweep failed")
        else:
            app_.state.runtime_cache_sweep_report = cache_report
            LOGGER.info(
                "Startup check runtime cache sweep: %d partial, %d evicted, %d failed",
                len(cache_report.removed_partials), len(cache_report.evicted),
                len(cache_report.failed),
            )
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

    @app.get(
        "/api/v1/system/backend-identity", response_model=BackendIdentity, tags=["system"]
    )
    def backend_identity() -> BackendIdentity:
        return BackendIdentity(
            service_name="change-assurance-runtime-backend",
            api_version=API_VERSION,
            instance_id=app.state.instance_id,
            started_at=app.state.started_at,
        )

    app.include_router(
        build_router(service, runtime),
        dependencies=[Depends(require_bearer_token(api_token))],
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.change_service = service
    app.state.runtime_services = runtime
    app.state.workspace_manager = workspace_manager
    app.state.check_boxes = check_boxes
    app.state.agent_launcher = agent_launcher
    app.state.credential_broker = broker
    app.state.api_token = api_token
    app.state.instance_id = uuid4()
    app.state.started_at = utc_now()
    return app


def _build_runtime_services(
    database: Database,
    service: ChangeService,
    credential_store: CredentialStorePort,
    http_transport: HttpTransport,
    evidence_service: EvidenceService,
    journal: JournalWriter | None = None,
    tool_registry: ToolRegistryService | None = None,
    *,
    broker: CredentialBroker | None = None,
    workspace_manager: WorkspaceManager | None = None,
) -> RuntimeServices:
    """Wires the AC-owned identity/policy/credential/provider/outcome/recovery/
    passport adapters into request-scoped use-case services (Gate 3 composition)."""

    resolved_journal = journal or JournalWriter(database)
    actors = ActorRepository(database)
    delegations = DelegationRepository(database)
    identity = IdentityAdminService(actors, delegations, journal=resolved_journal)

    policy = DelegationPolicyEngine(delegations)

    credential_grants = CredentialGrantRepository(database)
    broker = broker or CredentialBroker(
        credential_store, journal=resolved_journal, grant_lookup=credential_grants.get
    )
    credentials = CredentialAdminService(
        broker, actors, credential_grants,
        policy=policy, change_service=service, journal=resolved_journal,
    )

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
        policy=policy, journal=resolved_journal,
    )

    recovery_engine = GitRecoveryEngine(
        database, process_tree_terminator=evidence_service.terminate_process_trees
    )
    recovery = RecoveryService(
        recovery_engine, policy, service, RecoveryRepository(database),
        journal=resolved_journal,
    )

    replay_service = ReplayService(database)
    resolved_tools = tool_registry or ToolRegistryService(database, journal=resolved_journal)

    passport_builder = PassportBuilder(
        database, delegations, tools=resolved_tools, replay=replay_service
    )
    signing = SigningService(credential_store)
    passport = PassportService(passport_builder, service, PassportRepository(database),
                               journal=resolved_journal, signing=signing)

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
        replay=replay_service,
        tools=resolved_tools,
        workspace=(WorkspaceService(workspace_manager, policy, service, journal=resolved_journal)
                   if workspace_manager is not None else None),
        checks=CheckRunService(CheckRunRepository(database), service),
    )


app = create_app()
