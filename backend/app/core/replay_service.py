"""Trace-only Replay: deterministic reconstruction and cryptographic
verification of a Change's causal timeline. No re-execution of any kind.

Implements `ReplayPort` (see EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md A.7).
Lives in `core/` (shared, cross-cutting) rather than any single owner's
package because reconstruction reads across every owner's event types, the
same way `core/lifecycle_facts_service.py` already does for cross-cutting
reads.
"""

from __future__ import annotations

from uuid import UUID

from backend.app.contracts.models import (
    ChainVerificationResult,
    JournalEffect,
    JournalEvent,
    JournalEventType,
    ReplayTimeline,
    utc_now,
)
from backend.app.core.database import Database
from backend.app.core.journal import compute_event_hash, row_to_effect, row_to_event

LIMITATIONS = (
    "Trace-only replay: no agent command, test, or recovery action is "
    "re-executed.",
    "Process-tree evidence is available on AgentRun and in the raw journal, "
    "but descendant events are excluded from this trace-replay view.",
    "No filesystem-level change tracking beyond Git (the filesystem "
    "tracker is out of scope).",
    "The hash chain is scoped per Change; a verified chain proves this "
    "Change's own events were not edited since they were written, not "
    "cross-Change tamper evidence and not that the underlying evidence "
    "was itself captured honestly.",
)


class ReplayService:
    """Implements `ReplayPort`."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def reconstruct(self, change_id: UUID) -> ReplayTimeline:
        events, effects = self._load(change_id)
        result = self._verify(change_id, events)
        replay_events = [event for event in events if event.event_type not in {
            JournalEventType.AGENT_DESCENDANT_OBSERVED,
            JournalEventType.AGENT_DESCENDANT_TERMINATED,
            JournalEventType.AGENT_PROCESS_TREE_TERMINATED,
        }]
        return ReplayTimeline(
            change_id=change_id,
            events=replay_events,
            effects=effects,
            chain_verified=result.verified,
            first_break_seq=result.first_break_seq,
            limitations=list(LIMITATIONS),
            generated_at=utc_now(),
        )

    def verify_chain(self, change_id: UUID) -> ChainVerificationResult:
        events, _effects = self._load(change_id)
        return self._verify(change_id, events)

    def export(self, change_id: UUID) -> ReplayTimeline:
        """Redacted, self-contained bundle for external debugging.

        Reuses `reconstruct`: every payload is already bounded/redacted at
        the point of emission (A.5), so nothing new needs to be invented for
        export -- the timeline itself already *is* the export bundle.
        """

        return self.reconstruct(change_id)

    # -- internals --------------------------------------------------------

    def _load(self, change_id: UUID) -> tuple[list[JournalEvent], list[JournalEffect]]:
        with self.database.connection() as connection:
            event_rows = connection.execute(
                "SELECT * FROM journal_events WHERE change_id = ? ORDER BY seq",
                (str(change_id),),
            ).fetchall()
            effect_rows = connection.execute(
                "SELECT * FROM journal_effects WHERE change_id = ? ORDER BY rowid",
                (str(change_id),),
            ).fetchall()
        return (
            [row_to_event(row) for row in event_rows],
            [row_to_effect(row) for row in effect_rows],
        )

    @staticmethod
    def _verify(change_id: UUID, events: list[JournalEvent]) -> ChainVerificationResult:
        prev_hash: str | None = None
        for index, event in enumerate(events):
            if event.prev_event_hash != prev_hash:
                return ChainVerificationResult(
                    change_id=change_id, verified=False, checked_events=index,
                    first_break_seq=event.seq,
                    reason="prev_event_hash does not match the prior event's stored hash.",
                )
            recomputed = compute_event_hash(
                prev_event_hash=event.prev_event_hash, seq=event.seq, change_id=event.change_id,
                event_type=event.event_type.value, actor_id=event.actor_id,
                subject_type=event.subject_type, subject_id=event.subject_id,
                payload=event.payload, occurred_at=event.occurred_at,
                schema_version=event.schema_version,
            )
            if recomputed != event.event_hash:
                return ChainVerificationResult(
                    change_id=change_id, verified=False, checked_events=index,
                    first_break_seq=event.seq,
                    reason="event_hash does not match its recomputed value.",
                )
            prev_hash = event.event_hash
        return ChainVerificationResult(
            change_id=change_id, verified=True, checked_events=len(events),
            first_break_seq=None, reason=None,
        )
