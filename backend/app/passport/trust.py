"""Explicit local trust, revocation and old-key-authorized rotation for ES256.

Trust is recipient-local. A valid signature from an unknown or revoked SPKI is
cryptographically sound but has an indeterminate signer identity.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cryptography.hazmat.primitives import serialization

from backend.app.passport.cng import CngKey, fingerprint, verify_signature

_FINGERPRINT = re.compile(r"^[A-Z2-7]{52}$")
_MAX_STORE_BYTES = 1_048_576
_MAX_KEYS = 256


def default_trust_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OSError("LOCALAPPDATA is required for the Sentinel trust registry")
    return Path(local) / "Sentinel" / "trusted_keys.json"


def normalize_fingerprint(value: str) -> str:
    compact = value.replace("-", "").replace(" ", "").upper()
    if not _FINGERPRINT.fullmatch(compact):
        raise ValueError("Invalid grouped base32 SHA-256 fingerprint")
    return "-".join(compact[index:index + 8] for index in range(0, 52, 8))


def load_public_key(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > 16_384:
        raise ValueError("Public key file missing or oversized")
    raw = path.read_bytes()
    try:
        public = serialization.load_pem_public_key(raw) if raw.startswith(b"-----BEGIN ") else (
            serialization.load_der_public_key(raw))
        return public.public_bytes(serialization.Encoding.DER,
                                   serialization.PublicFormat.SubjectPublicKeyInfo)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid public SPKI") from exc


def _rotation_body(*, old_fingerprint: str, new_fingerprint: str, new_spki: bytes,
                   issued_at: str) -> bytes:
    body = {
        "kind": "sentinel-key-rotation-v1",
        "old_fingerprint": old_fingerprint,
        "new_fingerprint": new_fingerprint,
        "new_spki": base64.b64encode(new_spki).decode("ascii"),
        "issued_at": issued_at,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate trust registry field")
        result[key] = value
    return result


class TrustRegistry:
    """Bounded, atomic recipient trust registry with injectable path."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_trust_path()

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": 1, "keys": {}, "revoked": {}, "rotations": []}
        if self.path.stat().st_size > _MAX_STORE_BYTES:
            raise ValueError("Trust registry is oversized")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"),
                              object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, ValueError, RecursionError) as exc:
            raise ValueError("Trust registry is malformed") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("Unsupported trust registry schema")
        if not isinstance(data.get("keys"), dict) or not isinstance(data.get("revoked"), dict):
            raise ValueError("Malformed trust registry entries")
        if not isinstance(data.get("rotations"), list):
            raise ValueError("Malformed trust rotation records")
        if len(data["keys"]) > _MAX_KEYS or len(data["revoked"]) > _MAX_KEYS:
            raise ValueError("Trust registry has too many entries")
        for key, value in data["keys"].items():
            try:
                canonical = normalize_fingerprint(key)
            except (TypeError, ValueError) as exc:
                raise ValueError("Malformed trust registry entries") from exc
            if (key != canonical or not isinstance(value, dict)
                    or not isinstance(value.get("label"), str)
                    or not value["label"].strip() or len(value["label"]) > 80
                    or any(ord(char) < 32 for char in value["label"])
                    or value.get("spki") is not None
                    and not isinstance(value["spki"], str)):
                raise ValueError("Malformed trust registry entries")
        for key, value in data["revoked"].items():
            try:
                canonical = normalize_fingerprint(key)
            except (TypeError, ValueError) as exc:
                raise ValueError("Malformed trust registry entries") from exc
            if key != canonical or not isinstance(value, dict):
                raise ValueError("Malformed trust registry entries")
        return data

    def _write(self, data: dict[str, object]) -> None:
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")
        if len(encoded) > _MAX_STORE_BYTES:
            raise ValueError("Trust registry is oversized")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".trusted-", suffix=".json",
                                             dir=self.path.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def add(self, *, fingerprint_value: str | None = None, spki: bytes | None = None,
            label: str) -> str:
        if not label.strip() or len(label) > 80 or any(ord(char) < 32 for char in label):
            raise ValueError("A short printable installation label is required")
        if spki is None and fingerprint_value is None:
            raise ValueError("Provide a fingerprint or public key")
        actual = fingerprint(spki) if spki is not None else None
        provided = normalize_fingerprint(fingerprint_value) if fingerprint_value else None
        if actual is not None and provided is not None and actual != provided:
            raise ValueError("Public key does not match fingerprint")
        chosen = actual or provided
        assert chosen is not None
        data = self._read()
        keys = data["keys"]
        revoked = data["revoked"]
        assert isinstance(keys, dict) and isinstance(revoked, dict)
        if chosen in revoked:
            raise ValueError("Revoked key cannot be trusted without an explicit new decision")
        if len(keys) >= _MAX_KEYS and chosen not in keys:
            raise ValueError("Trust registry is full")
        previous = keys.get(chosen)
        if isinstance(previous, dict) and previous.get("spki") and spki is not None:
            if previous["spki"] != base64.b64encode(spki).decode("ascii"):
                raise ValueError("Fingerprint is pinned to a different public key")
        keys[chosen] = {
            "label": label.strip(),
            "spki": base64.b64encode(spki).decode("ascii") if spki is not None else (
                previous.get("spki") if isinstance(previous, dict) else None),
            "added_at": datetime.now(UTC).isoformat(),
        }
        self._write(data)
        return chosen

    def list(self) -> list[dict[str, object]]:
        data = self._read()
        keys = data["keys"]
        revoked = data["revoked"]
        assert isinstance(keys, dict) and isinstance(revoked, dict)
        return [{"fingerprint": key, **value, "revoked": key in revoked}
                for key, value in sorted(keys.items()) if isinstance(value, dict)]

    def remove(self, value: str) -> bool:
        data = self._read()
        keys = data["keys"]
        assert isinstance(keys, dict)
        removed = keys.pop(normalize_fingerprint(value), None) is not None
        if removed:
            self._write(data)
        return removed

    def revoke(self, value: str, *, reason: str = "Local revocation") -> None:
        if not reason or len(reason) > 256:
            raise ValueError("Invalid revocation reason")
        data = self._read()
        revoked = data["revoked"]
        assert isinstance(revoked, dict)
        if len(revoked) >= _MAX_KEYS and normalize_fingerprint(value) not in revoked:
            raise ValueError("Revocation list is full")
        revoked[normalize_fingerprint(value)] = {
            "reason": reason, "revoked_at": datetime.now(UTC).isoformat(),
        }
        self._write(data)

    def decision(self, *, spki: bytes) -> tuple[Literal["TRUSTED", "UNTRUSTED", "REVOKED", "MISMATCH"], str | None]:
        key = fingerprint(spki)
        data = self._read()
        keys = data["keys"]
        revoked = data["revoked"]
        assert isinstance(keys, dict) and isinstance(revoked, dict)
        if key in revoked:
            return "REVOKED", None
        record = keys.get(key)
        if not isinstance(record, dict):
            return "UNTRUSTED", None
        pinned = record.get("spki")
        if pinned is not None and pinned != base64.b64encode(spki).decode("ascii"):
            return "MISMATCH", None
        label = record.get("label")
        if not isinstance(label, str) or not label:
            return "UNTRUSTED", None
        return "TRUSTED", f"Sentinel installation {label}"

    def sign_rotation(self, *, old_key: CngKey, new_spki: bytes) -> dict[str, str]:
        old_spki = old_key.public_spki()
        issued_at = datetime.now(UTC).isoformat()
        old_fp, new_fp = fingerprint(old_spki), fingerprint(new_spki)
        body = _rotation_body(old_fingerprint=old_fp, new_fingerprint=new_fp,
                              new_spki=new_spki, issued_at=issued_at)
        return {
            "old_fingerprint": old_fp, "old_spki": base64.b64encode(old_spki).decode("ascii"),
            "new_fingerprint": new_fp, "new_spki": base64.b64encode(new_spki).decode("ascii"),
            "issued_at": issued_at,
            "signature": base64.b64encode(old_key.sign(body)).decode("ascii"),
        }

    def apply_rotation(self, statement: dict[str, str]) -> str:
        try:
            old_spki = base64.b64decode(statement["old_spki"], validate=True)
            new_spki = base64.b64decode(statement["new_spki"], validate=True)
            signature = base64.b64decode(statement["signature"], validate=True)
            old_fp = normalize_fingerprint(statement["old_fingerprint"])
            new_fp = normalize_fingerprint(statement["new_fingerprint"])
            issued_at = statement["issued_at"]
            if fingerprint(old_spki) != old_fp or fingerprint(new_spki) != new_fp:
                raise ValueError("Rotation fingerprint mismatch")
            body = _rotation_body(old_fingerprint=old_fp, new_fingerprint=new_fp,
                                  new_spki=new_spki, issued_at=issued_at)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Malformed key rotation statement") from exc
        if not verify_signature(spki=old_spki, message=body, signature=signature):
            raise ValueError("Invalid key rotation signature")
        decision, label = self.decision(spki=old_spki)
        if decision != "TRUSTED" or label is None:
            raise ValueError("Old rotation key is not trusted")
        data = self._read()
        keys = data["keys"]
        revoked = data["revoked"]
        rotations = data["rotations"]
        assert isinstance(keys, dict) and isinstance(revoked, dict) and isinstance(rotations, list)
        if new_fp in revoked or (len(keys) >= _MAX_KEYS and new_fp not in keys):
            raise ValueError("New rotation key cannot be trusted")
        if len(rotations) >= _MAX_KEYS:
            raise ValueError("Too many rotation statements")
        keys[new_fp] = {
            "label": label.removeprefix("Sentinel installation "),
            "spki": base64.b64encode(new_spki).decode("ascii"),
            "added_at": datetime.now(UTC).isoformat(),
        }
        rotations.append(statement)
        self._write(data)
        return new_fp
