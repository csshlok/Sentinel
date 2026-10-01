"""Issue Passport v2 claims only from a Change ID and persisted Sentinel rows."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from uuid import UUID

from backend.app.contracts.models import (
    ChangeContract,
    DiffCoverageResult,
    GitCheckpoint,
    PassportV2DiffClaim,
    PassportV2Issued,
    PassportV2LaunchBinding,
    PassportV2Payload,
    utc_now,
)
from backend.app.core.database import Database
from backend.app.core.errors import AppError, change_not_found
from backend.app.core.journal import compute_event_hash
from backend.app.execution.check_repository import (
    CheckRunRepository, check_run_events, confined_checks_fact,
)
from backend.app.git.state import GitStateTracker
from backend.app.policy.path_evidence import documentation_paths
from backend.app.passport.cng import CngKey, fingerprint
from backend.app.passport.jcs import canonicalize
from backend.app.passport.identity import open_signing_key
from backend.app.policy.presets import PresetEvidence, evaluate_preset
from backend.app.policy.version import product_version

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
            check_runs = CheckRunRepository(self._database).for_change(
                change_id, connection=connection)
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
        contract_raw = change["contract_json"]
        if isinstance(contract_raw, str) and len(contract_raw.encode("utf-8")) > _MAX_RECORD_BYTES:
            raise AppError("PASSPORT_CONTRACT_INVALID", "Change Contract is oversized.",
                           status_code=409)
        try:
            contract = (ChangeContract.model_validate_json(contract_raw)
                        if isinstance(contract_raw, str) else ChangeContract())
        except (ValueError, RecursionError) as exc:
            raise AppError("PASSPORT_CONTRACT_INVALID", "Change Contract is malformed.",
                           status_code=409) from exc
        comparable = contract.model_dump(mode="json")
        if contract.schema_version == 1:
            comparable.pop("diff_coverage_rule", None)
        if contract.schema_version < 3:
            comparable.pop("policy_preset_name", None)
            comparable.pop("policy_change_type", None)
        coverage_contract_digest = hashlib.sha256(json.dumps(
            comparable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        diff_claim, diff_limit, changed_paths, measured_percent = self._coverage_claim(
            coverage, coverage_contract_digest)
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
        confined_checks, confined_limit = self._confined_checks(coverage, journal, check_runs)
        if confined_limit:
            limitations.append(confined_limit)
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
            issued_at=utc_now(), product_version=product_version(),
            confined_checks=confined_checks,
        )
        payload = self._checked_freshness(change_id, payload, change)
        if contract.policy_preset_name is None or contract.policy_change_type is None:
            return payload.model_copy(update={
                "policy_denials": ["No versioned policy preset is selected."],
            })
        preset_paths = changed_paths
        mode_paths: tuple[str, ...] = ()
        path_error: str | None = None
        if contract.policy_change_type == "docs":
            preset_paths, mode_paths, path_error = self._preset_paths(
                change_id, change["repository_path"], coverage)
        decision = evaluate_preset(
            preset_name=contract.policy_preset_name,
            change_type=contract.policy_change_type,
            evidence=PresetEvidence(
                checks_passed=payload.diff_coverage.checks_passed,
                diff_exercised=payload.diff_coverage.diff_exercised,
                measured_percent=measured_percent,
                freshness=payload.diff_coverage.freshness,
                changed_paths=preset_paths,
                mode_changed_paths=mode_paths,
                path_evidence_error=path_error,
                execution_boundary=payload.execution_boundary,
                confined_checks=payload.confined_checks,
            ),
        )
        return payload.model_copy(update={
            "policy_preset_name": contract.policy_preset_name,
            "policy_preset_version": decision.preset_version,
            "policy_change_type": contract.policy_change_type,
            "policy_decision": decision.status,
            "policy_denials": list(decision.reasons),
        })

    def _preset_paths(self, change_id: UUID, root: str, coverage: object | None) -> tuple[
        tuple[str, ...], tuple[str, ...], str | None,
    ]:
        if coverage is None:
            return (), (), "coverage checkpoints are absent"
        try:
            result = DiffCoverageResult.model_validate_json(coverage["payload_json"])
            with self._database.connection() as connection:
                records = [connection.execute(
                    "SELECT payload_json FROM git_checkpoints WHERE id = ? AND change_id = ?",
                    (str(identifier), str(change_id))).fetchone()
                    for identifier in (result.baseline_checkpoint_id, result.tested_checkpoint_id)]
            if any(record is None for record in records):
                return (), (), "bound checkpoint is missing"
            baseline, tested = (GitCheckpoint.model_validate_json(record["payload_json"])
                                for record in records)
            if tested.repository_root != root or tested.head_sha != result.head_sha:
                return (), (), "tested checkpoint does not match coverage"
            return documentation_paths(baseline, tested)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            return (), (), f"bound checkpoint inspection failed ({type(exc).__name__})"

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
    def _confined_checks(coverage: object | None, journal: list[object],
                         check_runs: list[object]) -> tuple[str, str | None]:
        """Phase 5: the bound coverage run's observed check boundary (hash-verified journal)."""
        bound: list[tuple[UUID | None, str | None]] = []
        if coverage is not None:
            try:
                result = DiffCoverageResult.model_validate_json(coverage["payload_json"])
            except (ValueError, TypeError, RecursionError):
                return "UNKNOWN", "Confined checks UNKNOWN: the coverage record is malformed."
            bound.append((result.check_run_id, result.boundary))
        fact, reason = confined_checks_fact(
            bound, records={record.id: record for record in check_runs},
            events=check_run_events((row["event_type"], row["subject_id"], row["payload_json"])
                                    for row in journal))
        return fact, (f"Confined checks {fact}: {reason}." if reason else None)

    @staticmethod
    def _coverage_claim(row: object | None,
                        expected_contract_digest: str) -> tuple[
                            PassportV2DiffClaim, str | None, tuple[str, ...], float | None]:
        if row is None:
            return PassportV2DiffClaim(), "No diff coverage measurement exists.", (), None
        raw = row["payload_json"]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_RECORD_BYTES:
            return PassportV2DiffClaim(), "Diff coverage measurement is oversized.", (), None
        try:
            result = DiffCoverageResult.model_validate_json(raw)
        except (ValueError, RecursionError):
            return PassportV2DiffClaim(), "Diff coverage measurement is malformed.", (), None
        changed_contract = result.contract_digest != expected_contract_digest
        paths = tuple(sorted({item.path for item in result.files} | set(result.excluded)))
        return PassportV2DiffClaim(
            checks_passed=result.checks_passed,
            diff_exercised="STALE" if changed_contract else result.diff_exercised,
            freshness="STALE" if changed_contract else result.freshness,
            changed_executable_lines=result.changed_executable_lines,
            executed_changed_lines=result.executed_changed_lines,
            measured_percent_text=(format(result.measured_percent, ".6g")
                                   if result.measured_percent is not None else None),
            head_sha=result.head_sha, status_digest=result.status_digest,
            artifact_digest=result.artifact_digest,
            collection_boundary=result.collection_boundary,
        ), ("Change Contract changed after diff coverage measurement."
            if changed_contract else None), paths, result.measured_percent

    def issue(self, change_id: UUID) -> PassportV2Issued:
        """No payload argument exists: CNG signs only this freshly built snapshot."""
        source_payload = self.snapshot(change_id)
        with (CngKey.open(name=self._key_name) if self._key_name else open_signing_key()) as key:
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
