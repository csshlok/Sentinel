"""Real `LifecycleFactsPort`: composes transition facts from wired evidence.

`repository_valid`/`contract_present` are structurally guaranteed once a
`ChangeView` exists (repository canonicalization and a `ChangeContract`
default both happen at Change-creation time), so they are always `True`
here rather than a fabricated default.

`authority_valid`, `pull_request_recorded`, `ci_passed_for_current_head`,
and the `recovery_*` facts are computed from the identity, provider
operation, outcome, and recovery evidence `[SD]` wired in
`backend.app.core.runtime_service`.

Facts that depend on `[KB]`'s not-yet-implemented environment/dependency/
assurance stream (`required_assurance_passed`, `assurance_fresh`,
`deviations_resolved`, `required_evidence_complete`, `artifact_recorded`,
`deployment_recorded`, `observation_criteria_met`) are left at their
`LifecycleFacts` default of `False`. This class never fabricates them —
until that stream lands, `LOCALLY_VERIFIED`, `REVIEW_READY`,
`ARTIFACT_BUILT`, `DEPLOYED`, `OBSERVING`, and `STABLE` stay honestly
unreachable through the real API, per this product's "no safety theater"
invariant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.app.contracts.models import ChangeView, LifecycleFacts, OutcomeKind, OutcomeStatus, RecoveryStatus
from backend.app.core.runtime_repositories import (
    OutcomeRepository,
    ProviderOperationRepository,
    RecoveryRepository,
)
from backend.app.identity.repository import DelegationRepository

_UNRESOLVED_RECOVERY_STATUSES = frozenset(
    {
        RecoveryStatus.PLANNED,
        RecoveryStatus.APPROVED,
        RecoveryStatus.EXECUTING,
        RecoveryStatus.CONFLICTED,
    }
)


class RuntimeLifecycleFacts:
    """Implements `backend.app.contracts.ports.LifecycleFactsPort`."""

    def __init__(
        self,
        delegations: DelegationRepository,
        provider_operations: ProviderOperationRepository,
        outcomes: OutcomeRepository,
        recovery: RecoveryRepository,
    ) -> None:
        self.delegations = delegations
        self.provider_operations = provider_operations
        self.outcomes = outcomes
        self.recovery = recovery

    def get_facts(self, change: ChangeView, target_state: str) -> LifecycleFacts:
        del target_state  # every fact is computed; `validate_transition` picks what it needs
        now = datetime.now(UTC)

        authority_valid = any(
            delegation.revoked_at is None and delegation.expires_at > now
            for delegation in self.delegations.list_for_change(change.id)
        )
        pull_request_recorded = self.provider_operations.has_succeeded_operation(
            change.id, "github.pr.create"
        )
        ci_passed_for_current_head = self._ci_passed(change)

        latest_plan = self.recovery.latest_for_change(change.id)
        recovery_plan_approved = (
            latest_plan is not None and latest_plan.approved_at is not None
        )
        recovery_verified = (
            latest_plan is not None and latest_plan.status is RecoveryStatus.RECOVERED
        )
        recovery_conflict = (
            latest_plan is not None and latest_plan.status is RecoveryStatus.CONFLICTED
        )
        recovery_failed = (
            latest_plan is not None
            and latest_plan.status is RecoveryStatus.RECOVERY_FAILED
        )
        unresolved_recovery_actions = (
            latest_plan is not None
            and latest_plan.status in _UNRESOLVED_RECOVERY_STATUSES
        )

        return LifecycleFacts(
            repository_valid=True,
            contract_present=True,
            authority_valid=authority_valid,
            pull_request_recorded=pull_request_recorded,
            ci_passed_for_current_head=ci_passed_for_current_head,
            recovery_plan_approved=recovery_plan_approved,
            recovery_verified=recovery_verified,
            recovery_conflict=recovery_conflict,
            recovery_failed=recovery_failed,
            unresolved_recovery_actions=unresolved_recovery_actions,
        )

    def _ci_passed(self, change: ChangeView) -> bool:
        if change.git_summary is None:
            return False
        head_sha = change.git_summary.head_sha
        return any(
            outcome.kind is OutcomeKind.CI
            and outcome.status is OutcomeStatus.PASSED
            and outcome.head_sha == head_sha
            for outcome in self.outcomes.list_for_change(change.id)
        )
