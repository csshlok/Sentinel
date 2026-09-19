"""Append-only, hash-chained Event/Effect Journal writer.

This is the 4th independent application of a canonicalization/hash-chaining
pattern already trusted elsewhere in this codebase:

- `backend/app/git/state.py::summary_digest` hash-chains Git evidence content.
- `backend/app/environment/tracker.py` uses `hmac.new(..., hashlib.sha256)`.
- `backend/app/passport/builder.py::PassportBuilder.build` computes a
  `canonical_digest` over sorted-key JSON.
- `backend/app/core/change_repository.py::ChangeRepository._request_hash`-style
  `json.dumps(payload, sort_keys=True, separators=(",", ":"))` canonicalization.

`JournalWriter.append`/`append_effect` accept an already-open `sqlite3.Connection`
when the caller already holds one open transaction, so the event row commits
atomically with the mutation it describes. Not every owner module in this
codebase threads a single connection through its whole call chain (several
open a fresh short transaction per save, e.g. `assurance.store.EvidenceStore`,
`credentials.broker.CredentialBroker` holds no database handle at all); for
those callers, omitting `connection` opens a dedicated `BEGIN IMMEDIATE`
transaction for the event alone. This is a documented, deliberate
simplification versus full connection-threading through every domain module:
the mutation row and its journal row are not always one atomic SQLite
transaction, but each write is independently durable, and callers always
persist the mutation itself before appending the event describing it, so a
crash between the two can only ever produce an under-journaled mutation, never
a phantom event describing something that did not happen.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    JournalEffect,
    JournalEvent,
    JournalEventType,
    RestorationClass,
    utc_now,
)
from backend.app.core.database import Database

MAX_PAYLOAD_BYTES = 8192
SCHEMA_VERSION = 1


def _canonical(body: dict[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bound_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Bound a payload to `MAX_PAYLOAD_BYTES`; oversized payloads are replaced
    with a digest envelope rather than silently truncated mid-structure."""

    body = payload or {}
    encoded = _canonical(body).encode("utf-8")
    if len(encoded) <= MAX_PAYLOAD_BYTES:
        return body
    return {
        "truncated": True,
        "original_size_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def compute_event_hash(
    *,
    prev_event_hash: str | None,
    seq: int,
    change_id: UUID,
    event_type: str,
    actor_id: UUID | None,
    subject_type: str | None,
    subject_id: UUID | None,
    payload: dict[str, Any],
    occurred_at: datetime,
    schema_version: int,
) -> str:
    """`sha256(prev_hash_or_empty + canonical_json(envelope))`, matching A.3."""

    body = {
        "seq": seq,
        "change_id": str(change_id),
        "event_type": str(event_type),
        "actor_id": str(actor_id) if actor_id is not None else None,
        "subject_type": subject_type,
        "subject_id": str(subject_id) if subject_id is not None else None,
        "payload": payload,
        "occurred_at": occurred_at.isoformat(),
        "schema_version": schema_version,
    }
    prefix = prev_event_hash or ""
    encoded = (prefix + _canonical(body)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class JournalWriter:
    """Append-only writer for `journal_events` / `journal_effects`.

    Never issues UPDATE/DELETE (the schema's triggers reject those outright as
    defense in depth). Sequence allocation reads `MAX(seq)` and inserts inside
    the same transaction, so under concurrent writers on the same Change the
    second writer's transaction either serializes behind the first (SQLite's
    `BEGIN IMMEDIATE` write lock) or the `UNIQUE(change_id, seq)` constraint
    rejects a race, matching `ChangeRepository`'s existing optimistic-
    concurrency pattern.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    def append(
        self,
        change_id: UUID,
        event_type: JournalEventType,
        *,
        actor_id: UUID | None = None,
        subject_type: str | None = None,
        subject_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> JournalEvent:
        bounded = bound_payload(payload)
        if connection is not None:
            return self._append_on(
                connection,
                change_id,
                event_type,
                actor_id=actor_id,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=bounded,
            )
        with self._db.connection(immediate=True) as conn:
            return self._append_on(
                conn,
                change_id,
                event_type,
                actor_id=actor_id,
                subject_type=subject_type,
                subject_id=subject_id,
                payload=bounded,
            )

    def append_effect(
        self,
        event: JournalEvent,
        *,
        resource_type: str,
        resource_id: UUID,
        restoration_class: RestorationClass,
        before_digest: str | None = None,
        produced_digest: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> JournalEffect:
        effect = JournalEffect(
            id=uuid4(),
            event_id=event.id,
            change_id=event.change_id,
            resource_type=resource_type,
            resource_id=resource_id,
            before_digest=before_digest,
            produced_digest=produced_digest,
            restoration_class=restoration_class,
        )
        if connection is not None:
            self._insert_effect(connection, effect)
            return effect
        with self._db.connection(immediate=True) as conn:
            self._insert_effect(conn, effect)
        return effect

    # -- internals ------------------------------------------------------------

    def _append_on(
        self,
        connection: sqlite3.Connection,
        change_id: UUID,
        event_type: JournalEventType,
        *,
        actor_id: UUID | None,
        subject_type: str | None,
        subject_id: UUID | None,
        payload: dict[str, Any],
    ) -> JournalEvent:
        prev_row = connection.execute(
            "SELECT seq, event_hash FROM journal_events WHERE change_id = ? "
            "ORDER BY seq DESC LIMIT 1",
            (str(change_id),),
        ).fetchone()
        seq = (int(prev_row["seq"]) if prev_row is not None else 0) + 1
        prev_hash = prev_row["event_hash"] if prev_row is not None else None
        occurred_at = utc_now()
        event_hash = compute_event_hash(
            prev_event_hash=prev_hash,
            seq=seq,
            change_id=change_id,
            event_type=str(event_type.value if hasattr(event_type, "value") else event_type),
            actor_id=actor_id,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
            occurred_at=occurred_at,
            schema_version=SCHEMA_VERSION,
        )
        event = JournalEvent(
            id=uuid4(),
            change_id=change_id,
            seq=seq,
            event_type=JournalEventType(event_type),
            actor_id=actor_id,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
            occurred_at=occurred_at,
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            schema_version=SCHEMA_VERSION,
        )
        connection.execute(
            """
            INSERT INTO journal_events (
                id, change_id, seq, event_type, actor_id, subject_type, subject_id,
                payload_json, occurred_at, prev_event_hash, event_hash, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.id),
                str(event.change_id),
                event.seq,
                event.event_type.value,
                str(event.actor_id) if event.actor_id is not None else None,
                event.subject_type,
                str(event.subject_id) if event.subject_id is not None else None,
                _canonical(event.payload),
                event.occurred_at.isoformat(),
                event.prev_event_hash,
                event.event_hash,
                event.schema_version,
            ),
        )
        return event

    @staticmethod
    def _insert_effect(connection: sqlite3.Connection, effect: JournalEffect) -> None:
        connection.execute(
            """
            INSERT INTO journal_effects (
                id, event_id, change_id, resource_type, resource_id,
                before_digest, produced_digest, restoration_class
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(effect.id),
                str(effect.event_id),
                str(effect.change_id),
                effect.resource_type,
                str(effect.resource_id),
                effect.before_digest,
                effect.produced_digest,
                effect.restoration_class.value,
            ),
        )


def row_to_event(row: sqlite3.Row) -> JournalEvent:
    """Reconstruct a `JournalEvent` from a raw `journal_events` row."""

    return JournalEvent(
        id=UUID(row["id"]),
        change_id=UUID(row["change_id"]),
        seq=int(row["seq"]),
        event_type=JournalEventType(row["event_type"]),
        actor_id=UUID(row["actor_id"]) if row["actor_id"] else None,
        subject_type=row["subject_type"],
        subject_id=UUID(row["subject_id"]) if row["subject_id"] else None,
        payload=json.loads(row["payload_json"]),
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        prev_event_hash=row["prev_event_hash"],
        event_hash=row["event_hash"],
        schema_version=int(row["schema_version"]),
    )


def row_to_effect(row: sqlite3.Row) -> JournalEffect:
    return JournalEffect(
        id=UUID(row["id"]),
        event_id=UUID(row["event_id"]),
        change_id=UUID(row["change_id"]),
        resource_type=row["resource_type"],
        resource_id=UUID(row["resource_id"]),
        before_digest=row["before_digest"],
        produced_digest=row["produced_digest"],
        restoration_class=RestorationClass(row["restoration_class"]),
    )
