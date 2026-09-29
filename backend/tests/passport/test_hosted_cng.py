"""Hosted software-KSP selection stays inside the pytest process."""

from __future__ import annotations

import os

import pytest

import backend.app.passport.cng as cng
from backend.tests.passport.hosted_cng import configure_hosted_software_key_tests


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_hosted_device_not_ready_override_is_test_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = cng._PLATFORM_UNAVAILABLE_FOR_KEY

    class NoPlatform:
        def NCryptOpenStorageProvider(self, output, label, flags):
            return 0x80090030

        def NCryptFreeObject(self, handle):
            raise AssertionError("failed provider must not return a handle")

    with monkeypatch.context() as scoped:
        scoped.setenv("GITHUB_ACTIONS", "true")
        scoped.setattr(cng, "_api", lambda: NoPlatform())
        configure_hosted_software_key_tests(scoped)
        assert 0x80090030 in cng._PLATFORM_UNAVAILABLE_FOR_KEY
    assert cng._PLATFORM_UNAVAILABLE_FOR_KEY == original
