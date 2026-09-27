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
