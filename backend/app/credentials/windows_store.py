"""Windows Credential Manager-backed `CredentialStorePort`.

Implemented directly with `ctypes` bindings to `advapi32.dll` so no new
project dependency (e.g. `keyring`, `pywin32`) is required; adding one
would need an `[SD]`-owned dependency handoff per
`AGENT_COORDINATION.md`. Only this module touches the Windows API.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    """Concrete `CredentialStorePort` backed by Windows Credential Manager."""

    def __init__(self, target_prefix: str = "ChangeAssuranceRuntime") -> None:
        self._target_prefix = target_prefix
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(_CREDENTIAL),
            wintypes.DWORD,
        ]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    def _target_name(self, name: str) -> str:
        return f"{self._target_prefix}:{name}"

    def set_secret(self, name: str, value: str) -> None:
        blob = value.encode("utf-16-le")
        blob_buffer = ctypes.create_string_buffer(blob, len(blob)) if blob else None
        credential = _CREDENTIAL(
            Flags=0,
            Type=CRED_TYPE_GENERIC,
            TargetName=self._target_name(name),
            Comment=None,
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_char))
            if blob_buffer is not None
            else None,
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName=None,
        )
        ok = self._advapi32.CredWriteW(ctypes.byref(credential), 0)
        if not ok:
            raise OSError(ctypes.get_last_error(), "CredWriteW failed")

    def get_secret(self, name: str) -> str | None:
        credential_ptr = ctypes.POINTER(_CREDENTIAL)()
        ok = self._advapi32.CredReadW(
            self._target_name(name), CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr)
        )
        if not ok:
            error = ctypes.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise OSError(error, "CredReadW failed")
        try:
            credential = credential_ptr.contents
            size = credential.CredentialBlobSize
            if size == 0:
                return ""
            raw = ctypes.string_at(credential.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self._advapi32.CredFree(credential_ptr)

    def delete_secret(self, name: str) -> None:
        ok = self._advapi32.CredDeleteW(self._target_name(name), CRED_TYPE_GENERIC, 0)
        if not ok:
            error = ctypes.get_last_error()
            if error != ERROR_NOT_FOUND:
                raise OSError(error, "CredDeleteW failed")
