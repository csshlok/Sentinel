"""Non-exportable ES256 signing through the Windows CNG key storage providers.

Only public ECC coordinates and a SHA-256 digest cross the Python/CNG boundary.
Private-key generation, persistence and signing remain inside the selected KSP.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import struct
from ctypes import wintypes
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

PLATFORM_PROVIDER = "Microsoft Platform Crypto Provider"
SOFTWARE_PROVIDER = "Microsoft Software Key Storage Provider"
DEFAULT_KEY_NAME = "Sentinel Passport v2 ES256"
_BAD_KEYSET = 0x80090016
_ECC_P256_PUBLIC_MAGIC = 0x31534345  # ECS1
_EXPORT_POLICY = "Export Policy"


class CngError(OSError):
    """A Windows CNG operation failed, with its unsigned security status."""

    def __init__(self, operation: str, status: int) -> None:
        self.status = status & 0xFFFFFFFF
        super().__init__(f"{operation} failed (0x{self.status:08x})")


def _checked(operation: str, status: int) -> None:
    if status:
        raise CngError(operation, status)


def _api() -> ctypes.WinDLL:
    if os.name != "nt":
        raise OSError("Windows CNG is required for Passport v2 signing")
    dll = ctypes.WinDLL("ncrypt.dll")
    handle = ctypes.c_void_p
    dword = wintypes.DWORD
    dll.NCryptOpenStorageProvider.argtypes = [ctypes.POINTER(handle), wintypes.LPCWSTR, dword]
    dll.NCryptOpenStorageProvider.restype = wintypes.LONG
    dll.NCryptOpenKey.argtypes = [handle, ctypes.POINTER(handle), wintypes.LPCWSTR, dword, dword]
    dll.NCryptOpenKey.restype = wintypes.LONG
    dll.NCryptCreatePersistedKey.argtypes = [handle, ctypes.POINTER(handle), wintypes.LPCWSTR,
                                               wintypes.LPCWSTR, dword, dword]
    dll.NCryptCreatePersistedKey.restype = wintypes.LONG
    dll.NCryptSetProperty.argtypes = [handle, wintypes.LPCWSTR, ctypes.c_void_p, dword, dword]
    dll.NCryptSetProperty.restype = wintypes.LONG
    dll.NCryptGetProperty.argtypes = [handle, wintypes.LPCWSTR, ctypes.c_void_p, dword,
                                      ctypes.POINTER(dword), dword]
    dll.NCryptGetProperty.restype = wintypes.LONG
    dll.NCryptFinalizeKey.argtypes = [handle, dword]
    dll.NCryptFinalizeKey.restype = wintypes.LONG
    dll.NCryptExportKey.argtypes = [handle, handle, wintypes.LPCWSTR, ctypes.c_void_p,
                                    ctypes.c_void_p, dword, ctypes.POINTER(dword), dword]
    dll.NCryptExportKey.restype = wintypes.LONG
    dll.NCryptSignHash.argtypes = [handle, ctypes.c_void_p, ctypes.c_void_p, dword,
                                   ctypes.c_void_p, dword, ctypes.POINTER(dword), dword]
    dll.NCryptSignHash.restype = wintypes.LONG
    dll.NCryptFreeObject.argtypes = [handle]
    dll.NCryptFreeObject.restype = wintypes.LONG
    dll.NCryptDeleteKey.argtypes = [handle, dword]
    dll.NCryptDeleteKey.restype = wintypes.LONG
    return dll


@dataclass(slots=True)
class CngKey:
    """An opened persistent P-256 key; use as a context manager."""

    _dll: ctypes.WinDLL
    _provider_handle: ctypes.c_void_p
    _key_handle: ctypes.c_void_p
    provider: str
    name: str

    @classmethod
    def open(cls, *, name: str = DEFAULT_KEY_NAME) -> CngKey:
        if not name or len(name) > 200 or "\\" in name or "/" in name:
            raise ValueError("Invalid CNG key name")
        dll = _api()
        providers: list[tuple[str, ctypes.c_void_p]] = []
        try:
            for label in (PLATFORM_PROVIDER, SOFTWARE_PROVIDER):
                handle = ctypes.c_void_p()
                status = dll.NCryptOpenStorageProvider(ctypes.byref(handle), label, 0)
                if status == 0:
                    providers.append((label, handle))
                elif label == SOFTWARE_PROVIDER:
                    _checked("NCryptOpenStorageProvider", status)
            # An existing software identity stays stable if a TPM becomes available later.
            for label, handle in providers:
                key = ctypes.c_void_p()
                status = dll.NCryptOpenKey(handle, ctypes.byref(key), name, 0, 0)
                if status == 0:
                    chosen = cls(dll, handle, key, _provider_label(label), name)
                    try:
                        chosen._assert_nonexportable()
                    except Exception:
                        dll.NCryptFreeObject(key)
                        raise
                    for other_label, other in providers:
                        if other_label != label:
                            dll.NCryptFreeObject(other)
                    return chosen
                if status & 0xFFFFFFFF != _BAD_KEYSET:
                    _checked("NCryptOpenKey", status)
            # Platform creation can fail on machines with no usable TPM. Software is
            # the only fallback; never replace an existing key after an open error.
            for label, handle in providers:
                key = ctypes.c_void_p()
                status = dll.NCryptCreatePersistedKey(
                    handle, ctypes.byref(key), "ECDSA_P256", name, 0, 0)
                if status:
                    if label == PLATFORM_PROVIDER:
                        continue
                    _checked("NCryptCreatePersistedKey", status)
                try:
                    policy = wintypes.DWORD(0)
                    _checked("NCryptSetProperty", dll.NCryptSetProperty(
                        key, _EXPORT_POLICY, ctypes.byref(policy), ctypes.sizeof(policy), 0))
                    _checked("NCryptFinalizeKey", dll.NCryptFinalizeKey(key, 0))
                    chosen = cls(dll, handle, key, _provider_label(label), name)
                    chosen._assert_nonexportable()
                    for other_label, other in providers:
                        if other_label != label:
                            dll.NCryptFreeObject(other)
                    return chosen
                except Exception:
                    if key.value:
                        dll.NCryptFreeObject(key)
                    raise
            raise OSError("No usable Windows CNG key storage provider")
        except Exception:
            for _, handle in providers:
                if handle.value:
                    dll.NCryptFreeObject(handle)
            raise

    def _assert_nonexportable(self) -> None:
        policy = wintypes.DWORD()
        written = wintypes.DWORD()
        _checked("NCryptGetProperty", self._dll.NCryptGetProperty(
            self._key_handle, _EXPORT_POLICY, ctypes.byref(policy), ctypes.sizeof(policy),
            ctypes.byref(written), 0))
        if written.value != ctypes.sizeof(policy) or policy.value != 0:
            raise CngError("CNG key is exportable", policy.value)
        size = wintypes.DWORD()
        status = self._dll.NCryptExportKey(
            self._key_handle, None, "ECCPRIVATEBLOB", None, None, 0, ctypes.byref(size), 0)
        if status == 0:
            raise RuntimeError("CNG provider permitted private-key export")

    def public_spki(self) -> bytes:
        size = wintypes.DWORD()
        _checked("NCryptExportKey(public size)", self._dll.NCryptExportKey(
            self._key_handle, None, "ECCPUBLICBLOB", None, None, 0, ctypes.byref(size), 0))
        if size.value != 72:
            raise ValueError("Unexpected P-256 public blob size")
        output = ctypes.create_string_buffer(size.value)
        _checked("NCryptExportKey(public)", self._dll.NCryptExportKey(
            self._key_handle, None, "ECCPUBLICBLOB", None, output, size.value,
            ctypes.byref(size), 0))
        magic, key_size = struct.unpack_from("<II", output.raw)
        if magic != _ECC_P256_PUBLIC_MAGIC or key_size != 32:
            raise ValueError("CNG returned a non-P-256 public key")
        x = int.from_bytes(output.raw[8:40], "big")
        y = int.from_bytes(output.raw[40:72], "big")
        public = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        return public.public_bytes(serialization.Encoding.DER,
                                   serialization.PublicFormat.SubjectPublicKeyInfo)

    def sign(self, message: bytes) -> bytes:
        digest = hashlib.sha256(message).digest()
        input_buffer = ctypes.create_string_buffer(digest)
        size = wintypes.DWORD()
        _checked("NCryptSignHash(size)", self._dll.NCryptSignHash(
            self._key_handle, None, input_buffer, len(digest), None, 0,
            ctypes.byref(size), 0))
        if size.value != 64:
            raise ValueError("Unexpected P-256 signature size")
        output = ctypes.create_string_buffer(size.value)
        _checked("NCryptSignHash", self._dll.NCryptSignHash(
            self._key_handle, None, input_buffer, len(digest), output, size.value,
            ctypes.byref(size), 0))
        return output.raw[:size.value]  # JOSE ES256: fixed-width r || s.

    def close(self) -> None:
        if self._key_handle.value:
            self._dll.NCryptFreeObject(self._key_handle)
            self._key_handle = ctypes.c_void_p()
        if self._provider_handle.value:
            self._dll.NCryptFreeObject(self._provider_handle)
            self._provider_handle = ctypes.c_void_p()

    def delete_for_test(self) -> None:
        """Remove a disposable test key, never the installation's default key."""
        if self.name == DEFAULT_KEY_NAME:
            raise ValueError("Cannot delete the installation key")
        _checked("NCryptDeleteKey", self._dll.NCryptDeleteKey(self._key_handle, 0))
        self._key_handle = ctypes.c_void_p()

    def __enter__(self) -> CngKey:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _provider_label(name: str) -> str:
    return "TPM" if name == PLATFORM_PROVIDER else "SOFTWARE"


def fingerprint(spki: bytes) -> str:
    """Grouped base32 SHA-256 of the canonical DER SubjectPublicKeyInfo."""
    public = serialization.load_der_public_key(spki)
    if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
        raise ValueError("Fingerprint requires an ES256 SPKI")
    canonical = public.public_bytes(serialization.Encoding.DER,
                                    serialization.PublicFormat.SubjectPublicKeyInfo)
    encoded = base64.b32encode(hashlib.sha256(canonical).digest()).decode("ascii").rstrip("=")
    return "-".join(encoded[index:index + 8] for index in range(0, len(encoded), 8))


def verify_signature(*, spki: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an ES256 raw signature using only the public SPKI."""
    try:
        public = serialization.load_der_public_key(spki)
        if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
            return False
        if len(signature) != 64:
            return False
        der = utils.encode_dss_signature(int.from_bytes(signature[:32], "big"),
                                         int.from_bytes(signature[32:], "big"))
        public.verify(der, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (ValueError, InvalidSignature):
        return False
