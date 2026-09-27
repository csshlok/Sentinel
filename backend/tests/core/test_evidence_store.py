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
    prepare_store_directory,
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


def test_enclosing_git_worktree_finds_a_real_repository_above_a_missing_path(tmp_path) -> None:
    repo = make_repo(tmp_path / "repo")
    nested = repo / "a" / "b" / "store.sqlite3"
    assert enclosing_git_worktree(nested) == repo


def test_enclosing_git_worktree_finds_a_linked_worktree_gitfile(tmp_path) -> None:
    import subprocess

    repo = make_repo(tmp_path / "repo")
    worktree = tmp_path / "linked"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(worktree)],
                   check=True, capture_output=True)
    assert (worktree / ".git").is_file()
    assert enclosing_git_worktree(worktree / ".change-assurance" / "db.sqlite3") == worktree


def test_an_empty_or_fake_git_entry_does_not_refuse_the_store(tmp_path) -> None:
    """WR-05: a stray `.git` that Git itself rejects is not a denial of service."""

    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    garbage = tmp_path / "garbage"
    (garbage / ".git" / "objects").mkdir(parents=True)
    (garbage / ".git" / "HEAD").write_text("not a ref\n", encoding="utf-8")
    dangling = tmp_path / "dangling"
    dangling.mkdir()
    (dangling / ".git").write_text(f"gitdir: {tmp_path / 'nowhere'}\n", encoding="utf-8")
    text_file = tmp_path / "text"
    text_file.mkdir()
    (text_file / ".git").write_text("hello\n", encoding="utf-8")

    for root in (empty, garbage, dangling, text_file):
        assert enclosing_git_worktree(root / "Sentinel" / DATABASE_FILENAME) is None, root
        ensure_store_outside_repository(root / "Sentinel" / DATABASE_FILENAME)


def test_repository_confirmation_fails_closed_when_git_cannot_answer(tmp_path, monkeypatch) -> None:
    from backend.app.git.errors import GitExecutableNotFoundError

    repo = make_repo(tmp_path / "repo")

    def unavailable(*args, **kwargs):
        raise GitExecutableNotFoundError()

    monkeypatch.setattr(evidence_store, "run_git", unavailable)
    assert enclosing_git_worktree(repo / "state" / DATABASE_FILENAME) == repo
    # Without structural evidence Git is never consulted and nothing is refused.
    (tmp_path / "plain" / ".git").mkdir(parents=True)
    assert enclosing_git_worktree(tmp_path / "plain" / DATABASE_FILENAME) is None


def test_confirmation_never_accepts_an_outer_repository_found_by_upward_discovery(tmp_path) -> None:
    outer = make_repo(tmp_path / "outer")
    inner = outer / "inner"
    (inner / ".git" / "objects").mkdir(parents=True)
    (inner / ".git" / "HEAD").write_text("not a ref\n", encoding="utf-8")

    # The broken inner `.git` is skipped; the real outer repository still refuses.
    assert enclosing_git_worktree(inner / "Sentinel" / DATABASE_FILENAME) == outer


def test_a_repository_at_the_user_profile_recommends_the_database_path_override(
    tmp_path, monkeypatch
) -> None:
    home = make_repo(tmp_path / "home")
    local = home / "AppData" / "Local"
    local.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    with pytest.raises(AppError) as caught:
        ensure_store_outside_repository(default_database_path())
    assert caught.value.code == "EVIDENCE_STORE_INSIDE_REPOSITORY"
    assert "CHANGE_ASSURANCE_DB_PATH" in caught.value.message
    assert "user profile" in caught.value.message


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


def test_create_app_refuses_an_in_repository_junction_to_an_outside_store(
    tmp_path, monkeypatch
) -> None:
    """WR-04: the reverse junction (repository -> outside) is refused on the lexical path."""

    repo = make_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = repo / ".store"
    _junction(outside, link)
    monkeypatch.setenv("CHANGE_ASSURANCE_DB_PATH", str(link / DATABASE_FILENAME))
    monkeypatch.delenv("CHANGE_ASSURANCE_API_TOKEN", raising=False)

    settings = Settings.from_environment()
    # The resolved path alone is outside every repository.
    assert enclosing_git_worktree(settings.database_path) is None
    assert settings.configured_database_path == link / DATABASE_FILENAME

    with pytest.raises(AppError) as caught:
        create_app(settings=settings, credential_store=InMemoryCredentialStore())
    assert caught.value.code == "EVIDENCE_STORE_INSIDE_REPOSITORY"
    assert list(outside.iterdir()) == []


