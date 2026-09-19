"""Composes AC-owned domain adapters with SD-owned persistence and policy.

This is the Gate 3 integration layer for the identity/policy/credential/
provider/outcome/recovery/passport stream: it wires the already-implemented,
independently tested concrete classes from `backend.app.identity`,
`backend.app.policy`, `backend.app.credentials`, `backend.app.providers`,
`backend.app.outcomes`, `backend.app.recovery`, and `backend.app.passport`
into request-scoped use cases the HTTP router can call, adding the
persistence and authority checks those owner-local modules intentionally do
not perform themselves (per `AGENT_COORDINATION.md`, only `[SD]` composes
the application).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    Actor,
    ActorCreateRequest,
    ChangePassport,
    ChangeView,
    CredentialGrant,
    Delegation,
    DelegationCreateRequest,
    Outcome,
    ProviderOperation,
    ProviderOperationRequest,
    RecoveryPlan,
    utc_now,
)
from backend.app.contracts.ports import (
    OutcomePort,
    PassportPort,
    PolicyPort,
    ProviderPort,
    RecoveryPort,
)
from backend.app.core.change_service import ChangeService
from backend.app.core.errors import (
    grant_binding_invalid,
    passport_not_found,
    policy_denied,
    provider_repository_unresolved,
    recovery_plan_not_found,
)
from backend.app.core.runtime_repositories import (
    CredentialGrantRepository,
    OutcomeRepository,
    PassportRepository,
    ProviderOperationRepository,
    RecoveryRepository,
)
from backend.app.core.evidence_runtime import EvidenceAdminService
from backend.app.credentials.broker import CredentialBroker
from backend.app.identity.errors import actor_not_found, delegation_not_found
from backend.app.identity.repository import ActorRepository, DelegationRepository
from backend.app.outcomes.outcome_port import GitHubOutcomeTracker
from backend.app.outcomes.tracker import OutcomeTracker
from backend.app.providers.repository_slug import resolve_github_repository_slug

Clock = Callable[[], datetime]


class IdentityAdminService:
    """Actor/delegation administration over the `[AC]`-owned repositories."""

    def __init__(
        self,
        actors: ActorRepository,
        delegations: DelegationRepository,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self.actors = actors
        self.delegations = delegations
        self._clock = clock

    def create_actor(self, request: ActorCreateRequest) -> Actor:
        now = self._clock()
        return self.actors.create(
            Actor(
                id=uuid4(),
                kind=request.kind,
                display_name=request.display_name,
                provenance=request.provenance,
                created_at=now,
                updated_at=now,
            )
        )

    def get_actor(self, actor_id: UUID) -> Actor:
        actor = self.actors.get(actor_id)
        if actor is None:
            raise actor_not_found(str(actor_id))
        return actor

    def create_delegation(
        self, request: DelegationCreateRequest, *, repository_path: str
    ) -> Delegation:
        self.get_actor(request.grantee_id)
        now = self._clock()
        delegation = Delegation(
            id=uuid4(),
            grantor_id=request.grantor_id,
            grantee_id=request.grantee_id,
            change_id=request.change_id,
            repository_path=repository_path,
            scopes=request.scopes,
            issued_at=now,
            expires_at=now + timedelta(seconds=request.ttl_seconds),
            use_limit=request.use_limit,
        )
        return self.delegations.create(delegation)

    def get_delegation(self, delegation_id: UUID) -> Delegation:
        delegation = self.delegations.get(delegation_id)
        if delegation is None:
            raise delegation_not_found(str(delegation_id))
        return delegation

    def revoke_delegation(self, delegation_id: UUID) -> Delegation:
        revoked = self.delegations.revoke(delegation_id, self._clock())
        if revoked is None:
            raise delegation_not_found(str(delegation_id))
        return revoked

    def list_delegations_for_change(self, change_id: UUID) -> list[Delegation]:
        return self.delegations.list_for_change(change_id)


class CredentialAdminService:
    """Provider secret and internal grant administration over `CredentialBroker`."""

    def __init__(
        self,
        broker: CredentialBroker,
        actors: ActorRepository,
        grants: CredentialGrantRepository,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self.broker = broker
        self.actors = actors
        self.grants = grants
        self._clock = clock

    def connect(self, provider: str, token: str) -> None:
        self.broker.store_provider_secret(provider, token)

    def disconnect(self, provider: str) -> None:
        self.broker.revoke_provider_secret(provider)

    def is_configured(self, provider: str) -> bool:
        # Mirrors `CredentialBroker._secret_key`'s `f"provider:{provider}"`
        # convention. Never exposes the stored value, only its presence.
        return self.broker.store.get(f"provider:{provider}") is not None

    def issue_grant(
        self, actor_id: UUID, change_id: UUID, scopes: list[str], ttl_seconds: int
    ) -> CredentialGrant:
        if self.actors.get(actor_id) is None:
            raise actor_not_found(str(actor_id))
        grant = self.broker.issue_grant(actor_id, change_id, scopes, ttl_seconds)
        return self.grants.create(grant)

    def revoke_grant(self, grant_id: UUID) -> CredentialGrant:
        self.broker.revoke(grant_id)
        revoked = self.grants.revoke(grant_id, self._clock())
        if revoked is None:
            raise grant_binding_invalid(str(grant_id))
        return revoked

    def get_grant(self, grant_id: UUID) -> CredentialGrant:
        grant = self.grants.get(grant_id)
        if grant is None:
            raise grant_binding_invalid(str(grant_id))
        return grant

    def require_grant(self, grant_id: UUID, *, actor_id: UUID, change_id: UUID) -> CredentialGrant:
        grant = self.get_grant(grant_id)
        if grant.actor_id != actor_id or grant.change_id != change_id:
            raise grant_binding_invalid(str(grant_id))
        return grant


def _enforce_policy(
    policy: PolicyPort,
    actor_id: UUID,
    change: ChangeView,
    operation: str,
    parameters: dict[str, object],
) -> None:
    decision = policy.evaluate(actor_id, change, operation, parameters)
    if not decision.allowed:
        raise policy_denied(decision.reason_code, decision.explanation)


class ProviderOperationService:
    """GitHub provider operations: policy-gated, brokered, and persisted."""

    def __init__(
        self,
        provider: ProviderPort,
        policy: PolicyPort,
        change_service: ChangeService,
        credentials: CredentialAdminService,
        operations: ProviderOperationRepository,
    ) -> None:
        self.provider = provider
        self.policy = policy
        self.change_service = change_service
        self.credentials = credentials
        self.operations = operations

    def create_pull_request(
        self,
        change_id: UUID,
        *,
        actor_id: UUID,
        grant_id: UUID,
        base_branch: str,
        head_branch: str,
        title: str,
        idempotency_key: str,
    ) -> ProviderOperation:
        # Check for a prior result before touching the provider at all.
        # `ProviderOperationRepository.create`'s UNIQUE(change_id,
        # idempotency_key) constraint only dedupes what gets *stored* — by
        # itself it cannot stop a second real GitHub call for a replayed
        # key, since the constraint is only checked after `provider.execute`
        # has already run. This early return is what actually makes the
        # idempotency-key contract hold for a request that previously
        # failed (a previously *succeeded* request happens to also be
        # short-circuited by `GitHubProvider`'s own internal cache, but a
        # failure has no such cache).
        existing = self.operations.get_by_idempotency_key(change_id, idempotency_key)
        if existing is not None:
            return existing

        change = self.change_service.get(change_id)
        grant = self.credentials.require_grant(
            grant_id, actor_id=actor_id, change_id=change_id
        )
        repository = resolve_github_repository_slug(change.repository_path)
        if repository is None:
            raise provider_repository_unresolved(change.repository_path)

        parameters = {
            "repository": repository,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "title": title,
        }
        _enforce_policy(self.policy, actor_id, change, "github.pr.create", parameters)

        request = ProviderOperationRequest(
            provider="github",
            operation="github.pr.create",
            change_id=change_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            parameters=parameters,
        )
        result = self.provider.execute(request, grant)
        stored, _created = self.operations.create(result)
        return stored


class OutcomeService:
    """GitHub PR/CI outcome refresh, persisted per Change."""

    def __init__(
        self,
        tracker: OutcomeTracker,
        broker: CredentialBroker,
        change_service: ChangeService,
        credentials: CredentialAdminService,
        outcomes: OutcomeRepository,
    ) -> None:
        self.tracker = tracker
        self.broker = broker
        self.change_service = change_service
        self.credentials = credentials
        self.outcomes = outcomes

    def refresh(
        self,
        change_id: UUID,
        *,
        grant_id: UUID,
        required_check_names: list[str],
    ) -> list[Outcome]:
        change = self.change_service.get(change_id)
        grant = self.credentials.get_grant(grant_id)
        if grant.change_id != change_id:
            raise grant_binding_invalid(str(grant_id))
        port: OutcomePort = GitHubOutcomeTracker(
            self.tracker,
            self.broker,
            read_grant_id=grant_id,
            required_check_names=required_check_names,
        )
        results = port.refresh(change)
        for outcome in results:
            self.outcomes.create(outcome)
        return results

    def list_for_change(self, change_id: UUID) -> list[Outcome]:
        return self.outcomes.list_for_change(change_id)


class RecoveryService:
    """Constrained Git recovery: preview, policy-gated execute, persisted."""

    def __init__(
        self,
        recovery: RecoveryPort,
        policy: PolicyPort,
        change_service: ChangeService,
        plans: RecoveryRepository,
    ) -> None:
        self.recovery = recovery
        self.policy = policy
        self.change_service = change_service
        self.plans = plans

    def preview(self, change_id: UUID) -> RecoveryPlan:
        change = self.change_service.get(change_id)
        plan = self.recovery.plan(change)
        return self.plans.create_plan(plan)

    def execute(
        self, change_id: UUID, plan_id: UUID, *, actor_id: UUID, approval_token: str
    ) -> RecoveryPlan:
        change = self.change_service.get(change_id)
        stored_plan = self.plans.get(plan_id)
        if stored_plan is None or stored_plan.change_id != change_id:
            raise recovery_plan_not_found(str(plan_id))
        _enforce_policy(self.policy, actor_id, change, "recovery.execute", {})
        result = self.recovery.execute(change, stored_plan, approval_token)
        return self.plans.update_plan(result)

    def latest(self, change_id: UUID) -> RecoveryPlan:
        plan = self.plans.latest_for_change(change_id)
        if plan is None:
            raise recovery_plan_not_found(str(change_id))
        return plan


class PassportService:
    """Change Passport build/retrieve, persisted per Change."""

    def __init__(
        self,
        passport: PassportPort,
        change_service: ChangeService,
        passports: PassportRepository,
    ) -> None:
        self.passport = passport
        self.change_service = change_service
        self.passports = passports

    def build(self, change_id: UUID) -> ChangePassport:
        change = self.change_service.get(change_id)
        built = self.passport.build(change)
        return self.passports.create(built)

    def latest(self, change_id: UUID) -> ChangePassport:
        stored = self.passports.latest_for_change(change_id)
        if stored is None:
            raise passport_not_found(str(change_id))
        return stored


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    """Bundles the AC-domain use-case services for router composition."""

    identity: IdentityAdminService
    credentials: CredentialAdminService
    provider_operations: ProviderOperationService
    outcomes: OutcomeService
    recovery: RecoveryService
    passport: PassportService
    evidence: EvidenceAdminService
