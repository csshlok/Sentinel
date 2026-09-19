"""Pure Change lifecycle transition and guard rules."""

from __future__ import annotations

from backend.app.contracts.models import ChangeLifecycleState, LifecycleFacts
from backend.app.core.errors import invalid_transition, transition_guard_failed


_S = ChangeLifecycleState

ALLOWED_TRANSITIONS: dict[ChangeLifecycleState, frozenset[ChangeLifecycleState]] = {
    _S.DRAFT: frozenset({_S.ACTIVE, _S.CANCELLED}),
    _S.ACTIVE: frozenset(
        {
            _S.PAUSED,
            _S.LOCALLY_VERIFIED,
            _S.BLOCKED,
            _S.FAILED,
            _S.CANCELLED,
            _S.RECOVERY_PENDING,
        }
    ),
    _S.PAUSED: frozenset({_S.ACTIVE, _S.BLOCKED, _S.FAILED, _S.CANCELLED}),
    _S.LOCALLY_VERIFIED: frozenset(
        {
            _S.ACTIVE,
            _S.REVIEW_READY,
            _S.BLOCKED,
            _S.FAILED,
            _S.RECOVERY_PENDING,
        }
    ),
    _S.REVIEW_READY: frozenset(
        {
            _S.ACTIVE,
            _S.PR_OPEN,
            _S.BLOCKED,
            _S.FAILED,
            _S.RECOVERY_PENDING,
        }
    ),
    _S.PR_OPEN: frozenset(
        {
            _S.ACTIVE,
            _S.CI_VERIFIED,
            _S.BLOCKED,
            _S.FAILED,
            _S.RECOVERY_PENDING,
        }
    ),
    _S.CI_VERIFIED: frozenset(
        {
            _S.ACTIVE,
            _S.ARTIFACT_BUILT,
            _S.STABLE,
            _S.BLOCKED,
            _S.FAILED,
            _S.RECOVERY_PENDING,
        }
    ),
    _S.ARTIFACT_BUILT: frozenset(
        {_S.DEPLOYED, _S.STABLE, _S.BLOCKED, _S.FAILED, _S.RECOVERY_PENDING}
    ),
    _S.DEPLOYED: frozenset(
        {_S.OBSERVING, _S.BLOCKED, _S.FAILED, _S.RECOVERY_PENDING}
    ),
    _S.OBSERVING: frozenset(
        {_S.STABLE, _S.BLOCKED, _S.FAILED, _S.RECOVERY_PENDING}
    ),
    _S.STABLE: frozenset({_S.ACTIVE, _S.RECOVERY_PENDING}),
    _S.BLOCKED: frozenset(
        {_S.ACTIVE, _S.FAILED, _S.CANCELLED, _S.RECOVERY_PENDING}
    ),
    _S.FAILED: frozenset({_S.ACTIVE, _S.CANCELLED, _S.RECOVERY_PENDING}),
    _S.CANCELLED: frozenset(),
    _S.RECOVERY_PENDING: frozenset({_S.RECOVERING, _S.CANCELLED}),
    _S.RECOVERING: frozenset(
        {_S.RECOVERED_VERIFIED, _S.RECOVERY_CONFLICT, _S.RECOVERY_FAILED}
    ),
    _S.RECOVERY_CONFLICT: frozenset(
        {_S.RECOVERING, _S.RECOVERY_FAILED, _S.CANCELLED}
    ),
    _S.RECOVERY_FAILED: frozenset({_S.RECOVERY_PENDING, _S.CANCELLED}),
    _S.RECOVERED_VERIFIED: frozenset({_S.ACTIVE}),
}


GUARDS: dict[ChangeLifecycleState, tuple[str, ...]] = {
    _S.ACTIVE: ("repository_valid", "contract_present", "authority_valid"),
    _S.LOCALLY_VERIFIED: ("required_assurance_passed", "assurance_fresh"),
    _S.REVIEW_READY: ("deviations_resolved", "required_evidence_complete"),
    _S.PR_OPEN: ("pull_request_recorded",),
    _S.CI_VERIFIED: ("ci_passed_for_current_head",),
    _S.ARTIFACT_BUILT: ("artifact_recorded",),
    _S.DEPLOYED: ("deployment_recorded",),
    _S.OBSERVING: ("deployment_recorded",),
    _S.STABLE: ("observation_criteria_met",),
    _S.RECOVERING: ("recovery_plan_approved",),
    _S.RECOVERED_VERIFIED: ("recovery_verified",),
    _S.RECOVERY_CONFLICT: ("recovery_conflict",),
    _S.RECOVERY_FAILED: ("recovery_failed",),
}


def allowed_targets(current: ChangeLifecycleState) -> frozenset[ChangeLifecycleState]:
    return ALLOWED_TRANSITIONS[current]


def validate_transition(
    current: ChangeLifecycleState,
    target: ChangeLifecycleState,
    facts: LifecycleFacts,
) -> None:
    if target is current:
        return
    if target not in ALLOWED_TRANSITIONS[current]:
        raise invalid_transition(current.value, target.value)

    missing = [name for name in GUARDS.get(target, ()) if not getattr(facts, name)]
    if target is _S.STABLE and facts.unresolved_recovery_actions:
        missing.append("no_unresolved_recovery_actions")
    if missing:
        raise transition_guard_failed(target.value, missing)
