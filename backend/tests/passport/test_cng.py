"""Windows CNG key-protection and public verification regressions."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import threading
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.app.passport.cng import CngKey, fingerprint, verify_signature
import backend.app.passport.cng as cng
from backend.tests.passport.hosted_cng import platform_device_not_ready


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
    if platform_device_not_ready():
        pytest.skip("Hosted runner cannot open the Platform KSP for creation testing")
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


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_first_use_key_open_is_serialized_across_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    original = CngKey._open_unlocked.__func__
    active = 0
    peak = 0
    guard = threading.Lock()
    name = f"Sentinel disposable test {uuid4()}"
    identities: list[bytes] = []
    errors: list[Exception] = []

    def observed(cls, *, name: str, create_if_missing: bool = True):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.15)
            return original(cls, name=name, create_if_missing=create_if_missing)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(CngKey, "_open_unlocked", classmethod(observed))

    def worker() -> None:
        try:
            with CngKey.open(name=name) as key:
                identities.append(key.public_spki())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    try:
        assert not errors and len(identities) == 2
        assert identities[0] == identities[1]
        assert peak == 1
    finally:
        with CngKey.open(name=name) as key:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_missing_tpm_falls_back_to_software_only_when_no_key_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_dll = cng._api()

    class NoTpmDll:
        def NCryptOpenStorageProvider(self, output, label, flags):
            if label == cng.PLATFORM_PROVIDER:
                return 0x80090035
            return real_dll.NCryptOpenStorageProvider(output, label, flags)

        def __getattr__(self, attr):
            return getattr(real_dll, attr)

    monkeypatch.setattr(cng, "_api", lambda: NoTpmDll())
    name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=name) as key:
        try:
            assert key.provider == "SOFTWARE"
            spki = key.public_spki()
            with CngKey.open(name=name) as reopened:
                assert reopened.public_spki() == spki
        finally:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_existing_software_identity_rejects_transient_tpm_outage_and_provider_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_dll = cng._api()
    name = f"Sentinel disposable test {uuid4()}"

    class PlatformUnavailable:
        status = 0x80090035

        def NCryptOpenStorageProvider(self, output, label, flags):
            if label == cng.PLATFORM_PROVIDER:
                return self.status
            return real_dll.NCryptOpenStorageProvider(output, label, flags)

        def __getattr__(self, attr):
            return getattr(real_dll, attr)

    fake = PlatformUnavailable()
    with monkeypatch.context() as scoped:
        scoped.setattr(cng, "_api", lambda: fake)
        with CngKey.open(name=name) as first:
            assert first.provider == "SOFTWARE"
            original = first.public_spki()
        fake.status = 0x80290401  # transient TPM failure; identity could be hidden
        with pytest.raises(cng.CngError, match="NCryptOpenStorageProvider\\(Platform\\)"):
            CngKey.open(name=name)

    class BothProviders:
        def NCryptOpenStorageProvider(self, output, label, flags):
            return real_dll.NCryptOpenStorageProvider(output, cng.SOFTWARE_PROVIDER, flags)

        def __getattr__(self, attr):
            return getattr(real_dll, attr)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(cng, "_api", lambda: BothProviders())
            with pytest.raises(RuntimeError, match="Multiple CNG providers"):
                CngKey.open(name=name)
        with CngKey.open(name=name) as reopened:
            assert reopened.public_spki() == original
    finally:
        with CngKey.open(name=name) as cleanup:
            cleanup.delete_for_test()


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
