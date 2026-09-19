"""Unit and adversarial tests for `JournalWriter` (Event/Effect Journal, J0)."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest

from backend.app.contracts.models import JournalEventType, RestorationClass
from backend.app.core.database import Database
from backend.app.core.journal import JournalWriter, compute_event_hash


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "journal.sqlite3")
    database.initialize()
    return database


def _make_change(database: Database, change_id) -> None:
    with database.connection(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO changes (
                id, title, intent, repository_path, created_at, updated_at
            ) VALUES (?, 'T', 'I', 'C:\\repo', '2024-01-01T00:00:00+00:00',
                      '2024-01-01T00:00:00+00:00')
            """,
            (str(change_id),),
        )


def test_first_event_has_no_prev_hash_and_seq_one(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)

    event = writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={"a": 1})

    assert event.seq == 1
    assert event.prev_event_hash is None
    assert len(event.event_hash) == 64


def test_hash_chain_links_across_n_events(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)

    events = [
        writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={"i": i})
        for i in range(10)
    ]

    for index, event in enumerate(events):
        assert event.seq == index + 1
        if index == 0:
            assert event.prev_event_hash is None
        else:
            assert event.prev_event_hash == events[index - 1].event_hash
        recomputed = compute_event_hash(
            prev_event_hash=event.prev_event_hash,
            seq=event.seq,
            change_id=event.change_id,
            event_type=event.event_type.value,
            actor_id=event.actor_id,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            payload=event.payload,
            occurred_at=event.occurred_at,
            schema_version=event.schema_version,
        )
        assert recomputed == event.event_hash


def test_canonicalization_is_deterministic_regardless_of_key_order() -> None:
    from datetime import UTC, datetime

    change_id = uuid4()
    occurred_at = datetime(2024, 1, 1, tzinfo=UTC)
    common = dict(
        prev_event_hash=None,
        seq=1,
        change_id=change_id,
        event_type="change.created",
        actor_id=None,
        subject_type=None,
        subject_id=None,
        occurred_at=occurred_at,
        schema_version=1,
    )
    first = compute_event_hash(payload={"z": 1, "a": 2}, **common)
    second = compute_event_hash(payload={"a": 2, "z": 1}, **common)
    assert first == second


def test_sequences_are_independent_per_change(tmp_path) -> None:
    database = _database(tmp_path)
    change_a, change_b = uuid4(), uuid4()
    _make_change(database, change_a)
    _make_change(database, change_b)
    writer = JournalWriter(database)

    ea1 = writer.append(change_a, JournalEventType.CHANGE_CREATED, payload={})
    eb1 = writer.append(change_b, JournalEventType.CHANGE_CREATED, payload={})
    ea2 = writer.append(change_a, JournalEventType.CHANGE_TRANSITIONED, payload={})

    assert ea1.seq == 1
    assert eb1.seq == 1
    assert ea2.seq == 2
    assert eb1.prev_event_hash is None


def test_sequence_allocation_under_two_connections_never_collides(tmp_path) -> None:
    """Two independent `JournalWriter`s against the same file never produce a
    seq collision: `BEGIN IMMEDIATE` serializes the second behind the first."""

    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer_a = JournalWriter(database)
    writer_b = JournalWriter(database)

    events = []
    for i in range(6):
        writer = writer_a if i % 2 == 0 else writer_b
        events.append(writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={"i": i}))

    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_oversized_payload_is_bounded_not_silently_truncated(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)

    huge = {"blob": "x" * 20_000}
    event = writer.append(change_id, JournalEventType.CHANGE_CREATED, payload=huge)

    assert event.payload.get("truncated") is True
    assert "sha256" in event.payload
    assert "blob" not in event.payload


def test_append_effect_records_before_and_produced_digest(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)

    event = writer.append(change_id, JournalEventType.GIT_CHECKPOINT_CAPTURED, payload={})
    resource_id = uuid4()
    effect = writer.append_effect(
        event,
        resource_type="git_checkpoint",
        resource_id=resource_id,
        restoration_class=RestorationClass.NONE,
        before_digest=None,
        produced_digest="a" * 64,
    )

    assert effect.event_id == event.id
    assert effect.restoration_class is RestorationClass.NONE
    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM journal_effects WHERE id = ?", (str(effect.id),)
        ).fetchone()
    assert row["produced_digest"] == "a" * 64