def test_settings_keep_the_unresolved_configured_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CHANGE_ASSURANCE_DB_PATH", str(tmp_path / "a" / ".." / "db.sqlite3"))
    settings = Settings.from_environment()
    assert settings.database_path == (tmp_path / "db.sqlite3").resolve()
    assert settings.configured_database_path == tmp_path / "db.sqlite3"


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


def _legacy_store(cwd: Path) -> Path:
    """A real legacy `<cwd>/.change-assurance` store with an api_token beside it."""

    from backend.app.core.auth import load_or_create_api_token
    from backend.app.core.database import Database

    legacy = cwd / LEGACY_STORE_DIRECTORY / DATABASE_FILENAME
    legacy.parent.mkdir(parents=True)
    Database(legacy).initialize()
    load_or_create_api_token(legacy)
    return legacy


@pytest.fixture
def default_store_env(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """No conftest redirect: the real default-location code path under tmp_path."""

    local = tmp_path / "local"
    local.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.delenv("CHANGE_ASSURANCE_DB_PATH", raising=False)
    monkeypatch.delenv("CHANGE_ASSURANCE_API_TOKEN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.chdir(work)
    return local, work


def test_startup_refuses_a_fresh_default_store_while_a_legacy_store_awaits_migration(
    default_store_env,
) -> None:
    """CR-03 / revised D-05: refuse instead of creating a store that blocks migrate-store."""

    local, work = default_store_env
    legacy = _legacy_store(work)

    with pytest.raises(AppError) as caught:
        create_app(credential_store=InMemoryCredentialStore())

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_REQUIRED"
    assert caught.value.status_code == 409
    assert "migrate-store" in caught.value.message
    assert caught.value.details == {
        "legacy_path": str(legacy),
        "database_path": str(default_database_path().resolve()),
    }
    # Refuse-before-write: no default directory, token or database was created.
    assert not (local / STORE_DIRECTORY_NAME).exists()


def test_the_documented_upgrade_flow_works_after_a_refused_startup(default_store_env) -> None:
    """Start (refused) -> migrate-store with defaults -> start succeeds on the migrated store."""

    local, work = default_store_env
    legacy = _legacy_store(work)
    with pytest.raises(AppError):
        create_app(credential_store=InMemoryCredentialStore())

    result = evidence_store.migrate_store(source=legacy, target=default_database_path())
    assert result.target_database == local / STORE_DIRECTORY_NAME / DATABASE_FILENAME

    app = create_app(credential_store=InMemoryCredentialStore())
    token_path = local / STORE_DIRECTORY_NAME / "api_token"
    assert token_path.read_text(encoding="utf-8").strip() == app.state.api_token
    assert legacy.is_file()  # the old store is left in place for the user to delete


def test_startup_proceeds_with_a_warning_when_the_default_store_already_exists(
    default_store_env, caplog
) -> None:
    local, work = default_store_env
    create_app(credential_store=InMemoryCredentialStore())  # default store now exists
    _legacy_store(work)

    with caplog.at_level(logging.WARNING, logger="backend.app.main"):
        create_app(credential_store=InMemoryCredentialStore())

    assert any("legacy evidence store" in record.getMessage() for record in caplog.records)


def test_an_operator_chosen_store_is_not_refused_for_a_legacy_store(
    default_store_env, tmp_path
) -> None:
    _, work = default_store_env
    _legacy_store(work)
    chosen = tmp_path / "chosen" / DATABASE_FILENAME

    create_app(settings=Settings(database_path=chosen), credential_store=InMemoryCredentialStore())

    assert (chosen.parent / "api_token").is_file()


def test_module_exports_the_legacy_directory_name_only_here() -> None:
    assert evidence_store.LEGACY_STORE_DIRECTORY == ".change-assurance"


# ---- store directory DACL (Task 2) ------------------------------------------------


class _AclRecorder:
    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[Path, bool]] = []
        self.result = result

    def __call__(self, path: Path, *, directory: bool = False) -> bool:
        self.calls.append((Path(path), directory))
        return self.result


@pytest.fixture
def acl_recorder(monkeypatch) -> _AclRecorder:
    fake = _AclRecorder()
    monkeypatch.setattr(evidence_store, "restrict_to_current_user", fake)
    return fake


def test_prepare_store_directory_refuses_any_other_directory_name(tmp_path, acl_recorder) -> None:
    with pytest.raises(ValueError):
        prepare_store_directory(tmp_path / "NotSentinel")
    with pytest.raises(ValueError):
        prepare_store_directory(tmp_path)
    assert acl_recorder.calls == []
    assert not (tmp_path / "NotSentinel").exists()


def test_prepare_store_directory_creates_and_restricts_the_directory(tmp_path, acl_recorder) -> None:
    directory = tmp_path / "local" / "Sentinel"
    assert prepare_store_directory(directory) is True
    assert directory.is_dir()
    assert acl_recorder.calls == [(directory, True)]


def test_prepare_store_directory_logs_a_warning_when_the_acl_is_not_applied(
    tmp_path, acl_recorder, caplog
) -> None:
    acl_recorder.result = False
    logger = logging.getLogger("test.evidence_store.acl")
    with caplog.at_level(logging.WARNING, logger=logger.name):
        assert prepare_store_directory(tmp_path / "Sentinel", logger=logger) is False
    assert len(caplog.records) == 1
    assert "Could not restrict" in caplog.records[0].getMessage()


def test_prepare_store_directory_refuses_a_junction(tmp_path, acl_recorder) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "Sentinel"
    _junction(target, link)
    with pytest.raises(AppError) as caught:
        prepare_store_directory(link)
    assert caught.value.code == "EVIDENCE_STORE_UNSAFE_LOCATION"
    assert caught.value.details == {"path": str(link)}
    assert acl_recorder.calls == []


def test_prepare_store_directory_refuses_a_symlink(tmp_path, acl_recorder) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "Sentinel"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"cannot create a directory symlink here: {error}")
    with pytest.raises(AppError) as caught:
        prepare_store_directory(link)
    assert caught.value.code == "EVIDENCE_STORE_UNSAFE_LOCATION"
    assert acl_recorder.calls == []


