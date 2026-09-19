"""Transactional Change persistence with optimistic concurrency and idempotency."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from backend.app.contracts.models import (
    ChangeContract,
    ChangeLifecycleState,
    GitSummary,
    RiskLevel,
    VerificationResult,
)
from backend.app.core.database import Database
from backend.app.core.errors import idempotency_conflict, revision_conflict


_INVALIDATED_BY_NEW_GIT = frozenset(
    {
        ChangeLifecycleState.LOCALLY_VERIFIED,
        ChangeLifecycleState.REVIEW_READY,
        ChangeLifecycleState.PR_OPEN,
        ChangeLifecycleState.CI_VERIFIED,
        ChangeLifecycleState.ARTIFACT_BUILT,
        ChangeLifecycleState.DEPLOYED,
        ChangeLifecycleState.OBSERVING,
        ChangeLifecycleState.STABLE,
    }
)


@dataclass(frozen=True, slots=True)
class StoredChange:
    id: UUID
    title: str
    intent: str
    repository_path: str
    created_at: datetime
    updated_at: datetime
    last_refreshed_at: datetime | None
    git_summary: GitSummary | None
    verification: VerificationResult | None
    lifecycle_state: ChangeLifecycleState = ChangeLifecycleState.DRAFT
    revision: int = 1
    contract: ChangeContract = ChangeContract()
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    evidence_revision: int = 0
    verification_evidence_revision: int | None = None
    last_transition_at: datetime | None = None


class ChangeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        change: StoredChange,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> StoredChange:
        scope = "changes:create"
        with self.database.connection(immediate=True) as connection:
            replay = self._replay_change(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            connection.execute(
                """
                INSERT INTO changes (
                    id, title, intent, repository_path, created_at, updated_at,
                    last_refreshed_at, git_summary_json, verification_json,
                    lifecycle_state, revision, contract_json, risk_level,
                    evidence_revision, verification_evidence_revision,
                    last_transition_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._to_values(change),
            )
            self._record_change_result(
                connection, scope, idempotency_key, request_hash, change
            )
        return change

    def get(self, change_id: UUID) -> StoredChange | None:
        with self.database.connection() as connection:
            row = self._select(connection, change_id)
        return self._from_row(row) if row is not None else None

    def list(self, *, limit: int = 100, offset: int = 0) -> list[StoredChange]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM changes
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def update_contract(
        self,
        change_id: UUID,
        contract: ChangeContract,
        expected_revision: int,
        updated_at: datetime,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> StoredChange | None:
        scope = f"change:{change_id}:contract"
        with self.database.connection(immediate=True) as connection:
            replay = self._replay_change(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            row = self._select(connection, change_id)
            if row is None:
                return None
            current = self._from_row(row)
            self._check_revision(current, expected_revision)
            connection.execute(
                """
                UPDATE changes
                SET contract_json = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    self._model_json(contract),
                    updated_at.isoformat(),
                    str(change_id),
                    expected_revision,
                ),
            )
            updated = self._require_selected(connection, change_id)
            self._record_change_result(
                connection, scope, idempotency_key, request_hash, updated
            )
            return updated

    def transition(
        self,
        change_id: UUID,
        target: ChangeLifecycleState,
        expected_revision: int,
        updated_at: datetime,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> StoredChange | None:
        scope = f"change:{change_id}:transition"
        with self.database.connection(immediate=True) as connection:
            replay = self._replay_change(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            row = self._select(connection, change_id)
            if row is None:
                return None
            current = self._from_row(row)
            self._check_revision(current, expected_revision)
            if current.lifecycle_state is target:
                self._record_change_result(
                    connection, scope, idempotency_key, request_hash, current
                )
                return current
            connection.execute(
                """
                UPDATE changes
                SET lifecycle_state = ?, revision = revision + 1,
                    updated_at = ?, last_transition_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    target.value,
                    updated_at.isoformat(),
                    updated_at.isoformat(),
                    str(change_id),
                    expected_revision,
                ),
            )
            updated = self._require_selected(connection, change_id)
            self._record_change_result(
                connection, scope, idempotency_key, request_hash, updated
            )
            return updated

    def update_git_summary(
        self,
        change_id: UUID,
        summary: GitSummary,
        updated_at: datetime,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> StoredChange | None:
        scope = f"change:{change_id}:legacy-git-refresh"
        with self.database.connection(immediate=True) as connection:
            replay = self._replay_change(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            row = self._select(connection, change_id)
            if row is None:
                return None
            current = self._from_row(row)
            lifecycle = (
                ChangeLifecycleState.ACTIVE
                if current.lifecycle_state in _INVALIDATED_BY_NEW_GIT
                else current.lifecycle_state
            )
            transition_time = (
                updated_at.isoformat()
                if lifecycle is not current.lifecycle_state
                else (
                    current.last_transition_at.isoformat()
                    if current.last_transition_at
                    else None
                )
            )
            connection.execute(
                """
                UPDATE changes
                SET git_summary_json = ?, verification_json = NULL,
                    verification_evidence_revision = NULL,
                    evidence_revision = evidence_revision + 1,
                    lifecycle_state = ?, last_transition_at = ?,
                    last_refreshed_at = ?, updated_at = ?, revision = revision + 1
                WHERE id = ?
                """,
                (
                    self._model_json(summary),
                    lifecycle.value,
                    transition_time,
                    summary.refreshed_at.isoformat(),
                    updated_at.isoformat(),
                    str(change_id),
                ),
            )
            updated = self._require_selected(connection, change_id)
            self._record_change_result(
                connection, scope, idempotency_key, request_hash, updated
            )
            return updated

    def update_verification(
        self,
        change_id: UUID,
        result: VerificationResult,
        updated_at: datetime,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> StoredChange | None:
        scope = f"change:{change_id}:legacy-verification"
        with self.database.connection(immediate=True) as connection:
            replay = self._replay_change(
                connection, scope, idempotency_key, request_hash
            )
            if replay is not None:
                return replay
            row = self._select(connection, change_id)
            if row is None:
                return None
            connection.execute(
                """
                UPDATE changes
                SET verification_json = ?,
                    verification_evidence_revision = evidence_revision,
                    updated_at = ?, revision = revision + 1
                WHERE id = ?
                """,
                (self._model_json(result), updated_at.isoformat(), str(change_id)),
            )
            updated = self._require_selected(connection, change_id)
            self._record_change_result(
                connection, scope, idempotency_key, request_hash, updated
            )
            return updated

    def replay(
        self, scope: str, idempotency_key: str | None, request_hash: str | None
    ) -> StoredChange | bool | None:
        if idempotency_key is None:
            return None
        with self.database.connection() as connection:
            envelope = self._replay_envelope(
                connection, scope, idempotency_key, request_hash
            )
        if envelope is None:
            return None
        if envelope["kind"] == "deleted":
            return True
        return self._stored_from_payload(envelope["value"])

    def delete(
        self,
        change_id: UUID,
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
    ) -> bool:
        scope = f"change:{change_id}:delete"
        with self.database.connection(immediate=True) as connection:
            envelope = self._replay_envelope(
                connection, scope, idempotency_key, request_hash
            )
            if envelope is not None:
                return envelope["kind"] == "deleted"
            cursor = connection.execute(
                "DELETE FROM changes WHERE id = ?", (str(change_id),)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                self._record_envelope(
                    connection,
                    scope,
                    idempotency_key,
                    request_hash,
                    {"kind": "deleted", "value": True},
                )
            return deleted

    @staticmethod
    def _select(
        connection: sqlite3.Connection, change_id: UUID
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM changes WHERE id = ?", (str(change_id),)
        ).fetchone()

    def _require_selected(
        self, connection: sqlite3.Connection, change_id: UUID
    ) -> StoredChange:
        row = self._select(connection, change_id)
        if row is None:
            raise RuntimeError("Change disappeared during a transaction")
        return self._from_row(row)

    @staticmethod
    def _check_revision(change: StoredChange, expected: int) -> None:
        if change.revision != expected:
            raise revision_conflict(expected=expected, actual=change.revision)

    def _replay_change(
        self,
        connection: sqlite3.Connection,
        scope: str,
        key: str | None,
        request_hash: str | None,
    ) -> StoredChange | None:
        envelope = self._replay_envelope(connection, scope, key, request_hash)
        if envelope is None:
            return None
        if envelope["kind"] != "change":
            raise RuntimeError("Idempotency result kind does not match operation")
        return self._stored_from_payload(envelope["value"])

    @staticmethod
    def _replay_envelope(
        connection: sqlite3.Connection,
        scope: str,
        key: str | None,
        request_hash: str | None,
    ) -> dict[str, Any] | None:
        if key is None:
            return None
        if request_hash is None:
            raise ValueError("request_hash is required with an idempotency key")
        row = connection.execute(
            """
            SELECT request_hash, result_json
            FROM idempotency_records
            WHERE scope = ? AND key = ?
            """,
            (scope, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise idempotency_conflict(scope)
        return json.loads(row["result_json"])

    def _record_change_result(
        self,
        connection: sqlite3.Connection,
        scope: str,
        key: str | None,
        request_hash: str | None,
        change: StoredChange,
    ) -> None:
        self._record_envelope(
            connection,
            scope,
            key,
            request_hash,
            {"kind": "change", "value": self._stored_to_payload(change)},
        )

    @staticmethod
    def _record_envelope(
        connection: sqlite3.Connection,
        scope: str,
        key: str | None,
        request_hash: str | None,
        envelope: dict[str, Any],
    ) -> None:
        if key is None:
            return
        if request_hash is None:
            raise ValueError("request_hash is required with an idempotency key")
        connection.execute(
            """
            INSERT INTO idempotency_records (
                scope, key, request_hash, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                scope,
                key,
                request_hash,
                json.dumps(envelope, separators=(",", ":"), sort_keys=True),
                datetime.now(UTC).isoformat(),
            ),
        )

    @staticmethod
    def _model_json(model: Any) -> str:
        return json.dumps(model.model_dump(mode="json"), separators=(",", ":"))

    @classmethod
    def _to_values(cls, change: StoredChange) -> tuple[str | int | None, ...]:
        return (
            str(change.id),
            change.title,
            change.intent,
            change.repository_path,
            change.created_at.isoformat(),
            change.updated_at.isoformat(),
            change.last_refreshed_at.isoformat() if change.last_refreshed_at else None,
            cls._model_json(change.git_summary) if change.git_summary else None,
            cls._model_json(change.verification) if change.verification else None,
            change.lifecycle_state.value,
            change.revision,
            cls._model_json(change.contract),
            change.risk_level.value,
            change.evidence_revision,
            change.verification_evidence_revision,
            change.last_transition_at.isoformat() if change.last_transition_at else None,
        )

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> StoredChange:
        git_payload = row["git_summary_json"]
        verification_payload = row["verification_json"]
        contract_payload = row["contract_json"]
        return StoredChange(
            id=UUID(row["id"]),
            title=row["title"],
            intent=row["intent"],
            repository_path=row["repository_path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_refreshed_at=(
                datetime.fromisoformat(row["last_refreshed_at"])
                if row["last_refreshed_at"]
                else None
            ),
            git_summary=(
                GitSummary.model_validate_json(git_payload) if git_payload else None
            ),
            verification=(
                VerificationResult.model_validate_json(verification_payload)
                if verification_payload
                else None
            ),
            lifecycle_state=ChangeLifecycleState(row["lifecycle_state"]),
            revision=int(row["revision"]),
            contract=(
                ChangeContract.model_validate_json(contract_payload)
                if contract_payload
                else ChangeContract()
            ),
            risk_level=RiskLevel(row["risk_level"]),
            evidence_revision=int(row["evidence_revision"]),
            verification_evidence_revision=(
                int(row["verification_evidence_revision"])
                if row["verification_evidence_revision"] is not None
                else None
            ),
            last_transition_at=(
                datetime.fromisoformat(row["last_transition_at"])
                if row["last_transition_at"]
                else None
            ),
        )

    @classmethod
    def _stored_to_payload(cls, change: StoredChange) -> dict[str, Any]:
        return {
            "id": str(change.id),
            "title": change.title,
            "intent": change.intent,
            "repository_path": change.repository_path,
            "created_at": change.created_at.isoformat(),
            "updated_at": change.updated_at.isoformat(),
            "last_refreshed_at": (
                change.last_refreshed_at.isoformat()
                if change.last_refreshed_at
                else None
            ),
            "git_summary": (
                change.git_summary.model_dump(mode="json")
                if change.git_summary
                else None
            ),
            "verification": (
                change.verification.model_dump(mode="json")
                if change.verification
                else None
            ),
            "lifecycle_state": change.lifecycle_state.value,
            "revision": change.revision,
            "contract": change.contract.model_dump(mode="json"),
            "risk_level": change.risk_level.value,
            "evidence_revision": change.evidence_revision,
            "verification_evidence_revision": change.verification_evidence_revision,
            "last_transition_at": (
                change.last_transition_at.isoformat()
                if change.last_transition_at
                else None
            ),
        }

    @staticmethod
    def _stored_from_payload(payload: dict[str, Any]) -> StoredChange:
        return StoredChange(
            id=UUID(payload["id"]),
            title=payload["title"],
            intent=payload["intent"],
            repository_path=payload["repository_path"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            last_refreshed_at=(
                datetime.fromisoformat(payload["last_refreshed_at"])
                if payload["last_refreshed_at"]
                else None
            ),
            git_summary=(
                GitSummary.model_validate(payload["git_summary"])
                if payload["git_summary"]
                else None
            ),
            verification=(
                VerificationResult.model_validate(payload["verification"])
                if payload["verification"]
                else None
            ),
            lifecycle_state=ChangeLifecycleState(payload["lifecycle_state"]),
            revision=int(payload["revision"]),
            contract=ChangeContract.model_validate(payload["contract"]),
            risk_level=RiskLevel(payload["risk_level"]),
            evidence_revision=int(payload["evidence_revision"]),
            verification_evidence_revision=payload["verification_evidence_revision"],
            last_transition_at=(
                datetime.fromisoformat(payload["last_transition_at"])
                if payload["last_transition_at"]
                else None
            ),
        )
