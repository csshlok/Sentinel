"""Implements `backend.app.contracts.ports.PassportPort`.

The Passport is built only from frozen, persisted evidence: real rows
in the evidence tables (owned by `[SD]`'s migrations, written by `[KB]`
and `[AC]`), and real delegations. Genuinely absent evidence is never
represented by a fabricated `EvidenceReference` with an invented ID —
that would be evidence fabrication. It is instead recorded as a plain
`limitations` sentence, which is the honest way to say "nothing was
captured here."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    ChangePassport,
    ChangeView,
    EvidenceReference,
    EvidenceStatus,
    RecoveryStatus,
    ToolTrustSummaryEntry,
)
from backend.app.core.database import Database
from backend.app.core.replay_service import ReplayService
from backend.app.core.tool_registry_service import ToolRegistryService
from backend.app.identity.repository import DelegationRepository

# (table, id_column, timestamp_column, evidence_kind)
_LATEST_EVIDENCE_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("git_checkpoints", "id", "captured_at", "git_checkpoint"),
    ("environment_passports", "id", "captured_at", "environment_passport"),
    ("dependency_reports", "id", "captured_at", "dependency_report"),
    ("assurance_runs", "id", "completed_at", "assurance_run"),
    ("outcomes", "id", "observed_at", "provider_outcome"),
)

_MISSING_EVIDENCE_MESSAGES = {
    "git_checkpoint": "No Git checkpoint has been captured for this Change.",
    "environment_passport": "No environment passport has been captured for this Change.",
    "dependency_report": "No dependency report has been captured for this Change.",
    "assurance_run": "No assurance check has been run for this Change.",
    "provider_outcome": "No provider outcome has been recorded for this Change.",
}


def _default_clock() -> datetime:
    return datetime.now(UTC)


class PassportBuilder:
    """Implements `PassportPort`."""

    def __init__(
        self,
        database: Database,
        delegations: DelegationRepository,
        *,
        tools: ToolRegistryService | None = None,
        replay: ReplayService | None = None,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self.database = database
        self.delegations = delegations
        self.tools = tools or ToolRegistryService(database)
        self.replay = replay or ReplayService(database)
        self._clock = clock

    def build(self, change: ChangeView) -> ChangePassport:
        delegations = self.delegations.list_for_change(change.id)
        actor_ids = sorted({d.grantee_id for d in delegations}, key=str)
        authority_summary = sorted(
            f"{scope} until {delegation.expires_at.isoformat()}"
            + (" (revoked)" if delegation.revoked_at is not None else "")
            for delegation in delegations
            for scope in delegation.scopes
        )

        evidence: list[EvidenceReference] = []
        limitations: list[str] = []
        for table, id_column, time_column, kind in _LATEST_EVIDENCE_SOURCES:
            reference = self._latest_evidence(table, id_column, time_column, kind, change)
            if reference is None:
                limitations.append(_MISSING_EVIDENCE_MESSAGES[kind])
            else:
                evidence.append(reference)

        outcome_ids = self._outcome_ids(change.id)
        recovery_status = self._latest_recovery_status(change.id)
        if recovery_status is None:
            limitations.append("No recovery plan has been created for this Change.")

        tool_trust_summary = self._tool_trust_summary(change.id)
        if not tool_trust_summary:
            limitations.append("No tools have been observed for this Change.")

        replay_verified, replay_checked_events, replay_first_break_seq = (
            self._replay_summary(change.id)
        )
        if replay_verified is None:
            limitations.append(
                "No journal events have been recorded for this Change; "
                "replay verification is not meaningful."
            )
        elif not replay_verified:
            limitations.append(
                f"Replay chain verification failed at seq={replay_first_break_seq}."
            )

        content = {
            "schema_version": 1,
            "change_id": str(change.id),
            "lifecycle_state": change.lifecycle_state.value,
            "actor_ids": [str(actor_id) for actor_id in actor_ids],
            "authority_summary": authority_summary,
            "evidence": [
                {
                    "kind": item.kind,
                    "id": str(item.id),
                    "status": item.status.value,
                    "captured_at": item.captured_at.isoformat() if item.captured_at else None,
                }
                for item in sorted(evidence, key=lambda item: (item.kind, str(item.id)))
            ],
            "outcomes": sorted(str(outcome_id) for outcome_id in outcome_ids),
            "limitations": sorted(limitations),
            "recovery_status": recovery_status.value if recovery_status else None,
            "tool_trust_summary": [
                {
                    "tool_id": str(entry.tool_id),
                    "name": entry.name,
                    "version": entry.version,
                    "publisher": entry.publisher,
                    "trust_state": entry.trust_state.value,
                    "signature_state": entry.signature_state.value,
                    "drifted": entry.drifted,
                }
                for entry in sorted(tool_trust_summary, key=lambda item: str(item.tool_id))
            ],
            "replay_verified": replay_verified,
            "replay_checked_events": replay_checked_events,
            "replay_first_break_seq": replay_first_break_seq,
        }
        canonical_json = json.dumps(
            content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        digest = hashlib.sha256(canonical_json).hexdigest()

        return ChangePassport(
            id=uuid4(),
            change_id=change.id,
            lifecycle_state=change.lifecycle_state,
            actor_ids=actor_ids,
            authority_summary=authority_summary,
            evidence=evidence,
            outcomes=outcome_ids,
            limitations=sorted(limitations),
            recovery_status=recovery_status,
            tool_trust_summary=tool_trust_summary,
            replay_verified=replay_verified,
            replay_checked_events=replay_checked_events,
            replay_first_break_seq=replay_first_break_seq,
            generated_at=self._clock(),
            canonical_digest=digest,
        )

    def _latest_evidence(
        self,
        table: str,
        id_column: str,
        time_column: str,
        kind: str,
        change: ChangeView,
    ) -> EvidenceReference | None:
        query = (
            f"SELECT {id_column} AS evidence_id, {time_column} AS evidence_time, "
            f"head_sha AS head_sha "
            f"FROM {table} WHERE change_id = ? ORDER BY {time_column} DESC LIMIT 1"
            if table == "git_checkpoints"
            else (
                f"SELECT {id_column} AS evidence_id, {time_column} AS evidence_time "
                f"FROM {table} WHERE change_id = ? ORDER BY {time_column} DESC LIMIT 1"
            )
        )
        with self.database.connection() as connection:
            row = connection.execute(query, (str(change.id),)).fetchone()
        if row is None:
            return None

        status = EvidenceStatus.CURRENT
        if (
            table == "git_checkpoints"
            and change.git_summary is not None
            and row["head_sha"] != change.git_summary.head_sha
        ):
            status = EvidenceStatus.STALE

        return EvidenceReference(
            kind=kind,
            id=UUID(row["evidence_id"]),
            status=status,
            captured_at=datetime.fromisoformat(row["evidence_time"]),
        )

    def _outcome_ids(self, change_id: UUID) -> list[UUID]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT id FROM outcomes WHERE change_id = ? ORDER BY observed_at DESC",
                (str(change_id),),
            ).fetchall()
        return [UUID(row["id"]) for row in rows]

    def _latest_recovery_status(self, change_id: UUID) -> RecoveryStatus | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT status FROM recovery_plans
                WHERE change_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (str(change_id),),
            ).fetchone()
        return RecoveryStatus(row["status"]) if row is not None else None

    def _tool_trust_summary(self, change_id: UUID) -> list[ToolTrustSummaryEntry]:
        manifests = self.tools.list_for_change(change_id)
        summary: list[ToolTrustSummaryEntry] = []
        for manifest in manifests:
            drift = self.tools.check_drift(manifest.id, change_id=change_id)
            summary.append(
                ToolTrustSummaryEntry(
                    tool_id=manifest.id,
                    name=manifest.name,
                    version=manifest.version,
                    publisher=manifest.publisher,
                    trust_state=manifest.trust_state,
                    signature_state=manifest.signature_state,
                    drifted=drift.drifted,
                )
            )
        return summary

    def _replay_summary(self, change_id: UUID) -> tuple[bool | None, int | None, int | None]:
        result = self.replay.verify_chain(change_id)
        if result.checked_events == 0:
            return None, None, None
        return result.verified, result.checked_events, result.first_break_seq
