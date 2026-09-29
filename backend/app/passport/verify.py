"""Offline Portable Passport verifier; a sender database is never opened."""

from __future__ import annotations

import base64
import hashlib
import io
import re
import struct
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from backend.app.contracts.models import PassportV2Payload
from backend.app.passport.card import render_html, render_svg
from backend.app.passport.cng import fingerprint, verify_signature
from backend.app.passport.format import (
    MAX_BUNDLE_BYTES, MAX_MEMBER_BYTES, serialize_archive,
)
from backend.app.passport.jcs import canonicalize, parse_canonical
from backend.app.passport.trust import TrustRegistry, normalize_fingerprint

_MAX_ENTRIES = 7
_MAX_RATIO = 100
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPES = {
    "passport.json": "application/json",
    "evidence/records.json": "application/json",
    "journal/events.jsonl": "application/x-ndjson",
    "visuals/passport.svg": "image/svg+xml",
    "visuals/passport.html": "text/html",
}
_EXPECTED_WITH_JOURNAL = [
    "manifest.json", "passport.json", "evidence/records.json",
    "journal/events.jsonl", "visuals/passport.svg", "visuals/passport.html",
    "signature.json",
]
_EXPECTED_WITHOUT_JOURNAL = [name for name in _EXPECTED_WITH_JOURNAL
                             if name != "journal/events.jsonl"]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verdict: Literal["VALID", "INVALID", "INDETERMINATE"]
    reason: str
    change_id: str | None = None
    payload_sha256: str | None = None
    signer_fingerprint: str | None = None
    signer_identity: str | None = None
    trusted_as: str | None = None
    claims: dict[str, object] = field(default_factory=dict)


def _invalid(reason: str) -> VerificationResult:
    return VerificationResult("INVALID", reason)


def _safe_names(infos: list[zipfile.ZipInfo]) -> list[str]:
    if len(infos) > _MAX_ENTRIES:
        raise ValueError("Too many ZIP entries")
    seen: set[str] = set()
    names: list[str] = []
    total = 0
    for info in infos:
        name = info.filename
        if (not name or len(name) > 256 or name.startswith("/") or "\\" in name
                or ":" in name or "\x00" in name or name.endswith("/")):
            raise ValueError("Unsafe ZIP member path")
        if any(segment in {"", ".", ".."} for segment in name.split("/")):
            raise ValueError("Unsafe ZIP member path")
        folded = unicodedata.normalize("NFC", name).casefold()
        if folded in seen:
            raise ValueError("Duplicate normalized ZIP member")
        seen.add(folded)
        if info.flag_bits & 1:
            raise ValueError("Encrypted ZIP member")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("Symlink ZIP member")
        if mode not in {0, 0o100000}:
            raise ValueError("Non-file ZIP member")
        if info.compress_type != zipfile.ZIP_STORED:
            raise ValueError("Unsupported ZIP compression")
        if info.file_size > MAX_MEMBER_BYTES or info.file_size < 0:
            raise ValueError("Oversized ZIP member")
        if info.file_size and (not info.compress_size or
                               info.file_size > _MAX_RATIO * info.compress_size):
            raise ValueError("Excessive ZIP compression ratio")
        if info.extra or info.comment:
            raise ValueError("Unexpected ZIP member metadata")
        total += info.file_size
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Oversized ZIP contents")
        names.append(name)
    if tuple(names) not in {_tuple(_EXPECTED_WITH_JOURNAL), _tuple(_EXPECTED_WITHOUT_JOURNAL)}:
        raise ValueError("Missing, unexpected or out-of-order ZIP member")
    return names


def _tuple(names: list[str]) -> tuple[str, ...]:
    return tuple(names)


