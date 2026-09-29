"""Hosted CI uses the software KSP for disposable Passport test identities."""

from __future__ import annotations

import pytest

from backend.tests.passport.hosted_cng import configure_hosted_software_key_tests


@pytest.fixture(autouse=True)
def _hosted_software_key(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_hosted_software_key_tests(monkeypatch)
