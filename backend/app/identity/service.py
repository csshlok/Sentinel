"""Default-deny authorization decisions over delegation state."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from backend.app.identity.models import (
    AuthorizationDecision,
    Delegation,
    DelegationDenialReason,
)
from backend.app.identity.repository import DelegationRepository


def evaluate_delegation(
    delegation: Delegation | None,
    *,
    change_id: UUID,
    repository_path: str,
    scope: str,
    now: datetime,
) -> AuthorizationDecision:
    """Default-deny evaluation of one delegation against a requested action.

    Every branch denies unless the delegation is present, unrevoked,
    currently valid, bound to the exact Change/repository, grants the
    exact scope, and has remaining uses.
    """

    if delegation is None:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.NOT_FOUND
        )
    if delegation.revoked_at is not None:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.REVOKED
        )
    if now < delegation.issued_at or now >= delegation.expires_at:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.EXPIRED
        )
    if delegation.change_id != change_id:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.WRONG_CHANGE
        )
    if delegation.repository_path != repository_path:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.WRONG_REPOSITORY
        )
    if scope not in delegation.scopes:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.SCOPE_NOT_GRANTED
        )
    if delegation.use_limit is not None and delegation.uses >= delegation.use_limit:
        return AuthorizationDecision(
            allowed=False, denial_reason=DelegationDenialReason.EXHAUSTED
        )
    return AuthorizationDecision(allowed=True, delegation_id=delegation.id)


class IdentityService:
    """Composes delegation lookup with the pure authorization rule."""

    def __init__(self, delegations: DelegationRepository) -> None:
        self.delegations = delegations

    def authorize(
        self,
        delegation_id: UUID,
        *,
        change_id: UUID,
        repository_path: str,
        scope: str,
        now: datetime,
    ) -> AuthorizationDecision:
        delegation = self.delegations.get(delegation_id)
        return evaluate_delegation(
            delegation,
            change_id=change_id,
            repository_path=repository_path,
            scope=scope,
            now=now,
        )
