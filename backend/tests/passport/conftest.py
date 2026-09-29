"""Hosted CI uses the software KSP for disposable Passport test identities."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.tests.passport.hosted_cng import configure_hosted_software_key_tests


@pytest.fixture(scope="session", autouse=True)
def _hosted_software_key() -> Iterator[None]:
    # Session scope must precede test_verify's module-scoped signed_bundle.
    with pytest.MonkeyPatch.context() as patch:
        configure_hosted_software_key_tests(patch)
        yield
