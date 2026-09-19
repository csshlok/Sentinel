"""Persistence for the AC-owned runtime entities against shared schema.

Mirrors the read/write pattern already used by
`backend.app.core.change_repository` and `backend.app.recovery.checkpoints`:
each frozen Pydantic contract is the source of truth and is stored either as
individual indexed columns (`credential_grants`, matching
`backend.app.identity.repository`'s style) or as a verbatim `payload_json`
plus a few indexed columns for querying. These tables were created by
`backend.migrations.versions.migration_002_change_runtime_core`; this module
owns no schema of its own.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from backend.app.contracts.models import (
    ChangePassport,
    CredentialGrant,
    Outcome,
    ProviderOperation,
    ProviderOperationStatus,
    RecoveryPlan,
)
from backend.app.core.database import Database


class CredentialGrantRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self, grant: CredentialGrant, *, connection: sqlite3.Connection | None = None
    ) -> CredentialGrant:
        with self.database.connection_or(connection) as conn:
            conn.execute(
                """
                INSERT INTO credential_grants (
                    id, change_id, actor_id, provider, scopes_json,
                    issued_at, expires_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(grant.id),
                    str(grant.change_id),
                    str(grant.actor_id),
                    grant.provider,
                    json.dumps(list(grant.scopes), separators=(",", ":")),
                    grant.issued_at.isoformat(),
                    grant.expires_at.isoformat(),
                    grant.revoked_at.isoformat() if grant.revoked_at else None,
                ),
            )
        return grant

    def get(self, grant_id: UUID) -> CredentialGrant | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM credential_grants WHERE id = ?", (str(grant_id),)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def revoke(
        self, grant_id: UUID, revoked_at: datetime,
        *, connection: sqlite3.Connection | None = None,
    ) -> CredentialGrant | None:
        with self.database.connection_or(connection) as conn:
            cursor = conn.execute(
                "UPDATE credential_grants SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (revoked_at.isoformat(), str(grant_id)),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM credential_grants WHERE id = ?", (str(grant_id),)
            ).fetchone()
        return self._from_row(row) if row is not None else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CredentialGrant:
        return CredentialGrant(
            id=UUID(row["id"]),
            actor_id=UUID(row["actor_id"]),
            change_id=UUID(row["change_id"]),
            provider=row["provider"],
            scopes=json.loads(row["scopes_json"]),
            issued_at=datetime.fromisoformat(row["issued_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            revoked_at=(
                datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None
            ),
        )


class ProviderOperationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self, operation: ProviderOperation
    ) -> tuple[ProviderOperation, bool]:
        """Insert one provider operation. Returns `(operation, created)`.

        `created` is `False` when `(change_id, idempotency_key)` already had
        a row; the previously stored operation is returned instead of
        raising, matching this API's idempotency-key replay behavior.
        """

        try:
            with self.database.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO provider_operations (
                        id, change_id, status, idempotency_key, payload_json,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(operation.id),
                        str(operation.request.change_id),
                        operation.status.value,
                        operation.request.idempotency_key,
                        operation.model_dump_json(),
                        operation.started_at.isoformat(),
                        operation.completed_at.isoformat()
                        if operation.completed_at
                        else None,
                    ),
                )
            return operation, True
        except sqlite3.IntegrityError:
            existing = self.get_by_idempotency_key(
                operation.request.change_id, operation.request.idempotency_key
            )
            if existing is None:
                raise
            return existing, False

    def get_by_idempotency_key(
        self, change_id: UUID, idempotency_key: str
    ) -> ProviderOperation | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM provider_operations
                WHERE change_id = ? AND idempotency_key = ?
                """,
                (str(change_id), idempotency_key),
            ).fetchone()
        return ProviderOperation.model_validate_json(row["payload_json"]) if row else None

    def get_succeeded_operation(
        self, change_id: UUID, operation: str
    ) -> ProviderOperation | None:
        """The most recent SUCCEEDED operation of this kind for the Change,

        or None. Used to find the PR this Change itself created, so a
        compensation call always targets an object the Change actually
        produced -- never an arbitrary caller-supplied PR number.
        """

        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json, started_at FROM provider_operations "
                "WHERE change_id = ? AND status = ? ORDER BY started_at DESC",
                (str(change_id), ProviderOperationStatus.SUCCEEDED.value),
            ).fetchall()
        for row in rows:
            candidate = ProviderOperation.model_validate_json(row["payload_json"])
            if candidate.request.operation == operation:
                return candidate
        return None

    def has_succeeded_operation(self, change_id: UUID, operation: str) -> bool:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM provider_operations WHERE change_id = ? AND status = ?",
                (str(change_id), ProviderOperationStatus.SUCCEEDED.value),
            ).fetchall()
        return any(
            ProviderOperation.model_validate_json(row["payload_json"]).request.operation
            == operation
            for row in rows
        )


class OutcomeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, outcome: Outcome) -> Outcome:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO outcomes (
                    id, change_id, kind, status, head_sha, payload_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(outcome.id),
                    str(outcome.change_id),
                    outcome.kind.value,
                    outcome.status.value,
                    outcome.head_sha,
                    outcome.model_dump_json(),
                    outcome.observed_at.isoformat(),
                ),
            )
        return outcome

    def list_for_change(self, change_id: UUID) -> list[Outcome]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM outcomes WHERE change_id = ? ORDER BY observed_at DESC",
                (str(change_id),),
            ).fetchall()
        return [Outcome.model_validate_json(row["payload_json"]) for row in rows]


class RecoveryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_plan(
        self, plan: RecoveryPlan, *, connection: sqlite3.Connection | None = None
    ) -> RecoveryPlan:
        with self.database.connection_or(connection) as conn:
            conn.execute(
                """
                INSERT INTO recovery_plans (
                    id, change_id, status, payload_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(plan.id),
                    str(plan.change_id),
                    plan.status.value,
                    plan.model_dump_json(),
                    plan.created_at.isoformat(),
                    plan.completed_at.isoformat() if plan.completed_at else None,
                ),
            )
            self._replace_actions(conn, plan)
        return plan

    def update_plan(
        self, plan: RecoveryPlan, *, connection: sqlite3.Connection | None = None
    ) -> RecoveryPlan:
        with self.database.connection_or(connection) as conn:
            conn.execute(
                """
                UPDATE recovery_plans
                SET status = ?, payload_json = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    plan.status.value,
                    plan.model_dump_json(),
                    plan.completed_at.isoformat() if plan.completed_at else None,
                    str(plan.id),
                ),
            )
            self._replace_actions(conn, plan)
        return plan

    @staticmethod
    def _replace_actions(connection: sqlite3.Connection, plan: RecoveryPlan) -> None:
        connection.execute(
            "DELETE FROM recovery_actions WHERE plan_id = ?", (str(plan.id),)
        )
        for action in plan.actions:
            connection.execute(
                """
                INSERT INTO recovery_actions (
                    id, change_id, plan_id, status, payload_json, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(action.id),
                    str(plan.change_id),
                    str(plan.id),
                    "SUPPORTED" if action.supported else "UNSUPPORTED",
                    action.model_dump_json(),
                    plan.created_at.isoformat(),
                    plan.completed_at.isoformat() if plan.completed_at else None,
                ),
            )

    def get(self, plan_id: UUID) -> RecoveryPlan | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM recovery_plans WHERE id = ?", (str(plan_id),)
            ).fetchone()
        return RecoveryPlan.model_validate_json(row["payload_json"]) if row else None

    def latest_for_change(self, change_id: UUID) -> RecoveryPlan | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM recovery_plans
                WHERE change_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (str(change_id),),
            ).fetchone()
        return RecoveryPlan.model_validate_json(row["payload_json"]) if row else None


class PassportRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, passport: ChangePassport) -> ChangePassport:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO change_passports (
                    id, change_id, schema_version, canonical_digest, payload_json, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(passport.id),
                    str(passport.change_id),
                    passport.schema_version,
                    passport.canonical_digest,
                    passport.model_dump_json(),
                    passport.generated_at.isoformat(),
                ),
            )
        return passport

    def latest_for_change(self, change_id: UUID) -> ChangePassport | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM change_passports
                WHERE change_id = ? ORDER BY generated_at DESC LIMIT 1
                """,
                (str(change_id),),
            ).fetchone()
        return ChangePassport.model_validate_json(row["payload_json"]) if row else None


__all__ = [
    "CredentialGrantRepository",
    "ProviderOperationRepository",
    "OutcomeRepository",
    "RecoveryRepository",
    "PassportRepository",
]