def test_create_app_restricts_the_default_directory_before_the_token_exists(
    tmp_path, monkeypatch
) -> None:
    import backend.app.main as main_module

    seen: list[tuple[Path, bool]] = []

    def recording_prepare(directory: Path, *, logger=None) -> bool:
        seen.append((Path(directory), (Path(directory) / "api_token").exists()))
        return True

    monkeypatch.setattr(main_module, "prepare_store_directory", recording_prepare)
    monkeypatch.delenv("CHANGE_ASSURANCE_DB_PATH", raising=False)
    monkeypatch.delenv("CHANGE_ASSURANCE_API_TOKEN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no legacy store in the working directory

    app = create_app(credential_store=InMemoryCredentialStore())

    assert seen == [(tmp_path / "Sentinel", False)]
    token_path = tmp_path / "Sentinel" / "api_token"
    assert token_path.read_text(encoding="utf-8").strip() == app.state.api_token


def test_create_app_never_restricts_an_operator_chosen_directory(tmp_path, monkeypatch) -> None:
    import backend.app.main as main_module

    seen: list[Path] = []
    monkeypatch.setattr(
        main_module, "prepare_store_directory",
        lambda directory, *, logger=None: seen.append(directory) or True,
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    create_app(
        settings=Settings(database_path=tmp_path / "Sentinel" / "db.sqlite3"),
        credential_store=InMemoryCredentialStore(),
    )

    assert seen == []


@pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")
def test_create_app_default_directory_has_no_inherited_aces(tmp_path, monkeypatch) -> None:
    import subprocess

    monkeypatch.delenv("CHANGE_ASSURANCE_DB_PATH", raising=False)
    monkeypatch.delenv("CHANGE_ASSURANCE_API_TOKEN", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # no legacy store in the working directory

    create_app(credential_store=InMemoryCredentialStore())

    listing = subprocess.run(
        ["icacls", str(tmp_path / "Sentinel")], capture_output=True, timeout=30, check=True
    ).stdout.decode(errors="replace")
    block = listing.replace("\r", "").strip().split("\n\n", 1)[0]
    assert "(I)" not in block
    assert "S-1-5-18" in block or "SYSTEM" in block.upper()


# ---- migrate_store (Task 3) ---------------------------------------------------------


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_source_store(root: Path) -> tuple[Path, str]:
    """A real initialized store with probe rows and an api_token beside it."""

    import sqlite3

    from backend.app.core.auth import load_or_create_api_token
    from backend.app.core.database import Database

    database_path = root / "change_assurance.sqlite3"
    Database(database_path).initialize()
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE migration_probe (value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO migration_probe (value) VALUES (?)", [("one",), ("two",), ("three",)]
        )
        connection.commit()
    finally:
        connection.close()
    token = load_or_create_api_token(database_path)
    return database_path, token


@pytest.fixture
def quiet_acl(monkeypatch) -> _AclRecorder:
    fake = _AclRecorder()
    monkeypatch.setattr(evidence_store, "restrict_to_current_user", fake)
    return fake


def test_migrate_store_round_trip_copies_the_database_and_rotates_the_token(
    tmp_path, quiet_acl
) -> None:
    import sqlite3

    from backend.app.core.database import Database

    source, token = _build_source_store(tmp_path / "old")
    source_token = source.parent / "api_token"
    source_hash, token_hash = _sha256(source), _sha256(source_token)
    target = tmp_path / "new" / "store" / "change_assurance.sqlite3"

    result = evidence_store.migrate_store(source=source, target=target)

    assert result.source_database == source.resolve()
    assert result.target_database == target
    assert result.target_token == target.parent / "api_token"
    assert result.token_rotated is True
    assert result.integrity == "ok"
    assert evidence_store._integrity_check(target) == [("ok",)]
    assert Database(target).schema_version() == Database(source).schema_version()
    connection = sqlite3.connect(target)
    try:
        rows = connection.execute("SELECT value FROM migration_probe ORDER BY rowid").fetchall()
    finally:
        connection.close()
    assert rows == [("one",), ("two",), ("three",)]
    new_token = (target.parent / "api_token").read_text(encoding="utf-8").strip()
    # Revised D-06: the legacy token is never copied; a fresh one is generated.
    assert new_token and new_token != token
    assert len(new_token) >= 40
    assert (target.parent / "api_token", False) in quiet_acl.calls
    assert _sha256(source) == source_hash
    assert _sha256(source_token) == token_hash


def test_a_migrated_store_is_accepted_by_create_app_with_the_rotated_token(
    tmp_path, quiet_acl
) -> None:
    source, token = _build_source_store(tmp_path / "old")
    target = tmp_path / "new" / "change_assurance.sqlite3"
    result = evidence_store.migrate_store(source=source, target=target)

    app = create_app(
        settings=Settings(database_path=target),
        credential_store=InMemoryCredentialStore(),
    )

    assert app.state.api_token == result.target_token.read_text(encoding="utf-8").strip()
    assert app.state.api_token != token
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200


def test_migrate_store_without_a_source_token_still_creates_a_fresh_one(tmp_path, quiet_acl) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    (source.parent / "api_token").unlink()
    target = tmp_path / "new" / "change_assurance.sqlite3"

    result = evidence_store.migrate_store(source=source, target=target)

    assert result.token_rotated is True
    assert (target.parent / "api_token").read_text(encoding="utf-8").strip()


def test_migrate_store_never_reads_the_legacy_token(tmp_path, quiet_acl, monkeypatch) -> None:
    source, token = _build_source_store(tmp_path / "old")
    legacy_token = (source.parent / "api_token").resolve()
    real_read_bytes, real_read_text = Path.read_bytes, Path.read_text

    def guarded_bytes(self):
        assert self.resolve() != legacy_token, "the legacy token must never be read"
        return real_read_bytes(self)

    def guarded_text(self, *args, **kwargs):
        assert self.resolve() != legacy_token, "the legacy token must never be read"
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", guarded_bytes)
    monkeypatch.setattr(Path, "read_text", guarded_text)
    target = tmp_path / "new" / "change_assurance.sqlite3"

    evidence_store.migrate_store(source=source, target=target)

    monkeypatch.setattr(Path, "read_text", real_read_text)
    assert (target.parent / "api_token").read_text(encoding="utf-8").strip() != token


def test_a_token_that_cannot_be_restricted_fails_and_rolls_back_the_migration(
    tmp_path, monkeypatch
) -> None:
    """Revised D-06: failure to restrict the new token is an error, not ignored."""

    source, _token = _build_source_store(tmp_path / "old")
    source_hash = _sha256(source)
    monkeypatch.setattr(
        evidence_store, "restrict_to_current_user",
        lambda path, *, directory=False: not Path(path).name == "api_token",
    )
    target = tmp_path / "new" / "change_assurance.sqlite3"

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=target)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_TOKEN_UNPROTECTED"
    assert caught.value.details == {"path": str(target.parent / "api_token")}
    assert not target.exists()
    assert not (target.parent / "api_token").exists()
    assert _sha256(source) == source_hash


def test_migrate_store_refuses_an_existing_target_database(tmp_path, quiet_acl) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    target = tmp_path / "new" / "change_assurance.sqlite3"
    target.parent.mkdir()
    target.write_bytes(b"existing store")
    before, source_hash = _sha256(target), _sha256(source)

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=target)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_TARGET_EXISTS"
    assert _sha256(target) == before
    assert _sha256(source) == source_hash
    assert not (target.parent / "api_token").exists()


def test_migrate_store_refuses_an_existing_target_token(tmp_path, quiet_acl) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    target = tmp_path / "new" / "change_assurance.sqlite3"
    target.parent.mkdir()
    existing_token = target.parent / "api_token"
    existing_token.write_text("someone else's token", encoding="utf-8")
    before, source_hash = _sha256(existing_token), _sha256(source)

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=target)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_TARGET_EXISTS"
    assert caught.value.details == {"path": str(existing_token)}
    assert _sha256(existing_token) == before
    assert _sha256(source) == source_hash
    assert not target.exists()


