"""Read-only lookup of `[KB]`'s persisted Git checkpoints.

Consumes the `git_checkpoints` table (schema owned by `[SD]`, written by
`[KB]`) strictly through the frozen `GitCheckpoint` contract's own JSON
serialization — never a private implementation detail of `[KB]`'s
concrete Git adapter.
"""

from __future__ import annotations

from uuid import UUID

from backend.app.contracts.models import GitCheckpoint
from backend.app.core.database import Database


def get_earliest_checkpoint(database: Database, change_id: UUID) -> GitCheckpoint | None:
    with database.connection() as connection:
        row = connection.execute(
            """
            SELECT payload_json FROM git_checkpoints
            WHERE change_id = ?
            ORDER BY evidence_revision ASC, captured_at ASC
            LIMIT 1
            """,
            (str(change_id),),
        ).fetchone()
    return GitCheckpoint.model_validate_json(row["payload_json"]) if row else None


def get_checkpoint_by_id(database: Database, checkpoint_id: UUID) -> GitCheckpoint | None:
    with database.connection() as connection:
        row = connection.execute(
            "SELECT payload_json FROM git_checkpoints WHERE id = ?",
            (str(checkpoint_id),),
        ).fetchone()
    return GitCheckpoint.model_validate_json(row["payload_json"]) if row else None
