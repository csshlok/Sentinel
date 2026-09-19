from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.contracts.models import ChangeLifecycleState, RiskLevel
from backend.app.core.change_repository import ChangeRepository
from backend.app.core.database import Database
from backend.migrations import LATEST_SCHEMA_VERSION


LEGACY_SCHEMA = """
CREATE TABLE changes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    intent TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_refreshed_at TEXT NULL,
    git_summary_json TEXT NULL,
    verification_json TEXT NULL
)
"""


def test_legacy_database_upgrades_without_losing_change(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    change_id = uuid4()
    now = datetime.now(UTC).isoformat()
    connection = sqlite3.connect(path)
    connection.execute(LEGACY_SCHEMA)
    connection.execute(
        """
        INSERT INTO changes (
            id, title, intent, repository_path, created_at, updated_at,
            last_refreshed_at, git_summary_json, verification_json
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
        """,
        (str(change_id), "Legacy", "Preserve me", "C:\\repo", now, now),
    )
    connection.commit()
    connection.close()

    database = Database(path)
    database.initialize()
    database.initialize()

    assert database.schema_version() == LATEST_SCHEMA_VERSION
    stored = ChangeRepository(database).get(change_id)
    assert stored is not None
    assert stored.title == "Legacy"
    assert stored.lifecycle_state is ChangeLifecycleState.DRAFT
    assert stored.risk_level is RiskLevel.UNKNOWN
    assert stored.revision == 1
    assert stored.evidence_revision == 0
    assert stored.contract.allowed_paths == ["**"]


def test_schema_contains_retained_entities_and_no_removed_subsystem_tables(
    tmp_path,
) -> None:
    database = Database(tmp_path / "schema.sqlite3")
    database.initialize()
    with database.connection() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "changes",
        "actors",
        "delegations",
        "agent_runs",
        "git_checkpoints",
        "environment_passports",
        "dependency_reports",
        "assurance_plans",
        "assurance_runs",
        "credential_grants",
        "provider_operations",
        "outcomes",
        "recovery_plans",
        "recovery_actions",
        "change_passports",
        "idempotency_records",
    } <= tables
    assert {
        "events",
        "effects",
        "processes",
        "resource_versions",
        "filesystem_snapshots",
        "tools",
        "replay_events",
    }.isdisjoint(tables)


def test_newer_database_version_is_rejected(tmp_path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?, ?)",
        (LATEST_SCHEMA_VERSION + 1, "future", datetime.now(UTC).isoformat()),
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer"):
        Database(path).initialize()