def test_migrate_store_refuses_the_source_as_its_own_target(tmp_path, quiet_acl) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    source_hash = _sha256(source)

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=source)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_TARGET_EXISTS"
    assert _sha256(source) == source_hash


def test_migrate_store_refuses_a_target_inside_a_repository(tmp_path, quiet_acl) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    source_hash = _sha256(source)
    repo = make_repo(tmp_path / "repo")
    target = repo / "state" / "change_assurance.sqlite3"

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=target)

    assert caught.value.code == "EVIDENCE_STORE_INSIDE_REPOSITORY"
    assert not (repo / "state").exists()
    assert _sha256(source) == source_hash


def test_migrate_store_refuses_a_missing_source(tmp_path, quiet_acl) -> None:
    target = tmp_path / "new" / "change_assurance.sqlite3"

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=tmp_path / "absent.sqlite3", target=target)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_SOURCE_MISSING"
    assert not target.parent.exists()


def test_migrate_store_refuses_a_junction_target_parent(tmp_path, quiet_acl) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    source_hash = _sha256(source)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linked"
    _junction(elsewhere, link)

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=link / "change_assurance.sqlite3")

    assert caught.value.code == "EVIDENCE_STORE_UNSAFE_LOCATION"
    assert list(elsewhere.iterdir()) == []
    assert _sha256(source) == source_hash


