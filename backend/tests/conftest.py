"""Session-wide test isolation for Sentinel's evidence store.

`backend.app.main` builds a module-level `app = create_app()` at import time,
and `Settings.from_environment()` now defaults the store to
`%LOCALAPPDATA%\\Sentinel`. Without this redirect, merely importing the module
from a test would create (and ACL-restrict) the developer's real per-user
store. Point CHANGE_ASSURANCE_DB_PATH at a throwaway directory outside every
repository before any test module is imported. Tests that exercise the
default location unset this variable with `monkeypatch` and aim LOCALAPPDATA
at `tmp_path`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_SESSION_STORE = Path(tempfile.mkdtemp(prefix="sentinel-test-store-"))
os.environ["CHANGE_ASSURANCE_DB_PATH"] = str(_SESSION_STORE / "change_assurance.sqlite3")


def pytest_unconfigure(config) -> None:  # noqa: ARG001 - pytest hook signature
    shutil.rmtree(_SESSION_STORE, ignore_errors=True)


# ---------------------------------------------------------------------- check boxes
#
# Phase 5: `create_app` runs every verification, assurance and diff-coverage
# check in a real AppContainer check box with a runtime snapshot (seconds per
# check, plus a snapshot build in the user's cache). Tests that merely exercise
# routes and lifecycle get the HOST harness from `support_checks` instead: the
# real CheckBoxes code (rows, tree copy, journal, cleanup) with a fake Windows
# layer whose "box" is a plain host child. It proves nothing about containment;
# the real-boundary tests construct real CheckBoxes directly, and a test that
# needs a real box through `create_app` opts out with
# `@pytest.mark.real_check_boxes`.


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "real_check_boxes: create_app builds real AppContainer check boxes (no host harness)",
    )


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _host_check_boxes_in_create_app(request, monkeypatch, tmp_path_factory):
    if request.node.get_closest_marker("real_check_boxes") is not None:
        yield
        return
    import backend.app.main as main
    from backend.tests.support_checks import host_check_boxes

    def factory(database, *, journal=None, evidence_guard=None, **_kwargs):
        boxes, _ = host_check_boxes(tmp_path_factory.mktemp("host-check-boxes"), database,
                                    journal=journal, evidence_guard=evidence_guard)
        return boxes

    monkeypatch.setattr(main, "CheckBoxes", factory)
    yield
