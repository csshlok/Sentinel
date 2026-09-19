from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.contracts.models import JournalEventType
from backend.app.contracts.ports import CredentialBrokerPort
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter, row_to_event
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore

CANARY_SECRET = "ghp_do_not_leak_this_canary_value"
ONE_HOUR_SECONDS = 3600


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _broker() -> tuple[CredentialBroker, _FakeClock]:
    clock = _FakeClock(datetime.now(UTC))
    broker = CredentialBroker(InMemoryCredentialStore(), clock=clock)
    return broker, clock


def test_broker_satisfies_the_frozen_port() -> None:
    broker, _ = _broker()
    assert isinstance(broker, CredentialBrokerPort)


def test_resolve_secret_returns_stored_value_for_valid_grant() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        uuid4(), uuid4(), ["github.pr.create"], ONE_HOUR_SECONDS
    )

    resolved = broker.resolve_secret(grant.id, scope="github.pr.create")

    assert resolved == CANARY_SECRET
    assert grant.provider == "github"


def test_grant_object_never_contains_the_secret() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        uuid4(), uuid4(), ["github.pr.create"], ONE_HOUR_SECONDS
    )

    assert CANARY_SECRET not in repr(grant)
    assert CANARY_SECRET not in grant.model_dump_json()


def test_resolve_secret_denies_unknown_grant() -> None:
    broker, _ = _broker()
    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(uuid4(), scope="github.pr.create")
    assert excinfo.value.code == "CREDENTIAL_GRANT_NOT_FOUND"


def test_revoke_unknown_grant_raises() -> None:
    broker, _ = _broker()
    with pytest.raises(AppError) as excinfo:
        broker.revoke(uuid4())
    assert excinfo.value.code == "CREDENTIAL_GRANT_NOT_FOUND"


def test_resolve_secret_denies_expired_grant() -> None:
    broker, clock = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(uuid4(), uuid4(), ["github.pr.create"], 300)
    clock.now += timedelta(seconds=301)

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "CREDENTIAL_GRANT_DENIED"


def test_resolve_secret_denies_revoked_grant() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        uuid4(), uuid4(), ["github.pr.create"], ONE_HOUR_SECONDS
    )
    broker.revoke(grant.id)

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "CREDENTIAL_GRANT_DENIED"


def test_resolve_secret_denies_wrong_scope() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    grant = broker.issue_grant(
        uuid4(), uuid4(), ["github.repo.read"], ONE_HOUR_SECONDS
    )

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.force_push")
    assert excinfo.value.code == "CREDENTIAL_GRANT_DENIED"


def test_resolve_secret_denies_when_provider_never_configured() -> None:
    broker, _ = _broker()
    grant = broker.issue_grant(
        uuid4(), uuid4(), ["github.pr.create"], ONE_HOUR_SECONDS
    )

    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "PROVIDER_SECRET_NOT_CONFIGURED"


def test_resolve_secret_journals_metadata_only_never_the_raw_secret(tmp_path) -> None:
    """C.5's dedicated adversarial test: the highest-risk emission point in
    the whole journal must never leak the resolved secret into
    `journal_events.payload_json`, only {grant_id, scope, provider}."""

    database = Database(tmp_path / "journal.sqlite3")
    database.initialize()
    change_id = uuid4()
    with database.connection(immediate=True) as connection:
        connection.execute(
            "INSERT INTO changes (id, title, intent, repository_path, created_at, updated_at) "
            "VALUES (?, 'T', 'I', 'C:\\repo', '2024-01-01T00:00:00+00:00', "
            "'2024-01-01T00:00:00+00:00')",
            (str(change_id),),
        )
    journal = JournalWriter(database)
    clock = _FakeClock(datetime.now(UTC))
    broker = CredentialBroker(InMemoryCredentialStore(), clock=clock, journal=journal)
    broker.store_provider_secret("github", CANARY_SECRET)
    actor_id = uuid4()
    grant = broker.issue_grant(actor_id, change_id, ["github.pr.create"], ONE_HOUR_SECONDS)

    resolved = broker.resolve_secret(grant.id, scope="github.pr.create")
    assert resolved == CANARY_SECRET

    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_events WHERE change_id = ?", (str(change_id),)
        ).fetchall()
    events = [row_to_event(row) for row in rows]
    resolved_events = [e for e in events if e.event_type is JournalEventType.CREDENTIAL_SECRET_RESOLVED]
    assert len(resolved_events) == 1
    event = resolved_events[0]
    assert set(event.payload) == {"grant_id", "scope", "provider"}
    assert event.payload == {"grant_id": str(grant.id), "scope": "github.pr.create", "provider": "github"}

    # The canary must not appear anywhere in the serialized journal row.
    with database.connection() as connection:
        payload_blob = "\n".join(
            row["payload_json"] for row in connection.execute(
                "SELECT payload_json FROM journal_events"
            ).fetchall()
        )
    assert CANARY_SECRET not in payload_blob


def test_revoke_provider_secret_removes_it_from_the_store() -> None:
    broker, _ = _broker()
    broker.store_provider_secret("github", CANARY_SECRET)
    broker.revoke_provider_secret("github")

    grant = broker.issue_grant(
        uuid4(), uuid4(), ["github.pr.create"], ONE_HOUR_SECONDS
    )
    with pytest.raises(AppError) as excinfo:
        broker.resolve_secret(grant.id, scope="github.pr.create")
    assert excinfo.value.code == "PROVIDER_SECRET_NOT_CONFIGURED"
