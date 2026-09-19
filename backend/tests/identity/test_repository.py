from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.identity.models import Actor, ActorKind, Delegation
from backend.app.identity.repository import ActorRepository, DelegationRepository

REPO_PATH = "C:\\work\\repo"


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "identity.sqlite3")
    database.initialize()
    return database


def _create_change_row(database: Database, change_id: UUID) -> None:
    now = datetime.now(UTC)
    ChangeRepository(database).create(
        StoredChange(
            id=change_id,
            title="Test change",
            intent="Exercise delegation persistence",
            repository_path=REPO_PATH,
            created_at=now,
            updated_at=now,
            last_refreshed_at=None,
            git_summary=None,
            verification=None,
        )
    )


def test_actor_persists_across_connections(tmp_path) -> None:
    database = _database(tmp_path)
    repository = ActorRepository(database)
    now = datetime.now(UTC)
    actor = Actor(
        id=uuid4(),
        kind=ActorKind.AGENT,
        display_name="Codex AG-182",
        created_at=now,
        updated_at=now,
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
    _create_change_row(database, change_id)
    delegation = Delegation(
        id=uuid4(),
        grantor_id=uuid4(),
        grantee_id=uuid4(),
        change_id=change_id,
        repository_path=REPO_PATH,
        scopes=["github.repo.read", "github.pr.create"],
        issued_at=now,
        expires_at=now + timedelta(hours=1),
        use_limit=2,
    )

    repository.create(delegation)
    assert repository.get(delegation.id) == delegation
    assert repository.list_for_grantee(delegation.grantee_id, change_id) == [
        delegation
    ]

    used = repository.record_use(delegation.id)
    assert used is not None
    assert used.uses == 1

    revoked = repository.revoke(delegation.id, now + timedelta(minutes=5))
    assert revoked is not None
    assert revoked.revoked_at is not None

    assert repository.revoke(delegation.id, now + timedelta(minutes=10)) is None
    assert repository.revoke(uuid4(), now) is None
    assert repository.record_use(uuid4()) is None
