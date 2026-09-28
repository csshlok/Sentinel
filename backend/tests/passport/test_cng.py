"""Windows CNG key-protection and public verification regressions."""

from __future__ import annotations

import base64
import ctypes
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
def test_unavailable_platform_provider_fails_closed_before_new_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cng, "PLATFORM_PROVIDER", "Unavailable Sentinel test KSP")
    name = f"Sentinel disposable test {uuid4()}"
    with pytest.raises(cng.CngError, match="NCryptOpenStorageProvider\\(Platform\\)"):
        CngKey.open(name=name)


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_platform_outage_cannot_switch_an_existing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=name) as original:
        original_spki = original.public_spki()
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(cng, "PLATFORM_PROVIDER", "Unavailable Sentinel test KSP")
            with pytest.raises(cng.CngError, match="NCryptOpenStorageProvider\\(Platform\\)"):
                CngKey.open(name=name)
        with CngKey.open(name=name) as reopened:
            assert reopened.public_spki() == original_spki
    finally:
        with CngKey.open(name=name) as key:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_transient_platform_creation_failure_does_not_create_software_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_dll = cng._api()
    attempted: list[str] = []

    class FakeDll:
        platform_handle: int | None = None

        def NCryptOpenStorageProvider(self, output, label, flags):
            status = real_dll.NCryptOpenStorageProvider(output, label, flags)
            if label == cng.PLATFORM_PROVIDER and status == 0:
                self.platform_handle = output._obj.value
            return status

        def NCryptCreatePersistedKey(self, handle, *args):
            attempted.append("platform" if handle.value == self.platform_handle else "software")
            if handle.value == self.platform_handle:
                return 0x80290401  # TPM device temporarily not ready
            return real_dll.NCryptCreatePersistedKey(handle, *args)

        def __getattr__(self, name):
            return getattr(real_dll, name)

    monkeypatch.setattr(cng, "_api", lambda: FakeDll())
    with pytest.raises(cng.CngError, match="NCryptCreatePersistedKey\\(Platform\\)"):
        CngKey.open(name=f"Sentinel disposable test {uuid4()}")
    assert attempted == ["platform"]


def test_fingerprint_is_sha256_of_spki() -> None:
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    spki = public.public_bytes(serialization.Encoding.DER,
                               serialization.PublicFormat.SubjectPublicKeyInfo)
    expected = base64.b32encode(hashlib.sha256(spki).digest()).decode("ascii").rstrip("=")
    assert fingerprint(spki).replace("-", "") == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_existing_exportable_key_is_rejected() -> None:
    dll = cng._api()
    provider = ctypes.c_void_p()
    key = ctypes.c_void_p()
    name = f"Sentinel disposable test {uuid4()}"
    assert dll.NCryptOpenStorageProvider(ctypes.byref(provider), cng.SOFTWARE_PROVIDER, 0) == 0
    try:
        assert dll.NCryptCreatePersistedKey(provider, ctypes.byref(key),
                                             "ECDSA_P256", name, 0, 0) == 0
        policy = cng.wintypes.DWORD(1)
        assert dll.NCryptSetProperty(key, "Export Policy", ctypes.byref(policy),
                                      ctypes.sizeof(policy), 0) == 0
        assert dll.NCryptFinalizeKey(key, 0) == 0
        with pytest.raises(cng.CngError, match="exportable"):
            CngKey.open(name=name)
    finally:
        if key.value:
            dll.NCryptDeleteKey(key, 0)
        if provider.value:
            dll.NCryptFreeObject(provider)
