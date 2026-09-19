"""Additive migrations from the original Git-review schema."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass


MigrationFunction = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: MigrationFunction


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _add_column(
    connection: sqlite3.Connection, table: str, name: str, definition: str
) -> None:
    if name not in _column_names(connection, table):
        connection.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def migration_001_legacy_change_store(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS changes (
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
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_changes_created_at "
        "ON changes(created_at DESC)"
    )


def migration_002_change_runtime_core(connection: sqlite3.Connection) -> None:
    _add_column(
        connection, "changes", "lifecycle_state", "TEXT NOT NULL DEFAULT 'DRAFT'"
    )
    _add_column(connection, "changes", "revision", "INTEGER NOT NULL DEFAULT 1")
    _add_column(connection, "changes", "contract_json", "TEXT NULL")
    _add_column(
        connection, "changes", "risk_level", "TEXT NOT NULL DEFAULT 'UNKNOWN'"
    )
    _add_column(
        connection, "changes", "evidence_revision", "INTEGER NOT NULL DEFAULT 0"
    )
    _add_column(
        connection, "changes", "verification_evidence_revision", "INTEGER NULL"
    )
    _add_column(connection, "changes", "last_transition_at", "TEXT NULL")

    statements = (
        """
        CREATE TABLE IF NOT EXISTS idempotency_records (
            scope TEXT NOT NULL,
            key TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (scope, key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS actors (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            display_name TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS delegations (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            grantor_id TEXT NOT NULL,
            grantee_id TEXT NOT NULL,
            repository_path TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT NULL,
            use_limit INTEGER NULL,
            uses INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS git_checkpoints (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            head_sha TEXT NOT NULL,
            evidence_revision INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            captured_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS environment_passports (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            payload_json TEXT NOT NULL,
            captured_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS dependency_reports (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            checkpoint_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            captured_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assurance_plans (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            checkpoint_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assurance_runs (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            plan_id TEXT NOT NULL,
            checkpoint_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS credential_grants (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            actor_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS provider_operations (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT NULL,
            UNIQUE (change_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            head_sha TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            observed_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS recovery_plans (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS recovery_actions (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            plan_id TEXT NOT NULL REFERENCES recovery_plans(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS change_passports (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            schema_version INTEGER NOT NULL,
            canonical_digest TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL
        )
        """,
    )
    for statement in statements:
        connection.execute(statement)

    indexes = (
        "CREATE INDEX IF NOT EXISTS idx_changes_state ON changes(lifecycle_state)",
        "CREATE INDEX IF NOT EXISTS idx_delegations_change ON delegations(change_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_change ON agent_runs(change_id)",
        "CREATE INDEX IF NOT EXISTS idx_git_checkpoints_change ON git_checkpoints(change_id, evidence_revision)",
        "CREATE INDEX IF NOT EXISTS idx_environment_passports_change ON environment_passports(change_id, captured_at)",
        "CREATE INDEX IF NOT EXISTS idx_assurance_runs_change ON assurance_runs(change_id, completed_at)",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_change ON outcomes(change_id, observed_at)",
        "CREATE INDEX IF NOT EXISTS idx_recovery_plans_change ON recovery_plans(change_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_change_passports_change ON change_passports(change_id, generated_at)",
    )
    for statement in indexes:
        connection.execute(statement)


def migration_003_event_effect_journal(connection: sqlite3.Connection) -> None:
    """Append-only, hash-chained Event/Effect Journal.

    See `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` Part A. Application code
    never issues UPDATE/DELETE against these tables; the triggers below
    enforce that as a real, testable constraint (defense in depth), not a
    comment.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_events (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor_id TEXT NULL,
            subject_type TEXT NULL,
            subject_id TEXT NULL,
            payload_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            prev_event_hash TEXT NULL,
            event_hash TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            UNIQUE (change_id, seq)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_events_change "
        "ON journal_events(change_id, seq)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_events_type "
        "ON journal_events(change_id, event_type)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_effects (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES journal_events(id) ON DELETE CASCADE,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            before_digest TEXT NULL,
            produced_digest TEXT NULL,
            restoration_class TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_journal_effects_change "
        "ON journal_effects(change_id, resource_type)"
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS journal_events_immutable_update
        BEFORE UPDATE ON journal_events
        BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS journal_events_immutable_delete
        BEFORE DELETE ON journal_events
        BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS journal_effects_immutable_update
        BEFORE UPDATE ON journal_effects
        BEGIN SELECT RAISE(ABORT, 'journal_effects is append-only'); END
        """
    )
    connection.execute(
        """
        CREATE TRIGGER IF NOT EXISTS journal_effects_immutable_delete
        BEFORE DELETE ON journal_effects
        BEGIN SELECT RAISE(ABORT, 'journal_effects is append-only'); END
        """
    )


def migration_004_tool_registry(connection: sqlite3.Connection) -> None:
    """Tool Registry + supply-chain trust tables. See plan Part B.

    Applied after migration 3: `tool.manifest.registered` / `tool.trust.decided`
    / `tool.trust.invalidated` are journal event types, so `journal_events`
    must exist first.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_manifests (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            publisher TEXT NULL,
            source TEXT NOT NULL,
            artifact_digest TEXT NOT NULL,
            signature_state TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            filesystem_scope_json TEXT NOT NULL,
            network_scope_json TEXT NOT NULL,
            credential_requirements_json TEXT NOT NULL,
            trust_state TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE (name, version, artifact_digest)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_trust_decisions (
            id TEXT PRIMARY KEY,
            tool_id TEXT NOT NULL REFERENCES tool_manifests(id) ON DELETE CASCADE,
            change_id TEXT NULL REFERENCES changes(id) ON DELETE CASCADE,
            decided_by_actor_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            scope TEXT NOT NULL,
            reason TEXT NULL,
            snapshot_json TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            invalidated_at TEXT NULL,
            invalidation_reason TEXT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_trust_decisions_tool "
        "ON tool_trust_decisions(tool_id, decided_at)"
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_observations (
            id TEXT PRIMARY KEY,
            tool_id TEXT NOT NULL REFERENCES tool_manifests(id) ON DELETE CASCADE,
            change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
            agent_run_id TEXT NULL,
            observed_at TEXT NOT NULL,
            capabilities_observed_json TEXT NOT NULL,
            context TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_observations_change "
        "ON tool_observations(change_id, observed_at)"
    )


MIGRATIONS = (
    Migration(1, "legacy_change_store", migration_001_legacy_change_store),
    Migration(2, "change_runtime_core", migration_002_change_runtime_core),
    Migration(3, "event_effect_journal", migration_003_event_effect_journal),
    Migration(4, "tool_registry", migration_004_tool_registry),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
