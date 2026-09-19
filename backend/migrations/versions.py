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


def migration_005_journal_cascade_delete_fix(connection: sqlite3.Connection) -> None:
    """Fix migration 3's DELETE triggers to allow the FK cascade they broke.

    `journal_events.change_id` / `journal_effects.change_id` /
    `journal_effects.event_id` all use `ON DELETE CASCADE`, and
    `ChangeRepository.delete` relies on that cascade (A.4: "Change metadata
    deletion in this product already means delete this Change's evidence").
    Discovered only once a real end-to-end delete flow was exercised: SQLite
    fires a child table's own DELETE triggers for rows removed by a foreign
    key cascade action, exactly as it would for a direct `DELETE` statement --
    so migration 3's unconditional `BEFORE DELETE ... RAISE(ABORT)` triggers
    also aborted the legitimate cascade, not just direct tampering.

    The fix: a `WHEN` guard that only aborts when the row's own parent Change
    still exists. A direct `DELETE FROM journal_events WHERE ...` against a
    live Change is still rejected exactly as before (empirically verified);
    only a delete that is *itself* part of that Change's own cascade --
    which, by the time SQLite processes it, has already removed the parent
    `changes` row -- is allowed through. This is additive per this codebase's
    migration convention: migration 3 is not edited, its triggers are
    replaced by a later migration, the same way a bug found in shipped SQL
    would be patched forward in any real system.
    """

    connection.execute("DROP TRIGGER IF EXISTS journal_events_immutable_delete")
    connection.execute(
        """
        CREATE TRIGGER journal_events_immutable_delete
        BEFORE DELETE ON journal_events
        WHEN EXISTS (SELECT 1 FROM changes WHERE id = OLD.change_id)
        BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END
        """
    )
    connection.execute("DROP TRIGGER IF EXISTS journal_effects_immutable_delete")
    connection.execute(
        """
        CREATE TRIGGER journal_effects_immutable_delete
        BEFORE DELETE ON journal_effects
        WHEN EXISTS (SELECT 1 FROM changes WHERE id = OLD.change_id)
        BEGIN SELECT RAISE(ABORT, 'journal_effects is append-only'); END
        """
    )


def migration_006_change_deletion_log(connection: sqlite3.Connection) -> None:
    """Threat model finding #3: Change deletion destroys the whole journal.

    `journal_events`/`journal_effects` cascade on `changes` deletion (by
    design -- migration 5's own docstring quotes A.4: "Change metadata
    deletion in this product already means delete this Change's evidence").
    That means the CHANGE_DELETED marker event the deletion flow already
    emits is itself wiped by the same cascade it describes, and no
    Change-independent record survives that a deletion ever happened at
    all -- not even a hash proving what the chain looked like at the
    moment of deletion.

    `change_deletion_log` has no foreign key to `changes`, so it is never
    touched by that cascade. `ChangeRepository.delete` (core, not this
    migration) writes one row here, in the same transaction as the delete,
    capturing the journal's last committed event hash/seq/count *before*
    the cascade removes the rows those numbers describe -- a durable,
    independently-checkable fact that a Change with N journaled events,
    ending at a specific hash, was deleted at a specific time, even though
    the events themselves are gone with it.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS change_deletion_log (
            id TEXT PRIMARY KEY,
            change_id TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            journal_event_count INTEGER NOT NULL,
            last_event_seq INTEGER NULL,
            last_event_hash TEXT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_change_deletion_log_change "
        "ON change_deletion_log(change_id)"
    )


def migration_007_tool_manifest_resolved_path(connection: sqlite3.Connection) -> None:
    """Threat model finding #9: tool identity collision via (name, version).

    resolve_or_register looked up an existing manifest by
    `WHERE name = ? AND version = ?` alone -- looser than the schema's own
    `UNIQUE(name, version, artifact_digest)` constraint. Since `name` is
    just `Path(executable_path).stem.lower()` (e.g. two completely
    unrelated binaries both named `tool.exe` in different directories both
    become name="tool"), two different executables sharing a filename stem
    collapsed onto the same manifest row: resolving the second one silently
    overwrote the first's artifact_digest in place, and any prior trust
    decision on that row would (via check_drift) read as "drifted", or
    worse, an APPROVED decision for tool A could survive as an apparently
    -unrelated-but-same-row manifest that is actually tool B's binary.

    `resolved_path` (the exact resolved executable/manifest path the
    identity was registered from) becomes part of the lookup key, so two
    different paths -- however similarly named -- can never collide onto
    one row. This is additive and does not touch drift semantics at all:
    the *same* path, name, and version still update the same row in place
    exactly as before (which is what check_drift's digest comparison
    depends on); only genuinely different artifacts now get their own rows.
    """

    connection.execute(
        "ALTER TABLE tool_manifests ADD COLUMN resolved_path TEXT NOT NULL DEFAULT ''"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_manifests_identity "
        "ON tool_manifests(name, version, resolved_path)"
    )


def migration_008_agent_run_pause_fields(connection: sqlite3.Connection) -> None:
    """`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A: agent pause/resume.

    `AgentRun.paused_at`/`resumed_at` are stored in the existing JSON run
    payload (same place `stdout`/`stderr`/`limitations` already live), not
    in a dedicated column -- the run row's shape has always been a JSON blob
    keyed by run id, so no column addition is needed. This migration is a
    changelog entry only, matching the "no-op" precedent already established
    for pure-application-layer additions: it exists so schema version history
    stays a complete, honest record of every behavior-affecting change, even
    ones that touch no table.
    """

    del connection  # no schema change


def migration_009_change_fork_columns(connection: sqlite3.Connection) -> None:
    """`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part B: checkpoint forking.

    `forked_from_change_id`/`forked_from_checkpoint_id` record which Change
    and checkpoint a fork was created from. Both are nullable (most Changes
    are not forks) and `ON DELETE SET NULL` so deleting the source Change or
    checkpoint later never blocks or cascades into deleting the fork itself
    -- the fork's own evidence was already copied into its own rows at fork
    time (see `ChangeService.fork`), so these columns are provenance only,
    not a data dependency.
    """

    _add_column(
        connection,
        "changes",
        "forked_from_change_id",
        "TEXT NULL REFERENCES changes(id) ON DELETE SET NULL",
    )
    _add_column(
        connection,
        "changes",
        "forked_from_checkpoint_id",
        "TEXT NULL REFERENCES git_checkpoints(id) ON DELETE SET NULL",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_changes_forked_from "
        "ON changes(forked_from_change_id)"
    )


MIGRATIONS = (
    Migration(1, "legacy_change_store", migration_001_legacy_change_store),
    Migration(2, "change_runtime_core", migration_002_change_runtime_core),
    Migration(3, "event_effect_journal", migration_003_event_effect_journal),
    Migration(4, "tool_registry", migration_004_tool_registry),
    Migration(5, "journal_cascade_delete_fix", migration_005_journal_cascade_delete_fix),
    Migration(6, "change_deletion_log", migration_006_change_deletion_log),
    Migration(7, "tool_manifest_resolved_path", migration_007_tool_manifest_resolved_path),
    Migration(8, "agent_run_pause_fields", migration_008_agent_run_pause_fields),
    Migration(9, "change_fork_columns", migration_009_change_fork_columns),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
