"""Owner-local persistence for actors and delegations.

Reads and writes the canonical `actors`/`delegations` tables created by
`[SD]`'s `backend.migrations.versions.migration_002_change_runtime_core`
(applied by `Database.initialize`). This module owns no schema of its
own; it only consumes the already-migrated tables through
`Database.connection()`, matching the shared `Actor`/`Delegation`
contracts from `backend.app.contracts.models`.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from backend.app.contracts.models import Actor, ActorKind, Delegation
from backend.app.core.database import Database


class ActorRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, actor: Actor) -> Actor:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO actors (
                    id, kind, display_name, provenance_json, created_at,
                    updated_at, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(actor.id),
                    actor.kind.value,
                    actor.display_name,
                    json.dumps(actor.provenance, separators=(",", ":")),
                    actor.created_at.isoformat(),
                    actor.updated_at.isoformat(),
                    actor.revision,
                ),
            )
        return actor

    def get(self, actor_id: UUID) -> Actor | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM actors WHERE id = ?", (str(actor_id),)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    @staticmethod
    def _from_row(row: object) -> Actor:
        return Actor(
            id=UUID(row["id"]),  # type: ignore[index]
            kind=ActorKind(row["kind"]),  # type: ignore[index]
            display_name=row["display_name"],  # type: ignore[index]
            provenance=json.loads(row["provenance_json"]),  # type: ignore[index]
            created_at=datetime.fromisoformat(row["created_at"]),  # type: ignore[index]
            updated_at=datetime.fromisoformat(row["updated_at"]),  # type: ignore[index]
            revision=row["revision"],  # type: ignore[index]
        )


class DelegationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, delegation: Delegation) -> Delegation:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO delegations (
                    id, grantor_id, grantee_id, change_id,
                    repository_path, scopes_json, issued_at, expires_at,
                    revoked_at, use_limit, uses
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._to_values(delegation),
            )
        return delegation

    def get(self, delegation_id: UUID) -> Delegation | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM delegations WHERE id = ?",
                (str(delegation_id),),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_grantee(self, grantee_id: UUID, change_id: UUID) -> list[Delegation]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM delegations
                WHERE grantee_id = ? AND change_id = ?
                ORDER BY issued_at DESC
                """,
                (str(grantee_id), str(change_id)),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_for_change(self, change_id: UUID) -> list[Delegation]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM delegations WHERE change_id = ? ORDER BY issued_at DESC",
                (str(change_id),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def revoke(self, delegation_id: UUID, revoked_at: datetime) -> Delegation | None:
        with self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE delegations
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
                "UPDATE delegations SET uses = uses + 1 WHERE id = ?",
                (str(delegation_id),),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(delegation_id)

    def consume_use(self, delegation_id: UUID) -> Delegation | None:
        """Atomically increment ``uses`` iff the delegation still has one to spend.

        Guards the read-then-write race a plain ``record_use`` after a separate
        ``evaluate_delegation`` check would allow: the limit check and the
        increment happen in one ``UPDATE ... WHERE`` statement inside an
        immediate transaction, so two concurrent requests against a
        ``use_limit=1`` delegation cannot both succeed. Returns ``None`` (not
        an exception) when the delegation is revoked or already exhausted, so
        the caller can fall back to the next candidate delegation or a denial.
        """

        with self.database.connection(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE delegations
                SET uses = uses + 1
                WHERE id = ?
                  AND revoked_at IS NULL
                  AND (use_limit IS NULL OR uses < use_limit)
                """,
                (str(delegation_id),),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM delegations WHERE id = ?", (str(delegation_id),)
            ).fetchone()
        return self._from_row(row)

    @staticmethod
    def _to_values(delegation: Delegation) -> tuple[str | int | None, ...]:
        return (
            str(delegation.id),
            str(delegation.grantor_id),
            str(delegation.grantee_id),
            str(delegation.change_id),
            delegation.repository_path,
            json.dumps(list(delegation.scopes), separators=(",", ":")),
            delegation.issued_at.isoformat(),
            delegation.expires_at.isoformat(),
            delegation.revoked_at.isoformat() if delegation.revoked_at else None,
            delegation.use_limit,
            delegation.uses,
        )

    @staticmethod
    def _from_row(row: object) -> Delegation:
        return Delegation(
            id=UUID(row["id"]),  # type: ignore[index]
            grantor_id=UUID(row["grantor_id"]),  # type: ignore[index]
            grantee_id=UUID(row["grantee_id"]),  # type: ignore[index]
            change_id=UUID(row["change_id"]),  # type: ignore[index]
            repository_path=row["repository_path"],  # type: ignore[index]
            scopes=json.loads(row["scopes_json"]),  # type: ignore[index]
            issued_at=datetime.fromisoformat(row["issued_at"]),  # type: ignore[index]
            expires_at=datetime.fromisoformat(row["expires_at"]),  # type: ignore[index]
            revoked_at=datetime.fromisoformat(row["revoked_at"])  # type: ignore[index]
            if row["revoked_at"]  # type: ignore[index]
            else None,
            use_limit=row["use_limit"],  # type: ignore[index]
            uses=row["uses"],  # type: ignore[index]
        )
