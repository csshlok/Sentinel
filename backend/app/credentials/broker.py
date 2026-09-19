"""Issues short-lived internal grants and gates access to durable secrets.

Implements `backend.app.contracts.ports.CredentialBrokerPort`. The
durable provider secret lives only in a `CredentialStorePort`
implementation. `resolve_secret` is the single boundary where that
secret leaves the store, and only for a grant that is present,
unrevoked, unexpired, and scoped to the request. No other method on
this class or on `CredentialGrant` ever exposes the raw secret.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.app.contracts.models import CredentialGrant, JournalEventType
from backend.app.contracts.ports import CredentialStorePort
from backend.app.credentials.errors import (
    grant_denied,
    grant_not_found,
    provider_secret_not_configured,
)
from backend.app.core.journal import JournalWriter


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _provider_from_scopes(scopes: Sequence[str]) -> str:
    first = scopes[0]
    return first.split(".", 1)[0] if "." in first else first


class CredentialBroker:
    """Implements `CredentialBrokerPort`."""

    def __init__(
        self,
        store: CredentialStorePort,
        *,
        clock: Callable[[], datetime] = _default_clock,
        journal: JournalWriter | None = None,
        grant_lookup: Callable[[UUID], CredentialGrant | None] | None = None,
    ) -> None:
        self.store = store
        self._clock = clock
        self._grants: dict[UUID, CredentialGrant] = {}
        self._journal = journal
        # Grants are durably persisted by `CredentialGrantRepository`
        # (composition-layer, `[SD]`-owned), but this broker previously
        # consulted only its own in-process `_grants` cache -- so every
        # grant became unreachable to `revoke`/`resolve_secret` the moment
        # the process restarted, even though it was still visible through
        # `GET`-style lookups backed by that repository. `grant_lookup`
        # (typically `CredentialGrantRepository.get`) is the durable source
        # of truth when supplied; the in-memory cache remains for callers
        # (mainly tests) that construct this broker standalone.
        self._grant_lookup = grant_lookup

    def store_provider_secret(self, provider: str, token: str) -> None:
        self.store.put(self._secret_key(provider), token)

    def revoke_provider_secret(self, provider: str) -> None:
        self.store.delete(self._secret_key(provider))

    def issue_grant(
        self,
        actor_id: UUID,
        change_id: UUID,
        scopes: list[str],
        ttl_seconds: int,
    ) -> CredentialGrant:
        now = self._clock()
        grant = CredentialGrant(
            id=uuid4(),
            actor_id=actor_id,
            change_id=change_id,
            provider=_provider_from_scopes(scopes),
            scopes=list(scopes),
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._grants[grant.id] = grant
        return grant

    def _get_grant(self, grant_id: UUID) -> CredentialGrant | None:
        if self._grant_lookup is not None:
            durable = self._grant_lookup(grant_id)
            if durable is not None:
                return durable
        return self._grants.get(grant_id)

    def revoke(self, grant_id: UUID) -> CredentialGrant:
        grant = self._get_grant(grant_id)
        if grant is None:
            raise grant_not_found(str(grant_id))
        if grant.revoked_at is not None:
            return grant
        revoked = grant.model_copy(update={"revoked_at": self._clock()})
        self._grants[grant_id] = revoked
        return revoked

    def get_grant(self, grant_id: UUID) -> CredentialGrant | None:
        return self._get_grant(grant_id)

    def resolve_secret(self, grant_id: UUID, *, scope: str) -> str:
        grant = self._get_grant(grant_id)
        if grant is None:
            raise grant_not_found(str(grant_id))
        now = self._clock()
        if grant.revoked_at is not None or now >= grant.expires_at:
            raise grant_denied(str(grant_id))
        if scope not in grant.scopes:
            raise grant_denied(str(grant_id))
        secret = self.store.get(self._secret_key(grant.provider))
        if secret is None:
            raise provider_secret_not_configured(grant.provider)
        # The single highest-risk emission point in the whole journal (A.5):
        # the payload carries only {grant_id, scope, provider} -- exactly the
        # fields available *without* touching `secret` -- so the raw value
        # can never reach `journal_events.payload_json`. See
        # backend/tests/credentials/test_broker.py's canary-secret test.
        if self._journal is not None:
            self._journal.append(
                grant.change_id, JournalEventType.CREDENTIAL_SECRET_RESOLVED,
                actor_id=grant.actor_id, subject_type="credential_grant",
                subject_id=grant.id,
                payload={"grant_id": str(grant.id), "scope": scope, "provider": grant.provider},
            )
        return secret

    @staticmethod
    def _secret_key(provider: str) -> str:
        return f"provider:{provider}"