def test_an_integrity_failure_removes_only_what_this_call_created(
    tmp_path, quiet_acl, monkeypatch
) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    source_hash, token_hash = _sha256(source), _sha256(source.parent / "api_token")
    target_dir = tmp_path / "new"
    target_dir.mkdir()
    bystander = target_dir / "notes.txt"
    bystander.write_text("keep me", encoding="utf-8")
    target = target_dir / "change_assurance.sqlite3"
    monkeypatch.setattr(
        evidence_store, "_integrity_check", lambda path: [("*** page 3 is corrupt",)]
    )

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=target)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_INTEGRITY_FAILED"
    assert caught.value.status_code == 500
    assert sorted(path.name for path in target_dir.iterdir()) == ["notes.txt"]
    assert bystander.read_text(encoding="utf-8") == "keep me"
    assert _sha256(source) == source_hash
    assert _sha256(source.parent / "api_token") == token_hash


def test_migrating_into_the_default_directory_restricts_it(tmp_path, quiet_acl, monkeypatch) -> None:
    source, _token = _build_source_store(tmp_path / "old")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    target = default_database_path()

    evidence_store.migrate_store(source=source, target=target)

    assert quiet_acl.calls[0] == (tmp_path / "local" / "Sentinel", True)
    assert target.is_file()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_migrate_store_treats_an_existing_sidecar_as_an_existing_target(
    tmp_path, suffix
) -> None:
    """WR-07: a planted WAL must never be replayed onto the migrated copy."""

    source, _ = _build_source_store(tmp_path / "old")
    target = tmp_path / "new" / DATABASE_FILENAME
    target.parent.mkdir()
    planted = Path(f"{target}{suffix}")
    planted.write_bytes(b"planted")

    with pytest.raises(AppError) as caught:
        evidence_store.migrate_store(source=source, target=target)

    assert caught.value.code == "EVIDENCE_STORE_MIGRATION_TARGET_EXISTS"
    assert caught.value.details == {"path": str(planted)}
    assert not target.exists()
    assert planted.read_bytes() == b"planted"
