from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database


def test_change_persists_across_connections(tmp_path) -> None:
    database = Database(tmp_path / "data" / "changes.sqlite3")
    database.initialize()
    repository = ChangeRepository(database)
    now = datetime.now(UTC)
    change = StoredChange(
        id=uuid4(),
        title="Test change",
        intent="Exercise persistence",
        repository_path="C:\\work\\repo",
        created_at=now,
        updated_at=now,
        last_refreshed_at=None,
        git_summary=None,
        verification=None,
    )

    repository.create(change)
    reopened = ChangeRepository(Database(database.path))

    assert reopened.get(change.id) == change
    assert reopened.list() == [change]


def test_delete_only_removes_metadata(tmp_path) -> None:
    database = Database(tmp_path / "changes.sqlite3")
    database.initialize()
    repository = ChangeRepository(database)
    now = datetime.now(UTC)
    change = StoredChange(
        id=uuid4(),
        title="Delete me",
        intent="Delete metadata only",
        repository_path="C:\\work\\repo",
        created_at=now,
        updated_at=now,
        last_refreshed_at=None,
        git_summary=None,
        verification=None,
    )
    repository.create(change)

    assert repository.delete(change.id) is True
    assert repository.delete(change.id) is False

