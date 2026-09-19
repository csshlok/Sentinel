from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.journal import JournalWriter


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


def test_delete_leaves_a_deletion_log_record_that_survives_the_journal_cascade(
    tmp_path,
) -> None:
    """Threat model finding #3: journal_events/journal_effects cascade-delete

    with their parent Change, so nothing about a deleted Change's journal
    history would otherwise survive. change_deletion_log has no FK to
    changes, so it must still hold the terminal event hash/seq/count after
    the cascade has removed the journal rows themselves.
    """

    database = Database(tmp_path / "changes.sqlite3")
    database.initialize()
    journal = JournalWriter(database)
    repository = ChangeRepository(database, journal=journal)
    now = datetime.now(UTC)
    change = StoredChange(
        id=uuid4(), title="Delete me", intent="Prove the deletion log survives",
        repository_path="C:\\work\\repo", created_at=now, updated_at=now,
        last_refreshed_at=None, git_summary=None, verification=None,
    )
    repository.create(change)
    from backend.app.contracts.models import JournalEventType
    first = journal.append(change.id, JournalEventType.CHANGE_CONTRACT_UPDATED)
    journal.append(change.id, JournalEventType.CHANGE_TRANSITIONED)

    assert repository.delete(change.id) is True

    with database.connection() as connection:
        journal_rows = connection.execute(
            "SELECT COUNT(*) FROM journal_events WHERE change_id = ?", (str(change.id),)
        ).fetchone()[0]
        log_row = connection.execute(
            "SELECT * FROM change_deletion_log WHERE change_id = ?", (str(change.id),)
        ).fetchone()

    # The cascade genuinely removed the journal (this is by design, A.4).
    assert journal_rows == 0
    # But the deletion log independently survived it.
    assert log_row is not None
    assert log_row["journal_event_count"] == 4  # create + 2 appended + CHANGE_DELETED
    assert log_row["last_event_seq"] == 4
    assert log_row["last_event_hash"] is not None
    assert log_row["last_event_hash"] != first.event_hash

