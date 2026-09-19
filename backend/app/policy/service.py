"""Concrete `PolicyPort`: delegation authority, then operation/path/risk rules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from backend.app.contracts.models import ChangeView, PolicyDecision, RiskLevel
from backend.app.identity.models import DelegationDenialReason
from backend.app.identity.repository import DelegationRepository
from backend.app.identity.service import evaluate_delegation
from backend.app.policy.engine import _path_is_forbidden

DEFAULT_DENIED_OPERATIONS = frozenset({"github.force_push", "github.secret.read"})

_RISK_ORDER = [
    RiskLevel.UNKNOWN,
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
]

_DENIAL_EXPLANATIONS: dict[DelegationDenialReason, str] = {
    DelegationDenialReason.NOT_FOUND: "No delegation grants this actor the requested scope for this Change.",
    DelegationDenialReason.EXPIRED: "The matching delegation has expired or is not yet valid.",
    DelegationDenialReason.REVOKED: "The matching delegation has been revoked.",
    DelegationDenialReason.WRONG_CHANGE: "The matching delegation is bound to a different Change.",
    DelegationDenialReason.WRONG_REPOSITORY: "The matching delegation is bound to a different repository.",
    DelegationDenialReason.SCOPE_NOT_GRANTED: "No delegation grants the requested scope.",
    DelegationDenialReason.EXHAUSTED: "The matching delegation has no uses remaining.",
}


def _infer_risk(parameters: dict[str, object]) -> RiskLevel:
    raw = parameters.get("risk_level")
    if isinstance(raw, RiskLevel):
        return raw
    if isinstance(raw, str):
        try:
            return RiskLevel(raw)
        except ValueError:
            pass
    return RiskLevel.LOW


def _risk_exceeds(risk: RiskLevel, max_risk: RiskLevel) -> bool:
    return _RISK_ORDER.index(risk) > _RISK_ORDER.index(max_risk)


class DelegationPolicyEngine:
    """Implements `backend.app.contracts.ports.PolicyPort`."""

    def __init__(
        self,
        delegations: DelegationRepository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.delegations = delegations
        self._clock = clock

    def evaluate(
        self,
        actor_id: UUID,
        change: ChangeView,
        operation: str,
        parameters: dict[str, object],
    ) -> PolicyDecision:
        now = self._clock()
        candidates = self.delegations.list_for_grantee(actor_id, change.id)
        best_reason = DelegationDenialReason.NOT_FOUND
        for delegation in candidates:
            decision = evaluate_delegation(
                delegation,
                change_id=change.id,
                repository_path=change.repository_path,
                scope=operation,
                now=now,
            )
            if decision.allowed:
                return self._evaluate_operation(change, operation, parameters)
            if decision.denial_reason is not None:
                best_reason = decision.denial_reason

        return PolicyDecision(
            allowed=False,
            reason_code=f"AUTHORITY_{best_reason.value}",
            explanation=_DENIAL_EXPLANATIONS[best_reason],
            risk_level=RiskLevel.UNKNOWN,
        )

    def _evaluate_operation(
        self, change: ChangeView, operation: str, parameters: dict[str, object]
    ) -> PolicyDecision:
        risk = _infer_risk(parameters)

        if operation in DEFAULT_DENIED_OPERATIONS:
            return PolicyDecision(
                allowed=False,
                reason_code="OPERATION_NOT_PERMITTED",
                explanation=f"Operation '{operation}' is denied by default policy.",
                risk_level=RiskLevel.HIGH,
            )

        target_path = parameters.get("target_path")
        if isinstance(target_path, str) and _path_is_forbidden(
            target_path, change.contract.forbidden_paths
        ):
            return PolicyDecision(
                allowed=False,
                reason_code="PATH_FORBIDDEN",
                explanation=f"Path '{target_path}' is forbidden by the Change Contract.",
                risk_level=RiskLevel.HIGH,
            )

        ceiling = change.contract.authority_ceiling
        if ceiling and operation not in ceiling:
            return PolicyDecision(
                allowed=False,
                reason_code="OPERATION_NOT_PERMITTED",
                explanation=(
                    f"Operation '{operation}' exceeds the Change Contract's "
                    "authority ceiling."
                ),
                risk_level=risk,
            )

        if _risk_exceeds(risk, change.contract.max_risk):
            return PolicyDecision(
                allowed=False,
                reason_code="RISK_TOO_HIGH",
                explanation=(
                    f"Operation risk '{risk.value}' exceeds the Change Contract's "
                    f"maximum risk '{change.contract.max_risk.value}'."
                ),
                risk_level=risk,
                required_approval=True,
            )

        return PolicyDecision(
            allowed=True,
            reason_code="ALLOWED",
            explanation="Authority, path, operation, and risk checks passed.",
            risk_level=risk,
        )
