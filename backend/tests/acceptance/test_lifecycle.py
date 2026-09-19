from __future__ import annotations

import pytest

from backend.app.contracts.models import ChangeLifecycleState, LifecycleFacts
from backend.app.core.errors import AppError
from backend.app.core.lifecycle import allowed_targets, validate_transition


def test_draft_can_activate_only_with_repository_contract_and_authority() -> None:
    with pytest.raises(AppError) as failure:
        validate_transition(
            ChangeLifecycleState.DRAFT,
            ChangeLifecycleState.ACTIVE,
            LifecycleFacts(repository_valid=True, contract_present=True),
        )

    assert failure.value.code == "TRANSITION_GUARD_FAILED"
    assert failure.value.details["missing_requirements"] == ["authority_valid"]

    validate_transition(
        ChangeLifecycleState.DRAFT,
        ChangeLifecycleState.ACTIVE,
        LifecycleFacts(
            repository_valid=True,
            contract_present=True,
            authority_valid=True,
        ),
    )


@pytest.mark.parametrize(
    ("current", "target", "facts"),
    [
        (
            ChangeLifecycleState.ACTIVE,
            ChangeLifecycleState.LOCALLY_VERIFIED,
            LifecycleFacts(
                required_assurance_passed=True,
                assurance_fresh=True,
            ),
        ),
        (
            ChangeLifecycleState.LOCALLY_VERIFIED,
            ChangeLifecycleState.REVIEW_READY,
            LifecycleFacts(
                deviations_resolved=True,
                required_evidence_complete=True,
            ),
        ),
        (
            ChangeLifecycleState.REVIEW_READY,
            ChangeLifecycleState.PR_OPEN,
            LifecycleFacts(pull_request_recorded=True),
        ),
        (
            ChangeLifecycleState.PR_OPEN,
            ChangeLifecycleState.CI_VERIFIED,
            LifecycleFacts(ci_passed_for_current_head=True),
        ),
        (
            ChangeLifecycleState.RECOVERY_PENDING,
            ChangeLifecycleState.RECOVERING,
            LifecycleFacts(recovery_plan_approved=True),
        ),
        (
            ChangeLifecycleState.RECOVERING,
            ChangeLifecycleState.RECOVERED_VERIFIED,
            LifecycleFacts(recovery_verified=True),
        ),
    ],
)
def test_guarded_happy_path_transitions(
    current: ChangeLifecycleState,
    target: ChangeLifecycleState,
    facts: LifecycleFacts,
) -> None:
    validate_transition(current, target, facts)


def test_invalid_jump_and_unresolved_recovery_are_rejected() -> None:
    with pytest.raises(AppError) as invalid:
        validate_transition(
            ChangeLifecycleState.DRAFT,
            ChangeLifecycleState.PR_OPEN,
            LifecycleFacts(pull_request_recorded=True),
        )
    assert invalid.value.code == "INVALID_CHANGE_TRANSITION"

    with pytest.raises(AppError) as unresolved:
        validate_transition(
            ChangeLifecycleState.CI_VERIFIED,
            ChangeLifecycleState.STABLE,
            LifecycleFacts(
                observation_criteria_met=True,
                unresolved_recovery_actions=True,
            ),
        )
    assert unresolved.value.code == "TRANSITION_GUARD_FAILED"
    assert "no_unresolved_recovery_actions" in unresolved.value.details[
        "missing_requirements"
    ]


def test_cancelled_is_terminal_and_same_state_is_idempotent() -> None:
    assert allowed_targets(ChangeLifecycleState.CANCELLED) == frozenset()
    validate_transition(
        ChangeLifecycleState.ACTIVE,
        ChangeLifecycleState.ACTIVE,
        LifecycleFacts(),
    )
    with pytest.raises(AppError):
        validate_transition(
            ChangeLifecycleState.CANCELLED,
            ChangeLifecycleState.ACTIVE,
            LifecycleFacts(
                repository_valid=True,
                contract_present=True,
                authority_valid=True,
            ),
        )
