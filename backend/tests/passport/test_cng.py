"""Windows CNG key-protection and public verification regressions."""

from __future__ import annotations

import base64
import hashlib
import os
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.passport.cng import CngKey, fingerprint, verify_signature
import backend.app.passport.cng as cng


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_persisted_es256_key_is_nonexportable_and_publicly_verifiable() -> None:
    name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=name) as first:
        try:
            spki = first.public_spki()
            message = b"Sentinel Passport v2 test"
            signature = first.sign(message)
            assert first.provider in {"TPM", "SOFTWARE"}
            first._assert_nonexportable()
            assert verify_signature(spki=spki, message=message, signature=signature)
            assert not verify_signature(spki=spki, message=message + b"!", signature=signature)
            assert not verify_signature(spki=spki, message=message,
                                        signature=signature[:-1] + bytes([signature[-1] ^ 1]))
            assert fingerprint(spki).replace("-", "").isalnum()
            assert len(fingerprint(spki).replace("-", "")) == 52
        finally:
            first.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_existing_key_reopens_without_rotation() -> None:
    name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=name) as first:
        spki = first.public_spki()
        provider = first.provider
    with CngKey.open(name=name) as second:
        try:
            assert second.public_spki() == spki
            assert second.provider == provider
            assert fingerprint(spki) == fingerprint(second.public_spki())
        finally:
            second.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_unavailable_platform_provider_falls_back_to_software(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cng, "PLATFORM_PROVIDER", "Unavailable Sentinel test KSP")
    name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=name) as key:
        try:
            assert key.provider == "SOFTWARE"
            assert verify_signature(spki=key.public_spki(), message=b"fallback",
                                    signature=key.sign(b"fallback"))
        finally:
            key.delete_for_test()


def test_fingerprint_is_sha256_of_spki() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    spki = public.public_bytes(serialization.Encoding.DER,
                               serialization.PublicFormat.SubjectPublicKeyInfo)
    expected = base64.b32encode(hashlib.sha256(spki).digest()).decode("ascii").rstrip("=")
    assert fingerprint(spki).replace("-", "") == expected
