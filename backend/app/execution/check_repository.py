"""SQLite persistence for ``check_runs`` (migration 013): one row per confined check box.

A row is inserted (state CREATING) before the box's AppContainer profile is
created and is the only durable record of that profile, its tree and the
runtime ACEs granted to its package SID; the DB-driven sweep relies on it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from backend.app.core.database import Database
from backend.app.core.errors import AppError


class CheckRunState(StrEnum):
    CREATING = "CREATING"
    READY = "READY"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    CLEANED = "CLEANED"
    CLEANUP_FAILED = "CLEANUP_FAILED"


@dataclass(frozen=True, slots=True)
class RuntimeGrant:
    """One runtime cache entry the box's package SID was (or will be) granted read on."""

    path: str
    manifest_digest: str

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "manifest_digest": self.manifest_digest}


@dataclass(frozen=True, slots=True)
class CheckRunRecord:
    id: UUID
    change_id: UUID
    profile_name: str
    package_sid: str
    state: CheckRunState
    network: bool
    runtime_grants: tuple[RuntimeGrant, ...]
    created_at: datetime
    updated_at: datetime
    tree_digest: str | None = None
    facts: dict[str, Any] | None = None
    exit_code: int | None = None
    timed_out: bool | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CheckRunRecord:
        grants = tuple(
            RuntimeGrant(str(item["path"]), str(item["manifest_digest"]))
            for item in json.loads(row["runtime_digests_json"])
        )
        return cls(
            id=UUID(row["id"]),
            change_id=UUID(row["change_id"]),
            profile_name=row["profile_name"],
            package_sid=row["package_sid"],
            state=CheckRunState(row["state"]),
            network=bool(row["network"]),
            runtime_grants=grants,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            tree_digest=row["tree_digest"],
            facts=json.loads(row["facts_json"]) if row["facts_json"] else None,
            exit_code=row["exit_code"],
            timed_out=None if row["timed_out"] is None else bool(row["timed_out"]),
        )


def check_run_state_conflict(actual: str, operation: str) -> AppError:
    return AppError(
        "CHECK_RUN_STATE_CONFLICT",
        "The check run is not in a state that allows this operation.",
        status_code=409,
        details={"state": actual, "operation": operation},
    )


def _grants_json(grants: tuple[RuntimeGrant, ...]) -> str:
    return json.dumps([grant.to_payload() for grant in grants], sort_keys=True,
                      separators=(",", ":"))


class CheckRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(
        self, record: CheckRunRecord, *, connection: sqlite3.Connection | None = None
    ) -> CheckRunRecord:
        with self.database.connection_or(connection, immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO check_runs (
                    id, change_id, profile_name, package_sid, state, network, tree_digest,
                    runtime_digests_json, facts_json, exit_code, timed_out, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.id), str(record.change_id), record.profile_name,
                    record.package_sid, record.state.value, int(record.network),
                    record.tree_digest, _grants_json(record.runtime_grants),
                    json.dumps(record.facts, sort_keys=True) if record.facts is not None else None,
                    record.exit_code,
                    None if record.timed_out is None else int(record.timed_out),
                    record.created_at.isoformat(), record.updated_at.isoformat(),
                ),
            )
        return record

    def update(
        self, record: CheckRunRecord, *, expected_state: CheckRunState,
        connection: sqlite3.Connection | None = None,
    ) -> CheckRunRecord:
        """Compare-and-set on ``state``; a concurrent transition raises a conflict."""

        with self.database.connection_or(connection, immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE check_runs
                SET state = ?, tree_digest = ?, facts_json = ?, exit_code = ?,
                    timed_out = ?, updated_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    record.state.value, record.tree_digest,
                    json.dumps(record.facts, sort_keys=True) if record.facts is not None else None,
                    record.exit_code,
                    None if record.timed_out is None else int(record.timed_out),
                    record.updated_at.isoformat(), str(record.id), expected_state.value,
                ),
            )
            if cursor.rowcount != 1:
                row = conn.execute(
                    "SELECT state FROM check_runs WHERE id = ?", (str(record.id),)
                ).fetchone()
                raise check_run_state_conflict(
                    row["state"] if row is not None else "MISSING", "update")
        return record

    def get(
        self, run_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> CheckRunRecord | None:
        with self.database.connection_or(connection) as conn:
            row = conn.execute("SELECT * FROM check_runs WHERE id = ?", (str(run_id),)).fetchone()
        return CheckRunRecord.from_row(row) if row is not None else None

    def list_unclean(
        self, *, connection: sqlite3.Connection | None = None
    ) -> list[CheckRunRecord]:
        with self.database.connection_or(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM check_runs WHERE state != ? ORDER BY created_at, rowid",
                (CheckRunState.CLEANED.value,),
            ).fetchall()
        return [CheckRunRecord.from_row(row) for row in rows]

    def for_change(
        self, change_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> list[CheckRunRecord]:
        with self.database.connection_or(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM check_runs WHERE change_id = ? ORDER BY created_at, rowid",
                (str(change_id),),
            ).fetchall()
        return [CheckRunRecord.from_row(row) for row in rows]
