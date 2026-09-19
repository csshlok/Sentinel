"""Identity domain models: actors and scoped, expiring delegations."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

ScopeName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
DisplayName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class IdentityModel(BaseModel):
    """Strict base class matching the project's frozen-contract convention."""

    model_config = ConfigDict(extra="forbid")


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SERVICE = "SERVICE"


class Actor(IdentityModel):
    id: UUID
    kind: ActorKind
    display_name: DisplayName
    created_at: AwareDatetime


class Delegation(IdentityModel):
    id: UUID
    grantor_actor_id: UUID
    grantee_actor_id: UUID
    change_id: UUID
    repository_path: str
    scopes: list[ScopeName] = Field(min_length=1, max_length=32)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    use_count: int = Field(default=0, ge=0)


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
