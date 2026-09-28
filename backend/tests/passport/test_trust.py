"""Recipient trust is explicit, local and independent of signature validity."""

from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.passport.cng import CngKey, fingerprint
from backend.app.passport.trust import TrustRegistry, normalize_fingerprint
import backend.app.passport.trust as trust_module


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


def test_concurrent_registry_mutations_preserve_both_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "trusted_keys.json"
    first, second = _spki(), _spki()
    registry_a, registry_b = TrustRegistry(path), TrustRegistry(path)
    first_read = threading.Event()
    original = registry_a._read

    def delayed_read():
        data = original()
        first_read.set()
        threading.Event().wait(0.25)
        return data

    monkeypatch.setattr(registry_a, "_read", delayed_read)
    thread_a = threading.Thread(target=lambda: registry_a.add(spki=first, label="A"))
    thread_b = threading.Thread(target=lambda: registry_b.add(spki=second, label="B"))
    thread_a.start()
    assert first_read.wait(2)
    thread_b.start()
    thread_a.join(3)
    thread_b.join(3)
    assert not thread_a.is_alive() and not thread_b.is_alive()
    assert {item["fingerprint"] for item in TrustRegistry(path).list()} == {
        fingerprint(first), fingerprint(second),
    }


def test_default_named_trust_directory_uses_protected_store_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "Sentinel" / "trusted_keys.json"
    calls: list[Path] = []

    def protected(directory: Path) -> bool:
        calls.append(directory)
        directory.mkdir(parents=True, exist_ok=True)
        return True

    monkeypatch.setattr(trust_module, "prepare_store_directory", protected)
    TrustRegistry(path).add(spki=_spki(), label="Lab")
    assert calls and all(directory == path.parent for directory in calls)
    monkeypatch.setattr(trust_module, "prepare_store_directory", lambda _path: False)
    with pytest.raises(OSError, match="permissions"):
        TrustRegistry(path).list()


def test_equivalent_compressed_spki_keeps_the_same_pin(tmp_path: Path) -> None:
    canonical = _spki()
    assert canonical[:2] == b"\x30\x59" and canonical[26] == 4
    x, y = canonical[27:59], canonical[59:91]
    compressed = b"\x30\x39" + canonical[2:23] + b"\x03\x22\x00" + bytes([2 | (y[-1] & 1)]) + x
    registry = TrustRegistry(tmp_path / "trusted_keys.json")
    registry.add(spki=compressed, label="Lab")
    assert fingerprint(compressed) == fingerprint(canonical)
    assert registry.decision(spki=canonical) == ("TRUSTED", "Sentinel installation Lab")


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


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_rotation_cannot_steal_identity_and_revocation_cascades(tmp_path: Path) -> None:
    registry = TrustRegistry(tmp_path / "trusted_keys.json")
    old_name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=old_name) as old:
        try:
            old_spki, successor = old.public_spki(), _spki()
            registry.add(spki=old_spki, label="Office")
            registry.add(spki=successor, label="Release")
            statement = registry.sign_rotation(old_key=old, new_spki=successor)
            with pytest.raises(ValueError, match="already trusted"):
                registry.apply_rotation(statement)
            assert registry.decision(spki=successor) == (
                "TRUSTED", "Sentinel installation Release")
            registry.remove(fingerprint(successor))
            registry.apply_rotation(statement)
            assert registry.decision(spki=old_spki)[0] == "UNTRUSTED"
            registry.revoke(fingerprint(old_spki))
            assert registry.decision(spki=successor)[0] == "REVOKED"
        finally:
            old.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_rotation_rejects_consistent_key_pair_with_bad_signature(tmp_path: Path) -> None:
    registry = TrustRegistry(tmp_path / "trusted_keys.json")
    old_name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=old_name) as old:
        try:
            registry.add(spki=old.public_spki(), label="Office")
            statement = registry.sign_rotation(old_key=old, new_spki=_spki())
            signature = bytearray(base64.b64decode(statement["signature"]))
            signature[-1] ^= 1
            statement["signature"] = base64.b64encode(signature).decode("ascii")
            with pytest.raises(ValueError, match="Invalid key rotation signature"):
                registry.apply_rotation(statement)
        finally:
            old.delete_for_test()
