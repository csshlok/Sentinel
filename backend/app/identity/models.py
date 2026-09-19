"""Identity-domain helper types.

`Actor` and `Delegation` are now frozen shared contracts
(`backend.app.contracts.models`); this module only adds the internal,
non-shared vocabulary needed to explain an authorization decision before
it is translated into the frozen `PolicyDecision` at the `PolicyPort`
boundary.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Re-exported for convenience so callers can import identity types from
# one place; these are the frozen contracts, not local duplicates.
from backend.app.contracts.models import Actor, ActorKind, Delegation

__all__ = [
    "Actor",
    "ActorKind",
    "Delegation",
    "DelegationDenialReason",
    "AuthorizationDecision",
]


class IdentityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DelegationDenialReason(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    WRONG_CHANGE = "WRONG_CHANGE"
    WRONG_REPOSITORY = "WRONG_REPOSITORY"
    SCOPE_NOT_GRANTED = "SCOPE_NOT_GRANTED"
    EXHAUSTED = "EXHAUSTED"


class AuthorizationDecision(IdentityModel):
    allowed: bool
    delegation_id: UUID | None = None
    denial_reason: DelegationDenialReason | None = None
