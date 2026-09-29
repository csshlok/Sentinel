"""Test-only software KSP selection on disposable Windows CI machines.

NTE_DEVICE_NOT_READY can hide an existing TPM key, so production signing must
fail closed. CI tests use new disposable identities and may exercise the real
software KSP when the hosted runner has no usable TPM.
"""

from __future__ import annotations

import ctypes
import os

import pytest

import backend.app.passport.cng as cng

_DEVICE_NOT_READY = 0x80090030


def platform_device_not_ready() -> bool:
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    dll = cng._api()
    handle = ctypes.c_void_p()
    status = dll.NCryptOpenStorageProvider(
        ctypes.byref(handle), cng.PLATFORM_PROVIDER, 0) & 0xFFFFFFFF
    if handle.value:
        dll.NCryptFreeObject(handle)
    return status == _DEVICE_NOT_READY


def configure_hosted_software_key_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    if platform_device_not_ready():
        monkeypatch.setattr(cng, "_PLATFORM_UNAVAILABLE_FOR_KEY",
                            cng._PLATFORM_UNAVAILABLE_FOR_KEY | {_DEVICE_NOT_READY})
