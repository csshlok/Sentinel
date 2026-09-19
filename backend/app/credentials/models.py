"""Credential grant model: scoped, expiring, revocable, never a secret."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

ScopeName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
ProviderName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]


class CredentialsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialGrant(CredentialsModel):
    id: UUID
    actor_id: UUID
    change_id: UUID
    provider: ProviderName
    scopes: list[ScopeName] = Field(min_length=1, max_length=32)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
