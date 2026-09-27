"""Evidence-store location, in-repository refusal and legacy-store warning (D-05)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core import evidence_store
from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.core.evidence_store import (
    DATABASE_FILENAME,
    LEGACY_STORE_DIRECTORY,
    STORE_DIRECTORY_NAME,
    default_database_path,
    default_store_directory,
    enclosing_git_worktree,
    ensure_store_outside_repository,
    legacy_database_path,
    warn_if_legacy_store_present,
)
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.tests.support_kb import make_repo


def _files_named(root: Path, pattern: str) -> list[Path]:
    return [path for path in root.rglob(pattern) if ".git" not in path.parts]


def _junction(target: Path, link: Path) -> None:
    if os.name != "nt":
        pytest.skip("junctions are Windows-only")
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, AttributeError, OSError) as error:
        pytest.skip(f"cannot create a junction here: {error}")


# ---- default location ---------------------------------------------------------


def test_default_store_directory_uses_localappdata(tmp_path) -> None:
    assert default_store_directory({"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "Sentinel"
    assert STORE_DIRECTORY_NAME == "Sentinel"


def test_default_store_directory_falls_back_to_home_appdata_local(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert default_store_directory({}) == tmp_path / "AppData" / "Local" / "Sentinel"
    assert default_store_directory({"LOCALAPPDATA": ""}) == tmp_path / "AppData" / "Local" / "Sentinel"


def test_default_database_path_appends_the_database_filename(tmp_path) -> None:
    assert default_database_path({"LOCALAPPDATA": str(tmp_path)}) == (
        tmp_path / "Sentinel" / "change_assurance.sqlite3"
    )
    assert DATABASE_FILENAME == "change_assurance.sqlite3"


def test_legacy_database_path_is_under_cwd(tmp_path) -> None:
    assert legacy_database_path(tmp_path) == tmp_path / LEGACY_STORE_DIRECTORY / DATABASE_FILENAME


def test_settings_default_to_localappdata_sentinel(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CHANGE_ASSURANCE_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = Settings.from_environment()
    assert settings.database_path == (tmp_path / "Sentinel" / "change_assurance.sqlite3").resolve()


def test_settings_honor_the_database_path_override(tmp_path, monkeypatch) -> None:
    override = tmp_path / "elsewhere" / "custom.sqlite3"
    monkeypatch.setenv("CHANGE_ASSURANCE_DB_PATH", str(override))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert Settings.from_environment().database_path == override.resolve()


# ---- repository detection ------------------------------------------------------


def test_enclosing_git_worktree_finds_a_git_directory_above_a_missing_path(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    nested = repo / "a" / "b" / "store.sqlite3"
    assert enclosing_git_worktree(nested) == repo


def test_enclosing_git_worktree_finds_a_git_file(tmp_path) -> None:
    worktree = tmp_path / "linked"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: C:/somewhere/.git/worktrees/linked\n", encoding="utf-8")
    assert enclosing_git_worktree(worktree / ".change-assurance" / "db.sqlite3") == worktree


def test_enclosing_git_worktree_returns_none_outside_repositories(tmp_path) -> None:
    assert enclosing_git_worktree(tmp_path / "plain" / "db.sqlite3") is None


def test_ensure_store_outside_repository_raises_the_stable_code(tmp_path) -> None:
    repo = make_repo(tmp_path / "repo")
    database = repo / ".change-assurance" / "change_assurance.sqlite3"
    with pytest.raises(AppError) as caught:
        ensure_store_outside_repository(database)
    assert caught.value.code == "EVIDENCE_STORE_INSIDE_REPOSITORY"
    assert caught.value.status_code == 409


# ---- create_app ---------------------------------------------------------------


@pytest.mark.parametrize("explicit_token", [None, "explicit-token"])
def test_create_app_refuses_a_store_inside_a_repository_before_writing(
    tmp_path, explicit_token
) -> None:
    repo = make_repo(tmp_path / "repo")
    database = repo / ".change-assurance" / "change_assurance.sqlite3"

    with pytest.raises(AppError) as caught:
        create_app(
            settings=Settings(database_path=database, api_token=explicit_token),
            credential_store=InMemoryCredentialStore(),
        )

    error = caught.value
    assert error.code == "EVIDENCE_STORE_INSIDE_REPOSITORY"
    assert "migrate-store" in error.message
    assert error.details["database_path"] == str(database)
    assert Path(error.details["repository_root"]) == repo
    assert _files_named(repo, "api_token") == []
    assert _files_named(repo, "*.sqlite3") == []
    assert not (repo / ".change-assurance").exists()


def test_create_app_accepts_a_store_in_a_sibling_directory(tmp_path) -> None:
    make_repo(tmp_path / "repo")
    database = tmp_path / "state" / "api.sqlite3"

    app = create_app(
        settings=Settings(database_path=database),
        credential_store=InMemoryCredentialStore(),
    )

    assert (database.parent / "api_token").is_file()
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_create_app_refuses_a_junction_that_points_into_a_repository(tmp_path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "state").mkdir()
    link = tmp_path / "innocent"
    _junction(repo / "state", link)
    database = link / "change_assurance.sqlite3"

    # Lexically nothing on the path is a repository; only the resolved path is.
    assert not any((parent / ".git").exists() for parent in (link, *link.parents))
    with pytest.raises(AppError) as caught:
        create_app(
            settings=Settings(database_path=database),
            credential_store=InMemoryCredentialStore(),
        )
    assert caught.value.code == "EVIDENCE_STORE_INSIDE_REPOSITORY"
    assert list((repo / "state").iterdir()) == []


# ---- legacy store warning -----------------------------------------------------


def test_legacy_store_warning_names_migrate_store(tmp_path, caplog) -> None:
    legacy = tmp_path / LEGACY_STORE_DIRECTORY / DATABASE_FILENAME
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy")
    logger = logging.getLogger("test.evidence_store.legacy")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        warn_if_legacy_store_present(tmp_path / "new" / "db.sqlite3", cwd=tmp_path, logger=logger)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert "migrate-store" in caplog.records[0].getMessage()
    assert legacy.read_bytes() == b"legacy"


def test_no_legacy_warning_without_a_legacy_store_or_when_it_is_the_configured_path(
    tmp_path, caplog
) -> None:
    logger = logging.getLogger("test.evidence_store.none")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        warn_if_legacy_store_present(tmp_path / "new" / "db.sqlite3", cwd=tmp_path, logger=logger)
        legacy = tmp_path / LEGACY_STORE_DIRECTORY / DATABASE_FILENAME
        legacy.parent.mkdir()
        legacy.write_bytes(b"legacy")
        warn_if_legacy_store_present(legacy, cwd=tmp_path, logger=logger)
    assert caplog.records == []


def test_module_exports_the_legacy_directory_name_only_here() -> None:
    assert evidence_store.LEGACY_STORE_DIRECTORY == ".change-assurance"
