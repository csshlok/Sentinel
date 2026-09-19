"""Unit tests for the API bearer-token file (threat model finding #12)."""

from __future__ import annotations

import os
import stat

import pytest

from backend.app.core.auth import load_or_create_api_token


def test_token_persists_across_calls(tmp_path) -> None:
    db_path = tmp_path / "state" / "db.sqlite3"
    first = load_or_create_api_token(db_path)
    second = load_or_create_api_token(db_path)
    assert first == second
    assert len(first) > 20


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode bits are a no-op on Windows")
def test_token_file_is_restricted_to_the_owner_on_posix(tmp_path) -> None:
    db_path = tmp_path / "state" / "db.sqlite3"
    load_or_create_api_token(db_path)
    token_path = db_path.parent / "api_token"
    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


@pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")
def test_token_creation_invokes_icacls_to_restrict_to_the_current_user(
    tmp_path, monkeypatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        class _Result:
            returncode = 0
        return _Result()

    monkeypatch.setattr("backend.app.core.auth.subprocess.run", fake_run)
    monkeypatch.setenv("USERNAME", "test-user")

    db_path = tmp_path / "state" / "db.sqlite3"
    load_or_create_api_token(db_path)

    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "icacls"
    assert "/inheritance:r" in argv
    assert "test-user:F" in argv


def test_a_missing_icacls_does_not_break_token_creation(tmp_path, monkeypatch) -> None:
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("icacls not found")

    monkeypatch.setattr("backend.app.core.auth.subprocess.run", fake_run)
    monkeypatch.setenv("USERNAME", "test-user")

    db_path = tmp_path / "state" / "db.sqlite3"
    # Must not raise even if the restriction step itself fails.
    token = load_or_create_api_token(db_path)
    assert len(token) > 20
