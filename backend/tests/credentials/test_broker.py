from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore

CANARY_SECRET = "ghp_do_not_leak_this_canary_value"


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _broker() -> tuple[CredentialBroker, _FakeClock]:
    clock = _FakeClock(datetime.now(UTC))
    broker = CredentialBroker(InMemoryCredentialStore(), clock=clock)
    return broker, clock


def test_resolve_secret_returns_stored_value_for_valid_grant() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.pr.create"],
        ttl=timedelta(minutes=5),
    )

    resolved = broker.resolve_secret(grant.id, scope="github.pr.create")

    assert resolved == CANARY_SECRET


def test_grant_object_never_contains_the_secret() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.pr.create"],
        ttl=timedelta(minutes=5),
    )

    assert CANARY_SECRET not in repr(grant)
    assert CANARY_SECRET not in grant.model_dump_json()


def test_resolve_secret_denies_unknown_grant() -> None:
    broker, _ = _broker()
    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(uuid4(), scope="github.pr.create")
    assert excinfo.value.code == "CREDENTIAL_GRANT_NOT_FOUND"


def test_resolve_secret_denies_expired_grant() -> None:
    broker, clock = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.pr.create"],
        ttl=timedelta(minutes=5),
    )
    clock.now += timedelta(minutes=6)

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "CREDENTIAL_GRANT_DENIED"


def test_resolve_secret_denies_revoked_grant() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.pr.create"],
        ttl=timedelta(minutes=5),
    )
    broker.revoke_grant(grant.id)

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "CREDENTIAL_GRANT_DENIED"


def test_resolve_secret_denies_wrong_scope() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.repo.read"],
        ttl=timedelta(minutes=5),
    )

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.force_push")
    assert excinfo.value.code == "CREDENTIAL_GRANT_DENIED"


def test_resolve_secret_denies_when_provider_never_configured() -> None:
    broker, _ = _broker()
    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.pr.create"],
        ttl=timedelta(minutes=5),
    )

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "PROVIDER_SECRET_NOT_CONFIGURED"


def test_revoke_provider_secret_removes_it_from_the_store() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    broker.revoke_provider_secret("github")

    grant = broker.issue_grant(
        actor_id=uuid4(),
        change_id=uuid4(),
        provider="github",
        scopes=["github.pr.create"],
        ttl=timedelta(minutes=5),
    )
    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "PROVIDER_SECRET_NOT_CONFIGURED"
