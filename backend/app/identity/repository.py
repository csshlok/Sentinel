"""Owner-local persistence for actors and delegations.

Consumes `backend.app.core.database.Database`'s connection boundary
without editing shared core/migration files. This module manages its
own tables idempotently, the same way `Database.initialize` manages the
`changes` table, until `[SD]` promotes this schema into a shared
migration.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from backend.app.core.database import Database
from backend.app.identity.models import Actor, ActorKind, Delegation

SCHEMA = """
CREATE TABLE IF NOT EXISTS identity_actors (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_delegations (
    id TEXT PRIMARY KEY,
    grantor_actor_id TEXT NOT NULL,
    grantee_actor_id TEXT NOT NULL,
    change_id TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    scopes_json TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NULL,
    max_uses INTEGER NULL,
    use_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_identity_delegations_grantee
ON identity_delegations(grantee_actor_id, change_id);
"""


class ActorRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        with self.database.connection() as connection:
            connection.executescript(SCHEMA)

    def create(self, actor: Actor) -> Actor:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO identity_actors (id, kind, display_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(actor.id),
                    actor.kind.value,
                    actor.display_name,
                    actor.created_at.isoformat(),
                ),
            )
        return actor

    def get(self, actor_id: UUID) -> Actor | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM identity_actors WHERE id = ?", (str(actor_id),)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    @staticmethod
    def _from_row(row: object) -> Actor:
        return Actor(
            id=UUID(row["id"]),  # type: ignore[index]
            kind=ActorKind(row["kind"]),  # type: ignore[index]
            display_name=row["display_name"],  # type: ignore[index]
            created_at=datetime.fromisoformat(row["created_at"]),  # type: ignore[index]
        )


class DelegationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database
        with self.database.connection() as connection:
            connection.executescript(SCHEMA)

    def create(self, delegation: Delegation) -> Delegation:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO identity_delegations (
                    id, grantor_actor_id, grantee_actor_id, change_id,
                    repository_path, scopes_json, issued_at, expires_at,
                    revoked_at, max_uses, use_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._to_values(delegation),
            )
        return delegation

    def get(self, delegation_id: UUID) -> Delegation | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM identity_delegations WHERE id = ?",
                (str(delegation_id),),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_grantee(
        self, grantee_actor_id: UUID, change_id: UUID
    ) -> list[Delegation]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM identity_delegations
                WHERE grantee_actor_id = ? AND change_id = ?
                ORDER BY issued_at DESC
                """,
                (str(grantee_actor_id), str(change_id)),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def revoke(self, delegation_id: UUID, revoked_at: datetime) -> Delegation | None:
        with self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE identity_delegations
                SET revoked_at = ?
                WHERE id = ? AND revoked_at IS NULL
                """,
                (revoked_at.isoformat(), str(delegation_id)),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(delegation_id)

    def record_use(self, delegation_id: UUID) -> Delegation | None:
        with self.database.connection() as connection:
            cursor = connection.execute(
                "UPDATE identity_delegations SET use_count = use_count + 1 WHERE id = ?",
                (str(delegation_id),),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(delegation_id)

    @staticmethod
    def _to_values(delegation: Delegation) -> tuple[str | int | None, ...]:
        return (
            str(delegation.id),
            str(delegation.grantor_actor_id),
            str(delegation.grantee_actor_id),
            str(delegation.change_id),
            delegation.repository_path,
            json.dumps(list(delegation.scopes), separators=(",", ":")),
            delegation.issued_at.isoformat(),
            delegation.expires_at.isoformat(),
            delegation.revoked_at.isoformat() if delegation.revoked_at else None,
            delegation.max_uses,
            delegation.use_count,
        )

    @staticmethod
    def _from_row(row: object) -> Delegation:
        return Delegation(
            id=UUID(row["id"]),  # type: ignore[index]
            grantor_actor_id=UUID(row["grantor_actor_id"]),  # type: ignore[index]
            grantee_actor_id=UUID(row["grantee_actor_id"]),  # type: ignore[index]
            change_id=UUID(row["change_id"]),  # type: ignore[index]
            repository_path=row["repository_path"],  # type: ignore[index]
            scopes=json.loads(row["scopes_json"]),  # type: ignore[index]
            issued_at=datetime.fromisoformat(row["issued_at"]),  # type: ignore[index]
            expires_at=datetime.fromisoformat(row["expires_at"]),  # type: ignore[index]
            revoked_at=datetime.fromisoformat(row["revoked_at"])  # type: ignore[index]
            if row["revoked_at"]  # type: ignore[index]
            else None,
            max_uses=row["max_uses"],  # type: ignore[index]
            use_count=row["use_count"],  # type: ignore[index]
        )