def _validate_local_headers(raw: bytes, infos: list[zipfile.ZipInfo],
                            directory_offset: int) -> None:
    """Require the complete local-member region to equal the indexed members."""
    position = 0
    for info in infos:
        if info.header_offset != position or position + 30 > directory_offset:
            raise ValueError("ZIP has hidden data between members")
        (magic, _version, flags, method, _time, _date, crc, compressed,
         uncompressed, name_size, extra_size) = struct.unpack_from("<IHHHHHIIIHH", raw, position)
        if flags & 1:
            raise ValueError("Encrypted ZIP member")
        if method != zipfile.ZIP_STORED:
            raise ValueError("Unsupported ZIP compression")
        if magic != 0x04034B50 or flags != info.flag_bits or flags & ~0x800:
            raise ValueError("Local ZIP header differs from central directory")
        if (method != zipfile.ZIP_STORED or method != info.compress_type
                or (crc, compressed, uncompressed) !=
                (info.CRC, info.compress_size, info.file_size) or extra_size):
            raise ValueError("Local ZIP header differs from central directory")
        name = raw[position + 30:position + 30 + name_size]
        if b"\\" in name or b":" in name:
            raise ValueError("Unsafe ZIP member path")
        expected = info.filename.encode("utf-8")
        if name != expected:
            raise ValueError("Local ZIP name differs from central directory")
        position += 30 + name_size + info.compress_size
        if position > directory_offset:
            raise ValueError("ZIP member overlaps central directory")
    if position != directory_offset:
        raise ValueError("ZIP has hidden data before central directory")


