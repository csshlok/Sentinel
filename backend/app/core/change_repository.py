"""Parameterized persistence for the latest state of each Change."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.app.contracts.models import GitSummary, VerificationResult
from backend.app.core.database import Database


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


class ChangeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, change: StoredChange) -> StoredChange:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO changes (
                    id, title, intent, repository_path, created_at, updated_at,
                    last_refreshed_at, git_summary_json, verification_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._to_values(change),
            )
        return change

    def get(self, change_id: UUID) -> StoredChange | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM changes WHERE id = ?", (str(change_id),)
            ).fetchone()
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

    def update_git_summary(
        self, change_id: UUID, summary: GitSummary, updated_at: datetime
    ) -> StoredChange | None:
        payload = json.dumps(summary.model_dump(mode="json"), separators=(",", ":"))
        with self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE changes
                SET git_summary_json = ?,
                    verification_json = NULL,
                    last_refreshed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload,
                    summary.refreshed_at.isoformat(),
                    updated_at.isoformat(),
                    str(change_id),
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(change_id)

    def update_verification(
        self, change_id: UUID, result: VerificationResult, updated_at: datetime
    ) -> StoredChange | None:
        payload = json.dumps(result.model_dump(mode="json"), separators=(",", ":"))
        with self.database.connection() as connection:
            cursor = connection.execute(
                """
                UPDATE changes
                SET verification_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (payload, updated_at.isoformat(), str(change_id)),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(change_id)

    def delete(self, change_id: UUID) -> bool:
        with self.database.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM changes WHERE id = ?", (str(change_id),)
            )
        return cursor.rowcount > 0

    @staticmethod
    def _to_values(change: StoredChange) -> tuple[str | None, ...]:
        return (
            str(change.id),
            change.title,
            change.intent,
            change.repository_path,
            change.created_at.isoformat(),
            change.updated_at.isoformat(),
            change.last_refreshed_at.isoformat() if change.last_refreshed_at else None,
            json.dumps(change.git_summary.model_dump(mode="json"), separators=(",", ":"))
            if change.git_summary
            else None,
            json.dumps(change.verification.model_dump(mode="json"), separators=(",", ":"))
            if change.verification
            else None,
        )

    @staticmethod
    def _from_row(row: object) -> StoredChange:
        git_payload = row["git_summary_json"]  # type: ignore[index]
        verification_payload = row["verification_json"]  # type: ignore[index]
        return StoredChange(
            id=UUID(row["id"]),  # type: ignore[index]
            title=row["title"],  # type: ignore[index]
            intent=row["intent"],  # type: ignore[index]
            repository_path=row["repository_path"],  # type: ignore[index]
            created_at=datetime.fromisoformat(row["created_at"]),  # type: ignore[index]
            updated_at=datetime.fromisoformat(row["updated_at"]),  # type: ignore[index]
            last_refreshed_at=datetime.fromisoformat(row["last_refreshed_at"])  # type: ignore[index]
            if row["last_refreshed_at"]  # type: ignore[index]
            else None,
            git_summary=GitSummary.model_validate_json(git_payload)
            if git_payload
            else None,
            verification=VerificationResult.model_validate_json(verification_payload)
            if verification_payload
            else None,
        )