def test_shared_connection_commits_atomically_with_caller_transaction(tmp_path) -> None:
    """Passing an open connection means a caller rollback also rolls back the event."""

    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)

    with pytest.raises(RuntimeError):
        with database.connection(immediate=True) as connection:
            writer.append(
                change_id, JournalEventType.CHANGE_CREATED, payload={}, connection=connection
            )
            raise RuntimeError("simulated failure after journal append")

    with database.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS n FROM journal_events WHERE change_id = ?",
            (str(change_id),),
        ).fetchone()["n"]
    assert count == 0


# -- adversarial: append-only enforcement -------------------------------------


def test_direct_sqlite_update_against_journal_events_is_rejected(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)
    event = writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={"a": 1})

    connection = sqlite3.connect(database.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(
                "UPDATE journal_events SET event_hash = 'tampered' WHERE id = ?",
                (str(event.id),),
            )
    finally:
        connection.close()


def test_direct_sqlite_delete_against_journal_events_is_rejected(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)
    event = writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={"a": 1})

    connection = sqlite3.connect(database.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("DELETE FROM journal_events WHERE id = ?", (str(event.id),))
    finally:
        connection.close()


def test_change_deletion_cascade_is_not_blocked_by_the_append_only_trigger(tmp_path) -> None:
    """Regression test for migration 5: an unqualified BEFORE DELETE trigger
    also fires for rows removed by an ON DELETE CASCADE action, not just a
    direct DELETE statement -- so deleting a Change must still succeed even
    though journal_events/journal_effects are append-only, while a *direct*
    delete against a live Change's journal rows remains rejected."""

    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)
    event = writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={})
    writer.append_effect(
        event, resource_type="git_checkpoint", resource_id=uuid4(),
        restoration_class=RestorationClass.NONE, produced_digest="a" * 64,
    )

    with database.connection(immediate=True) as connection:
        connection.execute("DELETE FROM changes WHERE id = ?", (str(change_id),))

    with database.connection() as connection:
        remaining_events = connection.execute(
            "SELECT COUNT(*) AS n FROM journal_events WHERE change_id = ?",
            (str(change_id),),
        ).fetchone()["n"]
        remaining_effects = connection.execute(
            "SELECT COUNT(*) AS n FROM journal_effects WHERE change_id = ?",
            (str(change_id),),
        ).fetchone()["n"]
    assert remaining_events == 0
    assert remaining_effects == 0


def test_direct_sqlite_update_against_journal_effects_is_rejected(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)
    event = writer.append(change_id, JournalEventType.GIT_CHECKPOINT_CAPTURED, payload={})
    effect = writer.append_effect(
        event,
        resource_type="git_checkpoint",
        resource_id=uuid4(),
        restoration_class=RestorationClass.NONE,
        produced_digest="a" * 64,
    )

    connection = sqlite3.connect(database.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(
                "UPDATE journal_effects SET produced_digest = 'b' WHERE id = ?",
                (str(effect.id),),
            )
    finally:
        connection.close()


def test_offline_file_level_tamper_is_detectable_by_recomputation(tmp_path) -> None:
    """The append-only triggers reject any UPDATE from a live SQL connection
    (proven above); the only way to alter `event_hash` at all is to bypass the
    trigger mechanism itself, which is what genuine offline file-level
    tampering (the daemon stopped, the trigger not evaluated) would do. This
    test simulates exactly that boundary by dropping the trigger first — the
    one operation no live application connection ever performs — and proves
    `compute_event_hash` recomputation (the mechanism `ChainVerificationResult`,
    built in J3, relies on) detects the resulting mismatch."""

    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    writer = JournalWriter(database)
    event = writer.append(change_id, JournalEventType.CHANGE_CREATED, payload={"a": 1})

    connection = sqlite3.connect(database.path)
    try:
        connection.execute("DROP TRIGGER journal_events_immutable_update")
        connection.execute(
            "UPDATE journal_events SET event_hash = ? WHERE id = ?",
            ("0" * 64, str(event.id)),
        )
        connection.commit()
    finally:
        connection.close()

    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM journal_events WHERE id = ?", (str(event.id),)
        ).fetchone()
    import json as _json
    from datetime import datetime as _dt

    recomputed = compute_event_hash(
        prev_event_hash=row["prev_event_hash"],
        seq=row["seq"],
        change_id=change_id,
        event_type=row["event_type"],
        actor_id=None,
        subject_type=row["subject_type"],
        subject_id=None,
        payload=_json.loads(row["payload_json"]),
        occurred_at=_dt.fromisoformat(row["occurred_at"]),
        schema_version=row["schema_version"],
    )
    assert recomputed != row["event_hash"]
    assert row["event_hash"] == "0" * 64
