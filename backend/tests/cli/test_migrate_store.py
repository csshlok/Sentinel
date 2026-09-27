"""`sentinel migrate-store` CLI command (local, never contacts the API)."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backend.app.cli import main as cli_main
from backend.app.core import evidence_store
from backend.app.core.auth import load_or_create_api_token
from backend.app.core.database import Database

runner = CliRunner()
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class _AclRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, bool]] = []

    def __call__(self, path: Path, *, directory: bool = False) -> bool:
        self.calls.append((Path(path), directory))
        return True


@pytest.fixture
def acl_recorder(monkeypatch) -> _AclRecorder:
    fake = _AclRecorder()
    monkeypatch.setattr(evidence_store, "restrict_to_current_user", fake)
    return fake


def _store(directory: Path) -> tuple[Path, str]:
    database_path = directory / "change_assurance.sqlite3"
    Database(database_path).initialize()
    return database_path, load_or_create_api_token(database_path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_migrate_store_json_success(tmp_path, acl_recorder) -> None:
    source, token = _store(tmp_path / "old")
    target = tmp_path / "new" / "change_assurance.sqlite3"

    result = runner.invoke(
        cli_main.app, ["migrate-store", "--from", str(source), "--to", str(target), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["source"] == str(source.resolve())
    assert payload["target"] == str(target)
    assert payload["token_rotated"] is True
    assert payload["token_path"] == str(target.parent / "api_token")
    assert payload["integrity"] == "ok"
    assert str(source.resolve()) in payload["next_step"]
    assert "must re-read it" in payload["next_step"]
    assert "stale token" in payload["next_step"]
    new_token = (target.parent / "api_token").read_text(encoding="utf-8").strip()
    assert new_token and new_token != token
    assert source.is_file()
    assert (source.parent / "api_token").read_text(encoding="utf-8").strip() == token


def test_migrate_store_existing_target_exits_1_with_the_error_payload(tmp_path, acl_recorder) -> None:
    source, _token = _store(tmp_path / "old")
    target = tmp_path / "new" / "change_assurance.sqlite3"
    target.parent.mkdir()
    target.write_bytes(b"do not overwrite")
    before = _sha256(target)

    result = runner.invoke(
        cli_main.app, ["migrate-store", "--from", str(source), "--to", str(target), "--json"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "EVIDENCE_STORE_MIGRATION_TARGET_EXISTS"
    assert payload["error"]["details"] == {"path": str(target)}
    assert _sha256(target) == before


def test_migrate_store_plain_output_prints_code_and_message(tmp_path, acl_recorder) -> None:
    result = runner.invoke(
        cli_main.app,
        ["migrate-store", "--from", str(tmp_path / "absent.sqlite3"),
         "--to", str(tmp_path / "new.sqlite3"), "--no-color"],
    )

    assert result.exit_code == 1
    assert "EVIDENCE_STORE_MIGRATION_SOURCE_MISSING" in result.output


def test_migrate_store_defaults_move_the_legacy_store_to_localappdata(
    tmp_path, acl_recorder, monkeypatch
) -> None:
    legacy_source, token = _store(tmp_path / ".change-assurance")
    source_hash = _sha256(legacy_source)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    result = runner.invoke(cli_main.app, ["migrate-store", "--json"])

    assert result.exit_code == 0, result.output
    expected = tmp_path / "local" / "Sentinel" / "change_assurance.sqlite3"
    assert json.loads(result.stdout)["target"] == str(expected)
    assert expected.is_file()
    assert (expected.parent / "api_token").read_text(encoding="utf-8").strip() != token
    assert acl_recorder.calls[0] == (tmp_path / "local" / "Sentinel", True)
    assert _sha256(legacy_source) == source_hash


def test_migrate_store_file_system_errors_use_the_json_error_envelope(
    tmp_path, acl_recorder, monkeypatch
) -> None:
    """WR-09: no raw traceback; the stable exit code and envelope."""

    source, _token = _store(tmp_path / "old")
    target = tmp_path / "new" / "change_assurance.sqlite3"

    def failing_mkdir(self, *args, **kwargs):
        raise PermissionError(13, "Access is denied", str(self))

    monkeypatch.setattr(Path, "mkdir", failing_mkdir)
    result = runner.invoke(
        cli_main.app, ["migrate-store", "--from", str(source), "--to", str(target), "--json"]
    )

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "EVIDENCE_STORE_MIGRATION_IO_FAILED"
    assert payload["error"]["details"]["error"] == "PermissionError"


def test_pyproject_declares_the_sentinel_console_script() -> None:
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert project["scripts"]["sentinel"] == "backend.app.cli.main:main"
