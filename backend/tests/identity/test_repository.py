from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.core.database import Database
from backend.app.identity.models import Actor, ActorKind, Delegation
from backend.app.identity.repository import ActorRepository, DelegationRepository


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "identity.sqlite3")
    database.initialize()
    return database


def test_actor_persists_across_connections(tmp_path) -> None:
    database = _database(tmp_path)
    repository = ActorRepository(database)
    actor = Actor(
        id=uuid4(),
        kind=ActorKind.AGENT,
        display_name="Codex AG-182",
        created_at=datetime.now(UTC),
    )

    repository.create(actor)
    reopened = ActorRepository(Database(database.path))

    assert reopened.get(actor.id) == actor
    assert reopened.get(uuid4()) is None


def test_delegation_lifecycle(tmp_path) -> None:
    database = _database(tmp_path)
    repository = DelegationRepository(database)
    now = datetime.now(UTC)
    change_id = uuid4()
    delegation = Delegation(
        id=uuid4(),
        grantor_actor_id=uuid4(),
        grantee_actor_id=uuid4(),
        change_id=change_id,
        repository_path="C:\\work\\repo",
        scopes=["github.repo.read", "github.pr.create"],
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        max_uses=2,
    )

    repository.create(delegation)
    assert repository.get(delegation.id) == delegation
    assert repository.list_for_grantee(delegation.grantee_actor_id, change_id) == [
        delegation
    ]

    used = repository.record_use(delegation.id)
    assert used is not None
    assert used.use_count == 1

    revoked = repository.revoke(delegation.id, now + timedelta(minutes=5))
    assert revoked is not None
    assert revoked.revoked_at is not None

    assert repository.revoke(delegation.id, now + timedelta(minutes=10)) is None
    assert repository.revoke(uuid4(), now) is None
    assert repository.record_use(uuid4()) is None
