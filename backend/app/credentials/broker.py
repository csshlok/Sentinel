"""Issues short-lived internal grants and gates access to durable secrets.

The durable provider secret lives only in a `CredentialStorePort`
implementation. `resolve_secret` is the single boundary where that
secret leaves the store, and only for a grant that is present,
unrevoked, unexpired, and scoped to the request. No other method on
this class or on `CredentialGrant` ever exposes the raw secret.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.app.credentials.errors import (
    grant_denied,
    grant_not_found,
    provider_secret_not_configured,
)
from backend.app.credentials.models import CredentialGrant
from backend.app.credentials.ports import CredentialStorePort


def _default_clock() -> datetime:
    return datetime.now(UTC)


class CredentialBroker:
    def __init__(
        self,
        store: CredentialStorePort,
        *,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self.store = store
        self._clock = clock
        self._grants: dict[UUID, CredentialGrant] = {}

    def store_provider_secret(self, provider: str, token: str) -> None:
        self.store.set_secret(self._secret_name(provider), token)

    def revoke_provider_secret(self, provider: str) -> None:
        self.store.delete_secret(self._secret_name(provider))

    def issue_grant(
        self,
        *,
        actor_id: UUID,
        change_id: UUID,
        provider: str,
        scopes: Sequence[str],
        ttl: timedelta,
    ) -> CredentialGrant:
        now = self._clock()
        grant = CredentialGrant(
            id=uuid4(),
            actor_id=actor_id,
            change_id=change_id,
            provider=provider,
            scopes=list(scopes),
            issued_at=now,
            expires_at=now + ttl,
        )
        self._grants[grant.id] = grant
        return grant

    def revoke_grant(self, grant_id: UUID) -> CredentialGrant | None:
        grant = self._grants.get(grant_id)
        if grant is None or grant.revoked_at is not None:
            return grant
        revoked = grant.model_copy(update={"revoked_at": self._clock()})
        self._grants[grant_id] = revoked
        return revoked

    def get_grant(self, grant_id: UUID) -> CredentialGrant | None:
        return self._grants.get(grant_id)

    def resolve_secret(self, grant_id: UUID, *, scope: str) -> str:
        grant = self._grants.get(grant_id)
        if grant is None:
            raise grant_not_found(str(grant_id))
        now = self._clock()
        if grant.revoked_at is not None or now >= grant.expires_at:
            raise grant_denied(str(grant_id))
        if scope not in grant.scopes:
            raise grant_denied(str(grant_id))
        secret = self.store.get_secret(self._secret_name(grant.provider))
        if secret is None:
            raise provider_secret_not_configured(grant.provider)
        return secret

    @staticmethod
    def _secret_name(provider: str) -> str:
        return f"provider:{provider}"
