"""Opt-in smoke test against the real Windows Credential Manager.

Skipped by default: it touches real OS state. Run explicitly with
`RUN_WINDOWS_CREDENTIAL_SMOKE_TEST=1 pytest backend/tests/credentials/test_windows_store.py`.
It creates and removes only one uniquely named test credential.
"""

from __future__ import annotations

import os
import sys
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("RUN_WINDOWS_CREDENTIAL_SMOKE_TEST"),
    reason="Opt-in Windows-only smoke test; set RUN_WINDOWS_CREDENTIAL_SMOKE_TEST=1 to run.",
)


def test_real_windows_credential_manager_round_trip() -> None:
    from backend.app.credentials.windows_store import WindowsCredentialStore

    unique_name = f"smoke-test-{uuid.uuid4()}"
    store = WindowsCredentialStore(target_prefix="ChangeAssuranceRuntimeSmokeTest")

    try:
        assert store.get_secret(unique_name) is None

        store.set_secret(unique_name, "smoke-test-value")
        assert store.get_secret(unique_name) == "smoke-test-value"

        store.set_secret(unique_name, "smoke-test-value-2")
        assert store.get_secret(unique_name) == "smoke-test-value-2"
    finally:
        store.delete_secret(unique_name)

    assert store.get_secret(unique_name) is None
