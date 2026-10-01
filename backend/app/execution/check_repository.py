"""SQLite persistence for ``check_runs`` (migration 013): one row per confined check box.

A row is inserted (state CREATING) before the box's AppContainer profile is
created and is the only durable record of that profile, its tree and the
runtime ACEs granted to its package SID; the DB-driven sweep relies on it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from backend.app.core.database import Database
from backend.app.core.errors import AppError


class CheckRunState(StrEnum):
    CREATING = "CREATING"
    READY = "READY"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    CLEANED = "CLEANED"
    CLEANUP_FAILED = "CLEANUP_FAILED"


@dataclass(frozen=True, slots=True)
class RuntimeGrant:
    """One runtime cache entry the box's package SID was (or will be) granted read on."""

    path: str
    manifest_digest: str

    def to_payload(self) -> dict[str, str]:
        return {"path": self.path, "manifest_digest": self.manifest_digest}


@dataclass(frozen=True, slots=True)
class CheckRunRecord:
    id: UUID
    change_id: UUID
    profile_name: str
    package_sid: str
    state: CheckRunState
    network: bool
    runtime_grants: tuple[RuntimeGrant, ...]
    created_at: datetime
    updated_at: datetime
    tree_digest: str | None = None
    facts: dict[str, Any] | None = None
    exit_code: int | None = None
    timed_out: bool | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CheckRunRecord:
        grants = tuple(
            RuntimeGrant(str(item["path"]), str(item["manifest_digest"]))
            for item in json.loads(row["runtime_digests_json"])
        )
        return cls(
            id=UUID(row["id"]),
            change_id=UUID(row["change_id"]),
            profile_name=row["profile_name"],
            package_sid=row["package_sid"],
            state=CheckRunState(row["state"]),
            network=bool(row["network"]),
            runtime_grants=grants,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            tree_digest=row["tree_digest"],
            facts=json.loads(row["facts_json"]) if row["facts_json"] else None,
            exit_code=row["exit_code"],
            timed_out=None if row["timed_out"] is None else bool(row["timed_out"]),
        )


def check_run_state_conflict(actual: str, operation: str) -> AppError:
    return AppError(
        "CHECK_RUN_STATE_CONFLICT",
        "The check run is not in a state that allows this operation.",
        status_code=409,
        details={"state": actual, "operation": operation},
    )


def _grants_json(grants: tuple[RuntimeGrant, ...]) -> str:
    return json.dumps([grant.to_payload() for grant in grants], sort_keys=True,
                      separators=(",", ":"))


class CheckRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(
        self, record: CheckRunRecord, *, connection: sqlite3.Connection | None = None
    ) -> CheckRunRecord:
        with self.database.connection_or(connection, immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO check_runs (
                    id, change_id, profile_name, package_sid, state, network, tree_digest,
                    runtime_digests_json, facts_json, exit_code, timed_out, created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.id), str(record.change_id), record.profile_name,
                    record.package_sid, record.state.value, int(record.network),
                    record.tree_digest, _grants_json(record.runtime_grants),
                    json.dumps(record.facts, sort_keys=True) if record.facts is not None else None,
                    record.exit_code,
                    None if record.timed_out is None else int(record.timed_out),
                    record.created_at.isoformat(), record.updated_at.isoformat(),
                ),
            )
        return record

    def update(
        self, record: CheckRunRecord, *, expected_state: CheckRunState,
        connection: sqlite3.Connection | None = None,
    ) -> CheckRunRecord:
        """Compare-and-set on ``state``; a concurrent transition raises a conflict."""

        with self.database.connection_or(connection, immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE check_runs
                SET state = ?, tree_digest = ?, facts_json = ?, exit_code = ?,
                    timed_out = ?, updated_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    record.state.value, record.tree_digest,
                    json.dumps(record.facts, sort_keys=True) if record.facts is not None else None,
                    record.exit_code,
                    None if record.timed_out is None else int(record.timed_out),
                    record.updated_at.isoformat(), str(record.id), expected_state.value,
                ),
            )
            if cursor.rowcount != 1:
                row = conn.execute(
                    "SELECT state FROM check_runs WHERE id = ?", (str(record.id),)
                ).fetchone()
                raise check_run_state_conflict(
                    row["state"] if row is not None else "MISSING", "update")
        return record

    def get(
        self, run_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> CheckRunRecord | None:
        with self.database.connection_or(connection) as conn:
            row = conn.execute("SELECT * FROM check_runs WHERE id = ?", (str(run_id),)).fetchone()
        return CheckRunRecord.from_row(row) if row is not None else None

    def list_unclean(
        self, *, connection: sqlite3.Connection | None = None
    ) -> list[CheckRunRecord]:
        with self.database.connection_or(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM check_runs WHERE state != ? ORDER BY created_at, rowid",
                (CheckRunState.CLEANED.value,),
            ).fetchall()
        return [CheckRunRecord.from_row(row) for row in rows]

    def for_change(
        self, change_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> list[CheckRunRecord]:
        with self.database.connection_or(connection) as conn:
            rows = conn.execute(
                "SELECT * FROM check_runs WHERE change_id = ? ORDER BY created_at, rowid",
                (str(change_id),),
            ).fetchall()
        return [CheckRunRecord.from_row(row) for row in rows]

    def events_for_change(
        self, change_id: UUID, *, connection: sqlite3.Connection | None = None
    ) -> list[CheckRunEvent]:
        """The Change's ``check.confined_run`` / ``check.unconfined_run`` journal events."""

        with self.database.connection_or(connection) as conn:
            rows = conn.execute(
                "SELECT event_type, subject_id, payload_json FROM journal_events "
                "WHERE change_id = ? AND event_type IN (?, ?) ORDER BY seq",
                (str(change_id), CONFINED_RUN_EVENT, UNCONFINED_RUN_EVENT),
            ).fetchall()
        return check_run_events((row["event_type"], row["subject_id"], row["payload_json"])
                                for row in rows)


# --------------------------------------------------------------------------- facts
#
# Phase 5 (05-04): the observed boundary of a check run, and the Change-level
# ``confined_checks`` fact. A run counts as confined only when BOTH its row and
# every journaled ``check.confined_run`` event for it carry verified token facts
# (AppContainer token, Job Object verified before resume). Anything absent,
# mixed or unverifiable is UNKNOWN or FAIL, never PASS.

CONFINED_RUN_EVENT = "check.confined_run"
UNCONFINED_RUN_EVENT = "check.unconfined_run"
BOUNDARY_APPCONTAINER = "APPCONTAINER"
BOUNDARY_UNCONFINED = "UNCONFINED"

Fact = Literal["PASS", "FAIL", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class CheckRunEvent:
    event_type: str
    subject_id: str | None
    payload: Mapping[str, Any] | None  # None: malformed payload


def check_run_events(rows: Iterable[tuple[str, str | None, str | None]]) -> list[CheckRunEvent]:
    events: list[CheckRunEvent] = []
    for event_type, subject_id, raw in rows:
        if event_type not in (CONFINED_RUN_EVENT, UNCONFINED_RUN_EVENT):
            continue
        try:
            payload = json.loads(raw) if isinstance(raw, str) else None
        except (ValueError, RecursionError):
            payload = None
        events.append(CheckRunEvent(event_type, subject_id,
                                    payload if isinstance(payload, dict) else None))
    return events


def verified_token_facts(facts: Mapping[str, Any] | None) -> bool:
    """True only for facts read from an AppContainer token whose Job Object was verified."""

    return (isinstance(facts, Mapping) and facts.get("is_appcontainer") is True
            and facts.get("job_verified") is True)


def _run_events(run_id: UUID, events: Sequence[CheckRunEvent]) -> list[CheckRunEvent]:
    key = str(run_id)
    return [event for event in events
            if event.subject_id == key
            or (event.payload is not None and event.payload.get("check_run_id") == key)]


def check_run_fact(
    run_id: UUID | None, claimed: str | None, *,
    records: Mapping[UUID, CheckRunRecord], events: Sequence[CheckRunEvent],
) -> tuple[Fact, str | None]:
    """Classify one check run behind a piece of evidence; the reason explains non-PASS."""

    if run_id is None or claimed is None:
        return "UNKNOWN", "the evidence records no check run or boundary"
    mine = _run_events(run_id, events)
    if claimed == BOUNDARY_UNCONFINED or any(
            event.event_type == UNCONFINED_RUN_EVENT for event in mine):
        return "FAIL", "a check ran UNCONFINED (delegated checks.unconfined opt-in)"
    if claimed != BOUNDARY_APPCONTAINER:
        return "UNKNOWN", "the evidence names an unrecognized check boundary"
    record = records.get(run_id)
    confined = [event for event in mine if event.event_type == CONFINED_RUN_EVENT]
    if record is None or not confined:
        return "UNKNOWN", "the check run record or its journal event is missing"
    if record.facts is None:
        return "UNKNOWN", "the check run recorded no verified launch"
    if not verified_token_facts(record.facts):
        return "FAIL", "the check run's boundary verification failed"
    for event in confined:
        payload = event.payload
        if (payload is None or event.subject_id != str(run_id)
                or payload.get("check_run_id") != str(run_id)
                or payload.get("boundary") != BOUNDARY_APPCONTAINER
                or payload.get("package_sid") != record.package_sid
                or not verified_token_facts(payload)):
            return "FAIL", "a journaled check run failed boundary verification"
    return "PASS", None


def change_check_runs_fact(
    *, records: Mapping[UUID, CheckRunRecord], events: Sequence[CheckRunEvent],
) -> tuple[Fact, str | None, list[tuple[UUID, str | None]]]:
    """``confined_checks`` over EVERY check run of a Change, plus each run's boundary (D2).

    The runs are every ``check_runs`` row (verification runs and diff-coverage
    runs alike) and every run a ``check.confined_run`` / ``check.unconfined_run``
    event names. PASS only when at least one run exists and every run is a box
    run whose row and hash-verified journal events verify (``check_run_fact``);
    FAIL on any unconfined run or any failed/unverified boundary fact; UNKNOWN
    when no run exists or a run's facts are missing. Each run's boundary is
    APPCONTAINER only for a verified box run, UNCONFINED for a delegated
    opt-in run, and None otherwise.
    """

    ordered: dict[UUID, None] = {}
    for record in sorted(records.values(), key=lambda item: (item.created_at, str(item.id))):
        ordered[record.id] = None
    unconfined: set[UUID] = set()
    for event in events:
        candidates = [event.subject_id]
        if event.payload is not None:
            candidates.append(event.payload.get("check_run_id"))
        for candidate in candidates:
            try:
                run_id = UUID(str(candidate))
            except ValueError:
                continue
            ordered.setdefault(run_id, None)
            if event.event_type == UNCONFINED_RUN_EVENT:
                unconfined.add(run_id)
    runs: list[tuple[UUID, str | None]] = []
    results: list[tuple[Fact, str | None]] = []
    for run_id in ordered:
        if run_id in unconfined:
            runs.append((run_id, BOUNDARY_UNCONFINED))
            results.append(("FAIL", "a check ran UNCONFINED (delegated checks.unconfined opt-in)"))
            continue
        state, reason = check_run_fact(run_id, BOUNDARY_APPCONTAINER, records=records,
                                       events=events)
        runs.append((run_id, BOUNDARY_APPCONTAINER if state == "PASS" else None))
        results.append((state, reason))
    if not runs:
        return "UNKNOWN", "no check run of this Change is recorded", runs
    for fact in ("FAIL", "UNKNOWN"):
        for state, reason in results:
            if state == fact:
                return state, reason, runs
    return "PASS", None, runs


def confined_checks_fact(
    bound: Sequence[tuple[UUID | None, str | None]], *,
    records: Mapping[UUID, CheckRunRecord], events: Sequence[CheckRunEvent],
) -> tuple[Fact, str | None]:
    """PASS only when every bound run is a verified box run; any FAIL wins; none ran -> UNKNOWN.

    ``events`` are the Change's own journal events. Any ``check.unconfined_run``
    among them is FAIL even when it does not feed the bound evidence: a check of
    this Change ran at user authority, so "its checks were confined" is false.
    """

    if any(event.event_type == UNCONFINED_RUN_EVENT for event in events):
        return "FAIL", "a check of this Change ran UNCONFINED (delegated checks.unconfined opt-in)"
    if not bound:
        return "UNKNOWN", "no check run feeds the evaluated evidence"
    results = [check_run_fact(run_id, claimed, records=records, events=events)
               for run_id, claimed in bound]
    for fact in ("FAIL", "UNKNOWN"):
        for state, reason in results:
            if state == fact:
                return state, reason
    return "PASS", None
