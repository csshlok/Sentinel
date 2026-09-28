"""SQLite persistence for ``change_workspaces`` (migration 012)."""

from __future__ import annotations

import sqlite3
from uuid import UUID

from backend.app.contracts.models import WorkspaceState
from backend.app.core.database import Database
from backend.app.workspace.errors import workspace_state_conflict
from backend.app.workspace.models import WorkspaceRecord


class WorkspaceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(
        self, record: WorkspaceRecord, *, connection: sqlite3.Connection | None = None
    ) -> WorkspaceRecord:
        with self.database.connection_or(connection, immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO change_workspaces (
                    id, change_id, profile_name, state, active_run_id, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.id),
                    str(record.change_id),
                    record.profile_name,
                    record.state.value,
                    record.active_run_id,
                    record.to_json(),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
        return record

    def update(
        self, record: WorkspaceRecord, *, expected_state: WorkspaceState,
        connection: sqlite3.Connection | None = None,
    ) -> WorkspaceRecord:
        """Compare-and-set on ``state``: a concurrent transition raises a conflict."""

        with self.database.connection_or(connection, immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE change_workspaces
                SET state = ?, active_run_id = ?, payload_json = ?, updated_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    record.state.value,
                    record.active_run_id,
                    record.to_json(),
                    record.updated_at.isoformat(),
                    str(record.id),
                    expected_state.value,
                ),
            )
            if cursor.rowcount != 1:
                row = conn.execute(
                    "SELECT state FROM change_workspaces WHERE id = ?", (str(record.id),)
                ).fetchone()
                raise workspace_state_conflict(
                    row["state"] if row is not None else "MISSING", "update"
                )
        return record

    def get(
        self, workspace_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> WorkspaceRecord | None:
        with self.database.connection_or(connection) as conn:
            row = conn.execute(
                "SELECT * FROM change_workspaces WHERE id = ?", (str(workspace_id),)
            ).fetchone()
        return WorkspaceRecord.from_row(row) if row is not None else None

    def live_for_change(
        self, change_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> WorkspaceRecord | None:
        with self.database.connection_or(connection) as conn:
            row = conn.execute(
                "SELECT * FROM change_workspaces WHERE change_id = ? AND state != ?",
                (str(change_id), WorkspaceState.CLEANED.value),
            ).fetchone()
        return WorkspaceRecord.from_row(row) if row is not None else None

    def latest_for_change(
        self, change_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> WorkspaceRecord | None:
        with self.database.connection_or(connection) as conn:
            row = conn.execute(
                "SELECT * FROM change_workspaces WHERE change_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (str(change_id),),
            ).fetchone()
        return WorkspaceRecord.from_row(row) if row is not None else None

    def list_unclean(
        self, *, connection: sqlite3.Connection | None = None
    ) -> list[WorkspaceRecord]:
        with self.database.connection_or(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM change_workspaces WHERE state != ? ORDER BY created_at, rowid",
                (WorkspaceState.CLEANED.value,),
            ).fetchall()
        return [WorkspaceRecord.from_row(row) for row in rows]
