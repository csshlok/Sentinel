"""SQLite persistence for ``[KB]`` evidence, using ``[SD]``'s canonical tables.

Writes ``agent_runs``, ``git_checkpoints``, ``environment_passports``,
``dependency_reports``, ``assurance_plans`` and ``assurance_runs`` through the
frozen contract models' own JSON serialization, and nothing else. Schema and
``Database`` belong to ``[SD]`` and are only used, never changed. Evidence rows
are immutable (a repeated save of the same id is ignored); agent runs are
replaced as their status changes. Timestamps are stored as ISO-8601 text so
other readers (the Passport builder) can order by them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from backend.app.contracts.models import (
    AgentRun, AssurancePlan, AssuranceRun, DependencyReport, EnvironmentPassport,
    GitCheckpoint,
)
from backend.app.core.database import Database
from backend.app.core.errors import AppError

M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class StoredPlan:
    """A persisted plan and the digest of the Change Contract it was built from.

    The digest is what lets a restarted process still notice that the contract
    changed after planning. Plans are stored as ``{"plan": ..., "contract_sha256": ...}``
    envelopes, so read them through ``EvidenceStore`` rather than as bare
    ``AssurancePlan`` JSON.
    """

    plan: AssurancePlan
    contract_sha256: str


class EvidenceStore:
    def __init__(self, database: Database) -> None:
        self._db = database

    # -- agent runs ---------------------------------------------------------

    def save_agent_run(self, run: AgentRun) -> None:
        with self._db.connection(immediate=True) as c:
            c.execute(
                "INSERT OR REPLACE INTO agent_runs "
                "(id, change_id, status, payload_json, started_at, completed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(run.id), str(run.change_id), run.status.value, run.model_dump_json(),
                 run.started_at.isoformat(),
                 run.completed_at.isoformat() if run.completed_at else None))
            for process in run.descendant_processes:
                c.execute(
                    "INSERT OR REPLACE INTO descendant_processes "
                    "(agent_run_id, pid, parent_pid, executable_path, command_line, "
                    "started_at, terminated_at, exit_code, attributed, attribution_reason) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(run.id), process.pid, process.parent_pid,
                        process.executable_path, process.command_line,
                        process.started_at.isoformat(),
                        process.terminated_at.isoformat() if process.terminated_at else None,
                        process.exit_code, int(process.attributed), process.attribution_reason,
                    ),
                )

    def get_agent_run(self, run_id: UUID) -> AgentRun | None:
        return self._one("SELECT payload_json FROM agent_runs WHERE id = ?", (str(run_id),), AgentRun)

    def list_agent_runs(self, change_id: UUID) -> list[AgentRun]:
        return self._many("SELECT payload_json FROM agent_runs WHERE change_id = ? "
                          "ORDER BY started_at ASC, id ASC", (str(change_id),), AgentRun)

    # -- Git checkpoints ----------------------------------------------------

    def save_checkpoint(self, cp: GitCheckpoint) -> None:
        with self._db.connection(immediate=True) as c:
            c.execute(
                "INSERT OR IGNORE INTO git_checkpoints "
                "(id, change_id, name, head_sha, evidence_revision, payload_json, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(cp.id), str(cp.change_id), cp.name, cp.head_sha, cp.evidence_revision,
                 cp.model_dump_json(), cp.captured_at.isoformat()))

    def get_checkpoint(self, checkpoint_id: UUID) -> GitCheckpoint | None:
        return self._one("SELECT payload_json FROM git_checkpoints WHERE id = ?",
                         (str(checkpoint_id),), GitCheckpoint)

    def latest_checkpoint(self, change_id: UUID) -> GitCheckpoint | None:
        return self._one(
            "SELECT payload_json FROM git_checkpoints WHERE change_id = ? "
            "ORDER BY captured_at DESC, evidence_revision DESC LIMIT 1",
            (str(change_id),), GitCheckpoint)

    def named_checkpoint(self, change_id: UUID, name: str) -> GitCheckpoint | None:
        """The earliest checkpoint with ``name`` (e.g. the ``baseline``)."""

        return self._one(
            "SELECT payload_json FROM git_checkpoints WHERE change_id = ? AND name = ? "
            "ORDER BY captured_at ASC LIMIT 1", (str(change_id), name), GitCheckpoint)

    def list_checkpoints(self, change_id: UUID) -> list[GitCheckpoint]:
        return self._many("SELECT payload_json FROM git_checkpoints WHERE change_id = ? "
                          "ORDER BY captured_at ASC, evidence_revision ASC",
                          (str(change_id),), GitCheckpoint)

    # -- environment passports ----------------------------------------------

    def save_environment(self, passport: EnvironmentPassport) -> None:
        with self._db.connection(immediate=True) as c:
            c.execute(
                "INSERT OR IGNORE INTO environment_passports "
                "(id, change_id, payload_json, captured_at) VALUES (?, ?, ?, ?)",
                (str(passport.id), str(passport.change_id), passport.model_dump_json(),
                 passport.captured_at.isoformat()))

    def get_environment(self, passport_id: UUID) -> EnvironmentPassport | None:
        return self._one("SELECT payload_json FROM environment_passports WHERE id = ?",
                         (str(passport_id),), EnvironmentPassport)

    def latest_environment(self, change_id: UUID) -> EnvironmentPassport | None:
        return self._one("SELECT payload_json FROM environment_passports WHERE change_id = ? "
                         "ORDER BY captured_at DESC LIMIT 1", (str(change_id),),
                         EnvironmentPassport)

    def first_environment(self, change_id: UUID) -> EnvironmentPassport | None:
        return self._one("SELECT payload_json FROM environment_passports WHERE change_id = ? "
                         "ORDER BY captured_at ASC LIMIT 1", (str(change_id),),
                         EnvironmentPassport)

    # -- dependency reports -------------------------------------------------

    def save_dependency_report(self, report: DependencyReport) -> None:
        with self._db.connection(immediate=True) as c:
            c.execute(
                "INSERT OR IGNORE INTO dependency_reports "
                "(id, change_id, checkpoint_id, payload_json, captured_at) VALUES (?, ?, ?, ?, ?)",
                (str(report.id), str(report.change_id), str(report.checkpoint_id),
                 report.model_dump_json(), report.captured_at.isoformat()))

    def latest_dependency_report(self, change_id: UUID) -> DependencyReport | None:
        return self._one("SELECT payload_json FROM dependency_reports WHERE change_id = ? "
                         "ORDER BY captured_at DESC LIMIT 1", (str(change_id),),
                         DependencyReport)

    # -- assurance ----------------------------------------------------------

    def save_plan(self, plan: AssurancePlan, contract_sha256: str) -> None:
        envelope = json.dumps({"plan": json.loads(plan.model_dump_json()),
                               "contract_sha256": contract_sha256}, separators=(",", ":"))
        with self._db.connection(immediate=True) as c:
            c.execute(
                "INSERT OR IGNORE INTO assurance_plans "
                "(id, change_id, checkpoint_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(plan.id), str(plan.change_id), str(plan.checkpoint_id),
                 envelope, plan.created_at.isoformat()))

    def get_plan(self, plan_id: UUID) -> StoredPlan | None:
        return self._plan("SELECT payload_json FROM assurance_plans WHERE id = ?", (str(plan_id),))

    def latest_plan(self, change_id: UUID) -> StoredPlan | None:
        return self._plan("SELECT payload_json FROM assurance_plans WHERE change_id = ? "
                          "ORDER BY created_at DESC LIMIT 1", (str(change_id),))

    def _plan(self, sql: str, params: tuple) -> StoredPlan | None:
        with self._db.connection() as c:
            row = c.execute(sql, params).fetchone()
        if row is None:
            return None
        body = json.loads(row["payload_json"])
        return StoredPlan(AssurancePlan.model_validate(body["plan"]), str(body["contract_sha256"]))

    def save_runs(self, runs: list[AssuranceRun]) -> None:
        with self._db.connection(immediate=True) as c:
            for run in runs:
                c.execute(
                    "INSERT OR IGNORE INTO assurance_runs (id, change_id, plan_id, checkpoint_id, "
                    "status, payload_json, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(run.id), str(run.change_id), str(run.plan_id), str(run.checkpoint_id),
                     run.status.value, run.model_dump_json(), run.started_at.isoformat(),
                     run.completed_at.isoformat()))

    def list_runs(self, plan_id: UUID) -> list[AssuranceRun]:
        return self._many("SELECT payload_json FROM assurance_runs WHERE plan_id = ? "
                          "ORDER BY completed_at ASC, id ASC", (str(plan_id),), AssuranceRun)

    # -- helpers ------------------------------------------------------------

    def _one(self, sql: str, params: tuple, model: type[M]) -> M | None:
        with self._db.connection() as c:
            row = c.execute(sql, params).fetchone()
        return model.model_validate_json(row["payload_json"]) if row else None

    def _many(self, sql: str, params: tuple, model: type[M]) -> list[M]:
        with self._db.connection() as c:
            rows = c.execute(sql, params).fetchall()
        return [model.model_validate_json(row["payload_json"]) for row in rows]


class IdempotencyStore:
    """Replay-safe execution for side-effecting requests (launch, attach).

    Uses ``[SD]``'s ``idempotency_records`` table. A request first *claims* its
    key, so two concurrent identical submissions cannot both start an agent; the
    second sees ``IDEMPOTENCY_REQUEST_IN_PROGRESS``. A different request body under
    the same key is refused, and a failed attempt releases its claim.
    """

    PENDING = ""

    def __init__(self, database: Database) -> None:
        self._db = database

    def claim(self, scope: str, key: str, request_hash: str) -> str | None:
        """Return the stored result for a completed replay, or ``None`` if newly claimed."""

        with self._db.connection(immediate=True) as c:
            row = c.execute(
                "SELECT request_hash, result_json FROM idempotency_records WHERE scope = ? AND key = ?",
                (scope, key)).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO idempotency_records (scope, key, request_hash, result_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (scope, key, request_hash, self.PENDING, _now()))
                return None
            if row["request_hash"] != request_hash:
                raise AppError("IDEMPOTENCY_KEY_REUSED",
                               "The idempotency key was already used for a different request.",
                               status_code=409, details={"scope": scope})
            if row["result_json"] == self.PENDING:
                raise AppError("IDEMPOTENCY_REQUEST_IN_PROGRESS",
                               "A request with this idempotency key is still running.",
                               status_code=409, details={"scope": scope})
            return row["result_json"]

    def complete(self, scope: str, key: str, result_json: str) -> None:
        with self._db.connection(immediate=True) as c:
            c.execute("UPDATE idempotency_records SET result_json = ? WHERE scope = ? AND key = ?",
                      (result_json, scope, key))

    def release(self, scope: str, key: str) -> None:
        with self._db.connection(immediate=True) as c:
            c.execute("DELETE FROM idempotency_records WHERE scope = ? AND key = ? AND result_json = ?",
                      (scope, key, self.PENDING))


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
