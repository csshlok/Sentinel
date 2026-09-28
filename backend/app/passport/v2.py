"""Issue Passport v2 claims only from a Change ID and persisted Sentinel rows."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from uuid import UUID

from backend.app.contracts.models import (
    DiffCoverageResult,
    PassportV2DiffClaim,
    PassportV2Issued,
    PassportV2LaunchBinding,
    PassportV2Payload,
    utc_now,
)
from backend.app.core.database import Database
from backend.app.core.errors import AppError, change_not_found
from backend.app.core.journal import compute_event_hash
from backend.app.git.state import GitStateTracker
from backend.app.passport.cng import CngKey, fingerprint
from backend.app.passport.jcs import canonicalize
from backend.app.passport.identity import active_key_name

_MAX_JOURNAL_EVENTS = 4096
_MAX_LAUNCHES = 1024
_MAX_RECORD_BYTES = 1_048_576


def canonical_payload(payload: PassportV2Payload) -> bytes:
    """Canonical payload bytes for the constrained v2 schema (no JSON floats)."""
    return canonicalize(payload.model_dump(mode="json"))


class PassportV2Issuer:
    """Build and sign an allowlisted snapshot of one stored Change."""

    def __init__(self, database: Database, *, key_name: str | None = None,
                 installation_label: str = "local") -> None:
        if not installation_label.strip() or len(installation_label) > 80:
            raise ValueError("A short installation label is required")
        self._database = database
        self._key_name = key_name
        self._label = installation_label.strip()

    def snapshot(self, change_id: UUID) -> PassportV2Payload:
        """Read all bound records in one SQLite snapshot; caller supplies only the ID."""
        with self._database.connection() as connection:
            change = connection.execute(
                "SELECT id, revision, lifecycle_state, risk_level, contract_json, "
                "repository_path, evidence_revision "
                "FROM changes WHERE id = ?", (str(change_id),)).fetchone()
            if change is None:
                raise change_not_found(str(change_id))
            journal = connection.execute(
                "SELECT seq, event_type, actor_id, subject_type, subject_id, payload_json, "
                "occurred_at, prev_event_hash, event_hash, schema_version "
                "FROM journal_events WHERE change_id = ? ORDER BY seq LIMIT 4097",
                (str(change_id),)).fetchall()
            launches = connection.execute(
                "SELECT id, status, payload_json FROM agent_runs WHERE change_id = ? "
                "ORDER BY id LIMIT 1025",
                (str(change_id),)).fetchall()
            coverage = connection.execute(
                "SELECT payload_json FROM diff_coverage_results WHERE change_id = ? "
                "ORDER BY rowid DESC LIMIT 1", (str(change_id),)).fetchone()
        if len(journal) > _MAX_JOURNAL_EVENTS or len(launches) > _MAX_LAUNCHES:
            raise AppError("PASSPORT_EVIDENCE_LIMIT", "Too many journal or launch records to bind.",
                           status_code=409)
        head = self._verify_journal(change_id, journal)
        events: dict[str, dict[str, object]] = {}
        for event in journal:
            kind = event["event_type"]
            if kind not in {"agent.launched", "agent.completed", "agent.attached"}:
                continue
            if event["subject_type"] != "agent_run" or not event["subject_id"]:
                raise AppError("PASSPORT_LAUNCH_INVALID", "Launch journal subject is invalid.",
                               status_code=409)
            run_events = events.setdefault(event["subject_id"], {})
            if kind in run_events:
                raise AppError("PASSPORT_LAUNCH_INVALID", "Duplicate launch journal event.",
                               status_code=409)
            run_events[kind] = json.loads(event["payload_json"])
        if set(events) != {row["id"] for row in launches}:
            raise AppError("PASSPORT_LAUNCH_INVALID", "Launch records and journal differ.",
                           status_code=409)
        bindings: list[PassportV2LaunchBinding] = []
        for row in launches:
            raw = row["payload_json"]
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
                raise AppError("PASSPORT_LAUNCH_INVALID", "Launch record is oversized.", status_code=409)
            try:
                parsed = json.loads(raw)
            except (ValueError, RecursionError) as exc:
                raise AppError("PASSPORT_LAUNCH_INVALID", "Launch record is malformed.",
                               status_code=409) from exc
            if (not isinstance(parsed, dict) or str(parsed.get("id")) != row["id"]
                    or str(parsed.get("change_id")) != str(change_id)):
                raise AppError("PASSPORT_LAUNCH_INVALID", "Launch record identity mismatch.",
                               status_code=409)
            status = parsed.get("status")
            kinds = set(events[row["id"]])
            if status in {"RUNNING", "PAUSED"}:
                raise AppError("PASSPORT_LAUNCH_IN_PROGRESS",
                               "A launch is still in progress; its outcome is unknown.",
                               status_code=409)
            if status == "ATTACHED":
                attached = events[row["id"]].get("agent.attached")
                valid = (kinds == {"agent.attached"} and isinstance(attached, dict)
                         and attached.get("adapter") == parsed.get("adapter")
                         and attached.get("external_run_id") == parsed.get("external_run_id"))
            else:
                completed = events[row["id"]].get("agent.completed")
                valid = (kinds == {"agent.launched", "agent.completed"}
                         and isinstance(completed, dict)
                         and completed.get("status") == status)
            if status != row["status"] or not valid:
                raise AppError("PASSPORT_LAUNCH_INVALID", "Launch status differs from journal.",
                               status_code=409)
            try:
                bindings.append(PassportV2LaunchBinding(
                    run_id=UUID(row["id"]), status=status,
                    record_digest=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                ))
            except (ValueError, TypeError) as exc:
                raise AppError("PASSPORT_LAUNCH_INVALID", "Launch record is malformed.",
                               status_code=409) from exc
        diff_claim, diff_limit = self._coverage_claim(coverage)
        limitations = [
            "Execution boundary evidence is not yet structured; UNKNOWN.",
            "Execution-bearing files that run later are not measured; UNKNOWN.",
            "An executed line does not prove an assertion verified behavior.",
            "Offline journal export contains hash links, not event payloads; original event hashes cannot be recomputed offline.",
        ]
        if not journal:
            limitations.append("No journal events exist for this Change.")
        if not launches:
            limitations.append("No launch records exist for this Change.")
        if diff_limit:
            limitations.append(diff_limit)
        contract_raw = change["contract_json"]
        if isinstance(contract_raw, str) and len(contract_raw.encode("utf-8")) > _MAX_RECORD_BYTES:
            raise AppError("PASSPORT_CONTRACT_INVALID", "Change Contract is oversized.",
                           status_code=409)
        contract_digest = (hashlib.sha256(contract_raw.encode("utf-8")).hexdigest()
                           if isinstance(contract_raw, str) else None)
        payload = PassportV2Payload(
            change_id=change_id, change_revision=change["revision"],
            lifecycle_state=change["lifecycle_state"], risk_level=change["risk_level"],
            contract_digest=contract_digest, journal_head=head,
            journal_event_count=len(journal),
            journal_integrity="PASS" if journal else "UNKNOWN",
            launch_records=bindings, execution_boundary="UNKNOWN",
            diff_coverage=diff_claim, runs_later="UNKNOWN", limitations=limitations,
            issued_at=utc_now(),
        )
        return self._checked_freshness(change_id, payload, change)

    @staticmethod
    def _checked_freshness(change_id: UUID, claims: PassportV2Payload,
                           change: object) -> PassportV2Payload:
        """Reobserve CURRENT coverage before any v2 signing path uses it."""
        diff = claims.diff_coverage
        if diff.freshness != "CURRENT" or diff.head_sha is None or diff.status_digest is None:
            return claims
        try:
            current = GitStateTracker().capture(
                change_id, "passport-issue", change["repository_path"],
                max(1, int(change["evidence_revision"])), 1_048_576,
            )
        except (AppError, OSError, ValueError, TypeError):
            state, reason = "UNKNOWN", "Repository freshness could not be observed at issue."
        else:
            if current.head_sha != diff.head_sha or current.status_digest != diff.status_digest:
                state, reason = "STALE", "Repository moved after diff coverage measurement."
            elif current.summary.patch_truncated:
                state, reason = "UNKNOWN", "Current Git patch was truncated at issue."
            else:
                return claims
        updated = diff.model_copy(update={"freshness": state, "diff_exercised": state})
        return claims.model_copy(update={"diff_coverage": updated,
                                         "limitations": [*claims.limitations, reason]})

    @staticmethod
    def _verify_journal(change_id: UUID, rows: list[object]) -> str | None:
        previous: str | None = None
        for expected_seq, row in enumerate(rows, start=1):
            if row["seq"] != expected_seq or row["prev_event_hash"] != previous:
                raise AppError("PASSPORT_JOURNAL_INVALID", "Journal chain is discontinuous.",
                               status_code=409)
            raw = row["payload_json"]
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
                raise AppError("PASSPORT_JOURNAL_INVALID", "Journal event is oversized.",
                               status_code=409)
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError("Journal payload must be an object")
                calculated = compute_event_hash(
                    prev_event_hash=previous, seq=expected_seq, change_id=change_id,
                    event_type=row["event_type"],
                    actor_id=UUID(row["actor_id"]) if row["actor_id"] else None,
                    subject_type=row["subject_type"],
                    subject_id=UUID(row["subject_id"]) if row["subject_id"] else None,
                    payload=payload, occurred_at=datetime.fromisoformat(row["occurred_at"]),
                    schema_version=row["schema_version"],
                )
            except (ValueError, TypeError, RecursionError) as exc:
                raise AppError("PASSPORT_JOURNAL_INVALID", "Journal event is malformed.",
                               status_code=409) from exc
            if calculated != row["event_hash"]:
                raise AppError("PASSPORT_JOURNAL_INVALID", "Journal event hash mismatch.",
                               status_code=409)
            previous = calculated
        return previous

    @staticmethod
    def _coverage_claim(row: object | None) -> tuple[PassportV2DiffClaim, str | None]:
        if row is None:
            return PassportV2DiffClaim(), "No diff coverage measurement exists."
        raw = row["payload_json"]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
            return PassportV2DiffClaim(), "Diff coverage measurement is oversized."
        try:
            result = DiffCoverageResult.model_validate_json(raw)
        except (ValueError, RecursionError):
            return PassportV2DiffClaim(), "Diff coverage measurement is malformed."
        return PassportV2DiffClaim(
            checks_passed=result.checks_passed, diff_exercised=result.diff_exercised,
            freshness=result.freshness,
            changed_executable_lines=result.changed_executable_lines,
            executed_changed_lines=result.executed_changed_lines,
            measured_percent_text=(format(result.measured_percent, ".6g")
                                   if result.measured_percent is not None else None),
            head_sha=result.head_sha, status_digest=result.status_digest,
            artifact_digest=result.artifact_digest,
            collection_boundary=result.collection_boundary,
        ), None

    def issue(self, change_id: UUID) -> PassportV2Issued:
        """No payload argument exists: CNG signs only this freshly built snapshot."""
        source_payload = self.snapshot(change_id)
        with CngKey.open(name=self._key_name or active_key_name()) as key:
            payload = self._with_provider(source_payload, key.provider)
            message = canonical_payload(payload)
            spki = key.public_spki()
            signature = key.sign(message)
            latest = self.snapshot(change_id)
            if latest.model_dump(exclude={"issued_at"}) != source_payload.model_dump(exclude={"issued_at"}):
                raise AppError("PASSPORT_RECORDS_MOVED",
                               "Change records moved during Passport signing.", status_code=409)
            return PassportV2Issued(
                payload=payload, payload_digest=hashlib.sha256(message).hexdigest(),
                signer_fingerprint=fingerprint(spki),
                signer_public_spki_b64=base64.b64encode(spki).decode("ascii"),
                signer_provider=key.provider,
                signer_identity=f"Sentinel installation {self._label}",
                signature_b64=base64.b64encode(signature).decode("ascii"),
            )

    @staticmethod
    def _with_provider(payload: PassportV2Payload, provider: str) -> PassportV2Payload:
        limitations = list(payload.limitations)
        if provider == "SOFTWARE":
            limitations.append(
                "Software KSP key is non-exportable via CNG but recoverable by a same-user process via DPAPI."
            )
        return PassportV2Payload.model_validate({**payload.model_dump(),
                                                 "signer_provider": provider,
                                                 "limitations": limitations})
