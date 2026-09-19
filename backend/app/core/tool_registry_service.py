"""Tool Registry + supply-chain trust: implements `ToolRegistryPort`.

See EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md Part B for the full design and
its bounded scope (B.1): this governs only the top-level executable
`AgentLauncherPort` resolves and explicitly declared tool/MCP manifests. It
does not intercept, observe, or attribute a specific tool call made by a
running agent process -- that would require the still-cut process
supervisor.

`[SD]`-owned shared core, per C.2: storage, drift computation, and trust-
decision bookkeeping are orchestration, not domain-specific behavior.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    DriftReport,
    JournalEventType,
    ToolManifest,
    ToolObservation,
    ToolObservationContext,
    ToolSignatureState,
    ToolTrustDecision,
    ToolTrustDecisionKind,
    ToolTrustScope,
    ToolTrustState,
    utc_now,
)
from backend.app.core.database import Database
from backend.app.core.errors import tool_executable_unreadable, tool_not_found
from backend.app.core.journal import JournalWriter

MAX_ARTIFACT_BYTES = 256 * 1_048_576

# A callable that inspects a file and returns a `ToolSignatureState` value
# ("valid" | "invalid" | "unsigned" | "unknown"). Defaults to always
# "unknown" here in T0; T1 injects the real Windows-Authenticode check from
# `execution/signature.py`, following the same optional-collaborator
# dependency-injection pattern already used everywhere else in this codebase
# (e.g. `EvidenceService(git_state=..., launcher=...)`).
SignatureChecker = Callable[[str], str]


def _default_signature_checker(_executable_path: str) -> str:
    return ToolSignatureState.UNKNOWN.value


class ToolRegistryService:
    """Implements `ToolRegistryPort`."""

    def __init__(
        self,
        database: Database,
        *,
        journal: JournalWriter | None = None,
        signature_checker: SignatureChecker | None = None,
    ) -> None:
        self.database = database
        self._journal = journal
        self._signature_checker = signature_checker or _default_signature_checker

    # -- port ---------------------------------------------------------------

    def resolve_or_register(self, executable_path: str, *, source: str) -> ToolManifest:
        digest = self._digest_file(executable_path)
        name = Path(executable_path).stem.lower() or "tool"
        version = "unknown"  # a bare executable's semantic version cannot be
        # derived without executing it, which is out of scope for a
        # read-only collector; declared manifests may carry a real version
        # once §B.1's "declared_manifest" registration path is exercised.
        now = utc_now()
        with self.database.connection(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM tool_manifests WHERE name = ? AND version = ?",
                (name, version),
            ).fetchone()
            if row is None:
                tool_id = uuid4()
                signature_state = ToolSignatureState(self._signature_checker(executable_path))
                connection.execute(
                    """
                    INSERT INTO tool_manifests (
                        id, name, version, publisher, source, artifact_digest,
                        signature_state, capabilities_json, filesystem_scope_json,
                        network_scope_json, credential_requirements_json,
                        trust_state, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(tool_id), name, version, source, digest, signature_state.value,
                        "[]", "[]", "[]", "[]",
                        ToolTrustState.OBSERVED.value, now.isoformat(), now.isoformat(),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM tool_manifests WHERE id = ?", (str(tool_id),)
                ).fetchone()
            else:
                connection.execute(
                    "UPDATE tool_manifests SET artifact_digest = ?, last_seen_at = ? WHERE id = ?",
                    (digest, now.isoformat(), row["id"]),
                )
                row = connection.execute(
                    "SELECT * FROM tool_manifests WHERE id = ?", (row["id"],)
                ).fetchone()
        return self._row_to_manifest(row)

    def get(self, tool_id: UUID) -> ToolManifest:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM tool_manifests WHERE id = ?", (str(tool_id),)
            ).fetchone()
        if row is None:
            raise tool_not_found(str(tool_id))
        return self._row_to_manifest(row)

    def list(self) -> list[ToolManifest]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_manifests ORDER BY last_seen_at DESC"
            ).fetchall()
        return [self._row_to_manifest(row) for row in rows]

    def list_for_change(self, change_id: UUID) -> list[ToolManifest]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT m.* FROM tool_manifests m
                JOIN tool_observations o ON o.tool_id = m.id
                WHERE o.change_id = ?
                ORDER BY m.last_seen_at DESC
                """,
                (str(change_id),),
            ).fetchall()
        return [self._row_to_manifest(row) for row in rows]

    def record_observation(
        self,
        tool_id: UUID,
        change_id: UUID,
        agent_run_id: UUID | None,
        capabilities_observed: list[str],
        context: str,
    ) -> ToolObservation:
        manifest = self.get(tool_id)
        observation = ToolObservation(
            id=uuid4(), tool_id=tool_id, change_id=change_id, agent_run_id=agent_run_id,
            observed_at=utc_now(), capabilities_observed=list(capabilities_observed),
            context=ToolObservationContext(context),
        )
        with self.database.connection(immediate=True) as connection:
            is_first_observation = connection.execute(
                "SELECT 1 FROM tool_observations WHERE tool_id = ? LIMIT 1", (str(tool_id),)
            ).fetchone() is None
            connection.execute(
                """
                INSERT INTO tool_observations (
                    id, tool_id, change_id, agent_run_id, observed_at,
                    capabilities_observed_json, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(observation.id), str(tool_id), str(change_id),
                    str(agent_run_id) if agent_run_id else None,
                    observation.observed_at.isoformat(),
                    json.dumps(list(capabilities_observed), separators=(",", ":")),
                    observation.context.value,
                ),
            )
            # Capabilities actually used widen the manifest's known
            # capability set over time (B.4): a real, evidence-backed signal
            # distinct from a self-declared manifest.
            merged_capabilities = sorted(set(manifest.capabilities) | set(capabilities_observed))
            if merged_capabilities != manifest.capabilities:
                connection.execute(
                    "UPDATE tool_manifests SET capabilities_json = ? WHERE id = ?",
                    (json.dumps(merged_capabilities, separators=(",", ":")), str(tool_id)),
                )
            if is_first_observation and self._journal is not None:
                # The tool_manifests row this observation belongs to was
                # created by a resolve_or_register call with no change_id in
                # scope (tools are cross-Change; see B.3); this is the first
                # point at which a Change context exists, so the
                # tool.manifest.registered event is emitted here, against
                # the Change whose launch first observed the tool.
                self._journal.append(
                    change_id, JournalEventType.TOOL_MANIFEST_REGISTERED,
                    subject_type="tool_manifest", subject_id=tool_id,
                    payload={"name": manifest.name, "version": manifest.version,
                             "source": manifest.source, "trust_state": manifest.trust_state.value},
                    connection=connection,
                )
        return observation

    def decide_trust(
        self,
        tool_id: UUID,
        actor_id: UUID,
        decision: str,
        scope: str,
        reason: str | None,
        change_id: UUID | None,
    ) -> ToolTrustDecision:
        manifest = self.get(tool_id)
        decision_kind = ToolTrustDecisionKind(decision)
        trust_scope = ToolTrustScope(scope)
        new_state = (
            ToolTrustState.APPROVED if decision_kind is ToolTrustDecisionKind.APPROVE
            else ToolTrustState.DENIED
        )
        record = ToolTrustDecision(
            id=uuid4(), tool_id=tool_id, change_id=change_id, decided_by_actor_id=actor_id,
            decision=decision_kind, scope=trust_scope, reason=reason, decided_at=utc_now(),
        )
        snapshot = {"artifact_digest": manifest.artifact_digest, "capabilities": manifest.capabilities}
        with self.database.connection(immediate=True) as connection:
            connection.execute(
                """
                INSERT INTO tool_trust_decisions (
                    id, tool_id, change_id, decided_by_actor_id, decision, scope,
                    reason, snapshot_json, decided_at, invalidated_at, invalidation_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    str(record.id), str(tool_id), str(change_id) if change_id else None,
                    str(actor_id), decision_kind.value, trust_scope.value, reason,
                    json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
                    record.decided_at.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE tool_manifests SET trust_state = ? WHERE id = ?",
                (new_state.value, str(tool_id)),
            )
            if change_id is not None and self._journal is not None:
                # A publisher-level policy decision (change_id=None) has no
                # Change to scope a journal entry to; it is still recorded
                # durably in tool_trust_decisions, just not in the per-Change
                # journal -- an explicit, honest limitation (A.7's own
                # "the chain is scoped per Change" boundary applies here too).
                self._journal.append(
                    change_id, JournalEventType.TOOL_TRUST_DECIDED,
                    actor_id=actor_id, subject_type="tool_trust_decision", subject_id=record.id,
                    payload={"tool_id": str(tool_id), "decision": decision_kind.value,
                             "scope": trust_scope.value},
                    connection=connection,
                )
        return record

    def check_drift(self, tool_id: UUID, *, change_id: UUID | None = None) -> DriftReport:
        manifest = self.get(tool_id)
        if manifest.trust_state is not ToolTrustState.APPROVED:
            # B.5: drift only invalidates "an existing APPROVED decision".
            # Querying trust_state history for the latest non-invalidated
            # APPROVE row without checking the *current* state would let a
            # later explicit DENY be silently overridden back to PROVISIONAL
            # by a stale approval that a human has since revoked in effect --
            # a denial is not itself something drift ever loosens.
            return DriftReport(
                tool_id=tool_id, drifted=False, changed_fields=[],
                prior_trust_state=manifest.trust_state, new_trust_state=manifest.trust_state,
            )
        with self.database.connection(immediate=True) as connection:
            approved = connection.execute(
                """
                SELECT * FROM tool_trust_decisions
                WHERE tool_id = ? AND decision = 'APPROVE' AND invalidated_at IS NULL
                ORDER BY decided_at DESC LIMIT 1
                """,
                (str(tool_id),),
            ).fetchone()
            if approved is None:
                return DriftReport(
                    tool_id=tool_id, drifted=False, changed_fields=[],
                    prior_trust_state=manifest.trust_state, new_trust_state=manifest.trust_state,
                )
            snapshot = json.loads(approved["snapshot_json"])
            changed_fields: list[str] = []
            if snapshot.get("artifact_digest") != manifest.artifact_digest:
                changed_fields.append("artifact_digest")
            if sorted(snapshot.get("capabilities") or []) != sorted(manifest.capabilities):
                changed_fields.append("capabilities")
            if not changed_fields:
                return DriftReport(
                    tool_id=tool_id, drifted=False, changed_fields=[],
                    prior_trust_state=manifest.trust_state, new_trust_state=manifest.trust_state,
                )
            prior_state = manifest.trust_state
            now = utc_now()
            connection.execute(
                "UPDATE tool_trust_decisions SET invalidated_at = ?, invalidation_reason = ? "
                "WHERE id = ?",
                (now.isoformat(),
                 f"Drift detected in: {', '.join(changed_fields)}.", approved["id"]),
            )
            connection.execute(
                "UPDATE tool_manifests SET trust_state = ? WHERE id = ?",
                (ToolTrustState.PROVISIONAL.value, str(tool_id)),
            )
            if change_id is not None and self._journal is not None:
                self._journal.append(
                    change_id, JournalEventType.TOOL_TRUST_INVALIDATED,
                    subject_type="tool_trust_decision", subject_id=UUID(approved["id"]),
                    payload={"tool_id": str(tool_id), "changed_fields": changed_fields},
                    connection=connection,
                )
        return DriftReport(
            tool_id=tool_id, drifted=True, changed_fields=changed_fields,
            prior_trust_state=prior_state, new_trust_state=ToolTrustState.PROVISIONAL,
        )

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _digest_file(executable_path: str) -> str:
        path = Path(executable_path)
        try:
            size = path.stat().st_size
            if size > MAX_ARTIFACT_BYTES:
                raise tool_executable_unreadable(executable_path)
            data = path.read_bytes()
        except OSError as exc:
            raise tool_executable_unreadable(executable_path) from exc
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _row_to_manifest(row: sqlite3.Row) -> ToolManifest:
        return ToolManifest(
            id=UUID(row["id"]), name=row["name"], version=row["version"],
            publisher=row["publisher"], source=row["source"],
            artifact_digest=row["artifact_digest"],
            signature_state=ToolSignatureState(row["signature_state"]),
            capabilities=json.loads(row["capabilities_json"]),
            filesystem_scope=json.loads(row["filesystem_scope_json"]),
            network_scope=json.loads(row["network_scope_json"]),
            credential_requirements=json.loads(row["credential_requirements_json"]),
            trust_state=ToolTrustState(row["trust_state"]),
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        )
