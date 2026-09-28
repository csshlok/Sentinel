"""Recipient trust is explicit, local and independent of signature validity."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.passport.cng import CngKey, fingerprint
from backend.app.passport.trust import TrustRegistry, normalize_fingerprint


def _spki() -> bytes:
    return ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def test_add_list_remove_and_revoke(tmp_path: Path) -> None:
    registry = TrustRegistry(tmp_path / "trusted_keys.json")
    spki = _spki()
    value = fingerprint(spki)
    assert registry.decision(spki=spki) == ("UNTRUSTED", None)
    assert registry.add(fingerprint_value=value.replace("-", ""), label="Lab") == value
    assert registry.decision(spki=spki) == ("TRUSTED", "Sentinel installation Lab")
    assert registry.list()[0]["fingerprint"] == value
    assert registry.remove(value)
    assert registry.decision(spki=spki) == ("UNTRUSTED", None)
    registry.add(spki=spki, label="Lab")
    registry.revoke(value, reason="Compromised")
    assert registry.decision(spki=spki) == ("REVOKED", None)
    with pytest.raises(ValueError, match="Revoked"):
        registry.add(spki=spki, label="Lab")


def test_wrong_fingerprint_and_malformed_registry_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "trusted_keys.json"
    registry = TrustRegistry(path)
    first, second = _spki(), _spki()
    with pytest.raises(ValueError, match="does not match"):
        registry.add(spki=first, fingerprint_value=fingerprint(second), label="Lab")
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        registry.decision(spki=first)
    path.write_text('{"schema_version":1,"keys":{},"keys":{},"revoked":{},"rotations":[]}',
                    encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        registry.decision(spki=first)
    with pytest.raises(ValueError):
        normalize_fingerprint("not a fingerprint")


def test_noncanonical_revocation_cannot_fail_open(tmp_path: Path) -> None:
    spki = _spki()
    value = fingerprint(spki)
    path = tmp_path / "trusted_keys.json"
    registry = TrustRegistry(path)
    registry.add(spki=spki, label="Lab")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["revoked"] = {value.replace("-", "").lower(): {"reason": "compromised"}}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed trust registry entries"):
        registry.decision(spki=spki)


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_rotation_requires_valid_old_key_and_trust(tmp_path: Path) -> None:
    registry = TrustRegistry(tmp_path / "trusted_keys.json")
    old_name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=old_name) as old:
        try:
            old_spki = old.public_spki()
            new_spki = _spki()
            statement = registry.sign_rotation(old_key=old, new_spki=new_spki)
            with pytest.raises(ValueError, match="not trusted"):
                registry.apply_rotation(statement)
            registry.add(spki=old_spki, label="Office")
            forged = {**statement, "new_spki": base64.b64encode(_spki()).decode("ascii")}
            with pytest.raises(ValueError, match="Malformed"):
                registry.apply_rotation(forged)
            assert registry.apply_rotation(statement) == fingerprint(new_spki)
            assert registry.decision(spki=new_spki) == (
                "TRUSTED", "Sentinel installation Office")
            assert registry._read()["rotations"] == [statement]
        finally:
            old.delete_for_test()
