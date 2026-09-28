"""Deterministic, redacted Portable Passport v2 ZIP export for one Change ID."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from uuid import UUID

from backend.app.contracts.models import PassportV2Payload
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.passport.card import render_html, render_svg
from backend.app.passport.cng import CngKey, fingerprint
from backend.app.passport.format import MAX_BUNDLE_BYTES, MAX_MEMBER_BYTES, serialize_archive
from backend.app.passport.jcs import canonicalize
from backend.app.passport.identity import open_signing_key
from backend.app.passport.v2 import PassportV2Issuer

@dataclass(frozen=True, slots=True)
class BundleArtifact:
    filename: str
    content: bytes
    payload_sha256: str
    signer_fingerprint: str


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _member(path: str, content: bytes, media_type: str) -> dict[str, object]:
    if len(content) > MAX_MEMBER_BYTES:
        raise AppError("PASSPORT_EVIDENCE_LIMIT", "Portable Passport member is oversized.",
                       status_code=409)
    return {"path": path, "sha256": _sha256(content), "size": len(content),
            "media_type": media_type}


class BundleExporter:
    """Export only allowlisted claim fields and record digests from Sentinel DB."""

    def __init__(self, database: Database, *, key_name: str | None = None,
                 installation_label: str = "local") -> None:
        self._database = database
        self._key_name = key_name
        self._issuer = PassportV2Issuer(database, key_name=key_name,
                                        installation_label=installation_label)
        self._identity = f"Sentinel installation {installation_label.strip()}"

    def _journal_links(self, change_id: UUID, *, expected_count: int,
                       expected_head: str | None) -> bytes | None:
        if expected_count == 0:
            return None
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT seq, prev_event_hash, event_hash FROM journal_events "
                "WHERE change_id = ? ORDER BY seq LIMIT 4097", (str(change_id),)).fetchall()
        if len(rows) != expected_count or rows[-1]["event_hash"] != expected_head:
            raise AppError("PASSPORT_RECORDS_MOVED", "Journal moved during export.",
                           status_code=409)
        previous: str | None = None
        lines: list[bytes] = []
        for number, row in enumerate(rows, start=1):
            if row["seq"] != number or row["prev_event_hash"] != previous:
                raise AppError("PASSPORT_JOURNAL_INVALID", "Journal links are discontinuous.",
                               status_code=409)
            lines.append(canonicalize({"seq": number, "prev_event_hash": previous,
                                       "event_hash": row["event_hash"]}) + b"\n")
            previous = row["event_hash"]
        joined = b"".join(lines)
        if len(joined) > MAX_MEMBER_BYTES:
            raise AppError("PASSPORT_EVIDENCE_LIMIT", "Journal link export is oversized.",
                           status_code=409)
        return joined

    def export(self, change_id: UUID) -> BundleArtifact:
        """Create and sign a bundle; no payload or evidence parameter is accepted."""
        source_claims = self._issuer.snapshot(change_id)
        claims = source_claims
        journal = self._journal_links(change_id, expected_count=claims.journal_event_count,
                                      expected_head=claims.journal_head)
        with (CngKey.open(name=self._key_name) if self._key_name else open_signing_key()) as key:
            claims = self._issuer._with_provider(claims, key.provider)
            spki = key.public_spki()
            signer_fp = fingerprint(spki)
            passport = {
                "schema_version": 2,
                "claims": claims.model_dump(mode="json"),
                "signer": {"fingerprint": signer_fp, "provider": key.provider,
                           "identity": self._identity},
            }
            payload = canonicalize(passport)
            payload_digest = _sha256(payload)
            evidence = canonicalize({
                "schema_version": 1,
                "journal_head": claims.journal_head,
                "journal_event_count": claims.journal_event_count,
                "launch_records": [item.model_dump(mode="json") for item in claims.launch_records],
                "diff_artifact_digest": claims.diff_coverage.artifact_digest,
            })
            members: list[tuple[str, bytes, str]] = [
                ("passport.json", payload, "application/json"),
                ("evidence/records.json", evidence, "application/json"),
            ]
            if journal is not None:
                members.append(("journal/events.jsonl", journal, "application/x-ndjson"))
            members.extend([
                ("visuals/passport.svg", render_svg(passport, payload_digest=payload_digest),
                 "image/svg+xml"),
                ("visuals/passport.html", render_html(passport, payload_digest=payload_digest),
                 "text/html"),
            ])
            manifest = canonicalize({
                "schema_version": 2, "change_id": str(change_id),
                "payload_sha256": payload_digest,
                "members": [_member(path, content, media_type)
                            for path, content, media_type in members],
            })
            signature = canonicalize({
                "schema_version": 2, "algorithm": "ES256", "fingerprint": signer_fp,
                "provider": key.provider,
                "public_spki_b64": base64.b64encode(spki).decode("ascii"),
                "signature_b64": base64.b64encode(key.sign(manifest)).decode("ascii"),
            })
            latest = self._issuer.snapshot(change_id)
            if latest.model_dump(exclude={"issued_at"}) != source_claims.model_dump(exclude={"issued_at"}):
                raise AppError("PASSPORT_RECORDS_MOVED", "Change moved during export.",
                               status_code=409)
        data = serialize_archive([("manifest.json", manifest),
                                  *[(name, body) for name, body, _ in members],
                                  ("signature.json", signature)])
        if len(data) > MAX_BUNDLE_BYTES:
            raise AppError("PASSPORT_EVIDENCE_LIMIT", "Portable Passport is oversized.",
                           status_code=409)
        return BundleArtifact(filename=f"change-{change_id}.sentinel", content=data,
                              payload_sha256=payload_digest,
                              signer_fingerprint=signer_fp)