def _read_members(archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> dict[str, bytes]:
    content: dict[str, bytes] = {}
    total = 0
    for info in infos:
        with archive.open(info, "r") as stream:
            body = stream.read(MAX_MEMBER_BYTES + 1)
            if len(body) > MAX_MEMBER_BYTES or stream.read(1):
                raise ValueError("Oversized decompressed ZIP member")
        if len(body) != info.file_size:
            raise ValueError("ZIP member size mismatch")
        total += len(body)
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Oversized decompressed ZIP")
        content[info.filename] = body
    return content


def _object(raw: bytes, *, name: str) -> dict[str, object]:
    value = parse_canonical(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _validate_manifest(manifest: dict[str, object], content: dict[str, bytes],
                       names: list[str]) -> str:
    if set(manifest) != {"schema_version", "change_id", "payload_sha256", "members"}:
        raise ValueError("Manifest schema mismatch")
    if manifest["schema_version"] != 2:
        raise ValueError("Unsupported manifest schema")
    UUID(str(manifest["change_id"]))
    payload_digest = manifest["payload_sha256"]
    if not isinstance(payload_digest, str) or not _DIGEST.fullmatch(payload_digest):
        raise ValueError("Invalid payload digest")
    if hashlib.sha256(content["passport.json"]).hexdigest() != payload_digest:
        raise ValueError("Passport payload digest mismatch")
    members = manifest["members"]
    if not isinstance(members, list) or len(members) != len(names) - 2:
        raise ValueError("Manifest member list mismatch")
    for record, name in zip(members, names[1:-1], strict=True):
        if not isinstance(record, dict) or set(record) != {
                "path", "sha256", "size", "media_type"} or record["path"] != name:
            raise ValueError("Manifest member metadata mismatch")
        if not isinstance(record["sha256"], str) or not _DIGEST.fullmatch(record["sha256"]):
            raise ValueError("Invalid manifest member digest")
        if record["size"] != len(content[name]) or record["sha256"] != hashlib.sha256(
                content[name]).hexdigest():
            raise ValueError(f"Member digest or size mismatch: {name}")
        if record["media_type"] != _MEDIA_TYPES[name]:
            raise ValueError("Invalid member media type")
    return payload_digest


def _validate_claims(passport: dict[str, object], manifest: dict[str, object],
                     content: dict[str, bytes], payload_digest: str) -> PassportV2Payload:
    if set(passport) != {"schema_version", "claims", "signer"} or passport["schema_version"] != 2:
        raise ValueError("Unsupported Passport schema")
    claims = PassportV2Payload.model_validate(passport["claims"])
    normalized = claims.model_dump(mode="json")
    if "signer_provider" not in passport["claims"]:
        normalized.pop("signer_provider")  # pre-additive v2 bundles remain verifiable
    for field in ("policy_preset_name", "policy_preset_version", "policy_change_type",
                  "policy_decision", "policy_denials", "product_version"):
        if field not in passport["claims"]:
            normalized.pop(field)
    if canonicalize(normalized) != canonicalize(passport["claims"]):
        raise ValueError("Passport claim normalization mismatch")
    if str(claims.change_id) != manifest["change_id"]:
        raise ValueError("Passport Change ID mismatch")
    if content["visuals/passport.html"] != render_html(passport, payload_digest=payload_digest):
        raise ValueError("HTML card differs from signed claims")
    if content["visuals/passport.svg"] != render_svg(passport, payload_digest=payload_digest):
        raise ValueError("SVG card differs from signed claims")
    evidence = _object(content["evidence/records.json"], name="Evidence")
    expected_evidence = {
        "schema_version": 1,
        "journal_head": claims.journal_head,
        "journal_event_count": claims.journal_event_count,
        "launch_records": [item.model_dump(mode="json") for item in claims.launch_records],
        "diff_artifact_digest": claims.diff_coverage.artifact_digest,
    }
    if evidence != expected_evidence:
        raise ValueError("Evidence references differ from Passport claims")
    raw_journal = content.get("journal/events.jsonl")
    if (claims.journal_event_count > 0) != (raw_journal is not None):
        raise ValueError("Journal link export does not match claim")
    if raw_journal is not None:
        if not raw_journal.endswith(b"\n"):
            raise ValueError("Journal link export is malformed")
        lines = raw_journal[:-1].split(b"\n")
        if len(lines) != claims.journal_event_count:
            raise ValueError("Journal link count mismatch")
        previous: str | None = None
        for expected_seq, line in enumerate(lines, start=1):
            item = _object(line, name="Journal link")
            if set(item) != {"seq", "prev_event_hash", "event_hash"}:
                raise ValueError("Journal link schema mismatch")
            if (item["seq"] != expected_seq or item["prev_event_hash"] != previous
                    or not isinstance(item["event_hash"], str)
                    or not _DIGEST.fullmatch(item["event_hash"])):
                raise ValueError("Journal link mismatch")
            previous = item["event_hash"]
        if previous != claims.journal_head:
            raise ValueError("Journal head mismatch")
    return claims


def _claims_summary(claims: PassportV2Payload) -> dict[str, object]:
    diff = claims.diff_coverage
    return {
        "checks_passed": diff.checks_passed,
        "diff_exercised": diff.diff_exercised,
        "freshness": diff.freshness,
        "changed_executable_lines": diff.changed_executable_lines,
        "executed_changed_lines": diff.executed_changed_lines,
        "execution_boundary": claims.execution_boundary,
        "runs_later": claims.runs_later,
        "journal_integrity": claims.journal_integrity,
        "limitations": claims.limitations,
        "policy_preset_name": claims.policy_preset_name,
        "policy_preset_version": claims.policy_preset_version,
        "policy_decision": claims.policy_decision,
        "policy_denials": claims.policy_denials,
        "product_version": claims.product_version,
    }


def verify_bundle(path: Path, *, trust: TrustRegistry | None = None,
                  expected_fingerprint: str | None = None) -> VerificationResult:
    """Validate structure, every object, signature and explicit recipient trust."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle is missing or oversized")
        with path.open("rb") as stream:
            raw_zip = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(raw_zip) > MAX_BUNDLE_BYTES:
            raise ValueError("Bundle is oversized")
        if (not raw_zip.startswith(b"PK\x03\x04") or len(raw_zip) < 22
                or raw_zip[-22:-18] != b"PK\x05\x06" or raw_zip[-2:] != b"\x00\x00"):
            raise ValueError("ZIP has a prefix, trailer or archive comment")
        directory_size = int.from_bytes(raw_zip[-10:-6], "little")
        directory_offset = int.from_bytes(raw_zip[-6:-2], "little")
        if directory_offset + directory_size != len(raw_zip) - 22:
            raise ValueError("ZIP central directory has an unexpected boundary")
        if (raw_zip[-18:-14] != b"\x00\x00\x00\x00"
                or raw_zip[-14:-12] != raw_zip[-12:-10]):
            raise ValueError("ZIP central directory counts or disk mismatch")
        with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as archive:
            if archive.comment:
                raise ValueError("Unexpected ZIP archive comment")
            infos = archive.infolist()
            if int.from_bytes(raw_zip[-12:-10], "little") != len(infos):
                raise ValueError("ZIP central directory entry count mismatch")
            _validate_local_headers(raw_zip, infos, directory_offset)
            names = _safe_names(infos)
            content = _read_members(archive, infos)
        expected_zip = serialize_archive([(name, content[name]) for name in names])
        if raw_zip != expected_zip:
            raise ValueError("ZIP differs from the canonical exported layout")
        manifest = _object(content["manifest.json"], name="Manifest")
        payload_digest = _validate_manifest(manifest, content, names)
        passport = _object(content["passport.json"], name="Passport")
        claims = _validate_claims(passport, manifest, content, payload_digest)
        signature = _object(content["signature.json"], name="Signature")
        if set(signature) != {"schema_version", "algorithm", "fingerprint", "provider",
                              "public_spki_b64", "signature_b64"}:
            raise ValueError("Signature schema mismatch")
        if signature["schema_version"] != 2 or signature["algorithm"] != "ES256":
            raise ValueError("Unsupported signature schema or algorithm")
        spki = base64.b64decode(signature["public_spki_b64"], validate=True)
        signed = base64.b64decode(signature["signature_b64"], validate=True)
        actual_fp = fingerprint(spki)
        if signature["fingerprint"] != actual_fp:
            raise ValueError("Signature fingerprint mismatch")
        signer = passport["signer"]
        if (not isinstance(signer, dict) or set(signer) != {
                "fingerprint", "provider", "identity"}
                or signer["fingerprint"] != actual_fp
                or signer["provider"] != signature["provider"]
                or signer["provider"] not in {"TPM", "SOFTWARE"}
                or not isinstance(signer["identity"], str)
                or not signer["identity"].startswith("Sentinel installation ")):
            raise ValueError("Signer claims differ from signature")
        if not verify_signature(spki=spki, message=content["manifest.json"], signature=signed):
            raise ValueError("ES256 manifest signature is invalid")
        summary = _claims_summary(claims)
        common = {
            "change_id": str(claims.change_id), "payload_sha256": payload_digest,
            "signer_fingerprint": actual_fp, "claims": summary,
        }
        try:
            decision, identity = (trust or TrustRegistry()).decision(spki=spki)
        except (OSError, ValueError):
            return VerificationResult("INDETERMINATE", "Recipient trust registry is unavailable.",
                                      **common)
        if decision == "REVOKED":
            return VerificationResult("INDETERMINATE", "Signer is revoked locally.", **common)
        if expected_fingerprint is not None:
            if normalize_fingerprint(expected_fingerprint) != actual_fp:
                return VerificationResult("INDETERMINATE", "Signer does not match the explicit key.",
                                          **common)
            return VerificationResult("VALID", "Signature and explicit key match.",
                                      signer_identity=signer["identity"], trusted_as=identity,
                                      **common)
        if decision != "TRUSTED":
            return VerificationResult("INDETERMINATE", f"Signer is {decision.lower()}.",
                                      **common)
        return VerificationResult("VALID", "Signature, contents and recipient trust verified.",
                                  signer_identity=signer["identity"], trusted_as=identity,
                                  **common)
    except (OSError, ValueError, TypeError, KeyError, AssertionError, RuntimeError,
            RecursionError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        return _invalid(f"Portable Passport invalid: {type(exc).__name__}: {exc}")
    except Exception as exc:
        # Parsing untrusted archives must always produce a verdict, including for
        # decompressor and cryptography exceptions outside the list above.
        return _invalid(f"Portable Passport invalid: {type(exc).__name__}")
