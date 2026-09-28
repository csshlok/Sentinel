"""D-06: the broker stages an agent's model credential into a staged home and removes it.

Dummy credential files only: the real ~/.claude is never read here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import JournalEventType
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter, row_to_event
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.agent_ports import CredentialStager, git_blob_id
from backend.app.execution.process_supervisor import IS_WINDOWS

ACCESS = "sk-ant-oat01-CANARYaccessTOKEN-do-not-leak-0123456789"
REFRESH = "sk-ant-ort01-CANARYrefreshTOKEN-do-not-leak-9876543210"
KIND = "claude-oauth-file"

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows-only")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "host-home" / ".claude" / ".credentials.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": ACCESS, "refreshToken": REFRESH, "expiresAt": 1893456000000,
        "scopes": ["user:inference"], "subscriptionType": "max",
    }}), encoding="utf-8")
    os.utime(path, (1_700_000_000, 1_700_000_000))
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "AC" / "home"
    (path / ".claude").mkdir(parents=True)
    return path


@pytest.fixture
def journaled(tmp_path: Path):
    database = Database(tmp_path / "journal.sqlite3")
    database.initialize()
    change_id = uuid4()
    with database.connection(immediate=True) as connection:
        connection.execute(
            "INSERT INTO changes (id, title, intent, repository_path, created_at, updated_at) "
            "VALUES (?, 'T', 'I', 'C:\\repo', '2024-01-01T00:00:00+00:00', "
            "'2024-01-01T00:00:00+00:00')",
            (str(change_id),),
        )
    return database, change_id


def _broker(source: Path, **kwargs) -> CredentialBroker:
    return CredentialBroker(InMemoryCredentialStore(),
                            agent_credential_sources={KIND: source}, **kwargs)


def test_broker_is_a_credential_stager(source):
    assert isinstance(_broker(source), CredentialStager)


def test_stage_copies_the_bytes_and_leaves_the_source_untouched(source, home):
    before = (source.read_bytes(), os.stat(source).st_mtime_ns)
    staged = _broker(source).stage_agent_credential(uuid4(), KIND, home)
    assert staged is not None
    assert staged.path == home / ".claude" / ".credentials.json"
    assert staged.path.read_bytes() == source.read_bytes()
    assert git_blob_id(source.read_bytes()) in staged.fingerprint.blob_ids
    assert set(staged.redaction_values) == {ACCESS, REFRESH}
    assert ACCESS not in repr(staged)
    assert (source.read_bytes(), os.stat(source).st_mtime_ns) == before


def test_release_is_journaled_without_secret_material(source, home, journaled):
    database, change_id = journaled
    broker = _broker(source, journal=JournalWriter(database))
    assert broker.stage_agent_credential(change_id, KIND, home) is not None
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_events WHERE change_id = ?", (str(change_id),)).fetchall()
        blob = "\n".join(row["payload_json"] for row in connection.execute(
            "SELECT payload_json FROM journal_events").fetchall())
    events = [row_to_event(row) for row in rows
              if row["event_type"] == JournalEventType.CREDENTIAL_SECRET_RESOLVED.value]
    assert len(events) == 1
    assert set(events[0].payload) == {"provider", "scope", "delivery", "kind"}
    assert events[0].payload["kind"] == KIND
    for secret in (ACCESS, REFRESH, "CANARY"):
        assert secret not in blob


def test_journal_failure_deletes_the_staged_file(source, home):
    class BrokenJournal:
        def append(self, *args, **kwargs):
            raise RuntimeError("journal down")

    broker = _broker(source, journal=BrokenJournal())
    with pytest.raises(AppError) as caught:
        broker.stage_agent_credential(uuid4(), KIND, home)
    assert caught.value.code == "AGENT_CREDENTIAL_STAGING_FAILED"
    assert not (home / ".claude" / ".credentials.json").exists()


def test_planted_destination_is_never_overwritten(source, home):
    planted = home / ".claude" / ".credentials.json"
    planted.write_text("planted by the agent", encoding="utf-8")
    with pytest.raises(AppError) as caught:
        _broker(source).stage_agent_credential(uuid4(), KIND, home)
    assert caught.value.code == "AGENT_CREDENTIAL_STAGING_FAILED"
    assert planted.read_text(encoding="utf-8") == "planted by the agent"


@windows_only
@pytest.mark.parametrize("which", ["home", "claude"])
def test_reparse_home_or_claude_directory_is_refused(source, tmp_path, which):
    import _winapi

    outside = tmp_path / "outside"
    (outside / ".claude").mkdir(parents=True)
    ac = tmp_path / "AC2"
    ac.mkdir()
    if which == "home":
        _winapi.CreateJunction(str(outside), str(ac / "home"))
    else:
        (ac / "home").mkdir()
        _winapi.CreateJunction(str(outside / ".claude"), str(ac / "home" / ".claude"))
    with pytest.raises(AppError) as caught:
        _broker(source).stage_agent_credential(uuid4(), KIND, ac / "home")
    assert caught.value.code == "AGENT_CREDENTIAL_STAGING_FAILED"
    assert list((outside / ".claude").iterdir()) == []


def test_missing_source_returns_none_and_unknown_kind_is_refused(tmp_path, home):
    broker = _broker(tmp_path / "absent.json")
    assert broker.stage_agent_credential(uuid4(), KIND, home) is None
    with pytest.raises(AppError) as caught:
        broker.stage_agent_credential(uuid4(), "mystery-token", home)
    assert caught.value.code == "AGENT_CREDENTIAL_UNSUPPORTED"
    assert caught.value.status_code == 400


def test_revoke_deletes_and_never_writes_the_source(source, home):
    broker = _broker(source)
    before = (source.read_bytes(), os.stat(source).st_mtime_ns)
    staged = broker.stage_agent_credential(uuid4(), KIND, home)
    outcome = broker.revoke_staged_credential(staged)
    assert outcome.deleted and not outcome.changed_during_run
    assert not staged.path.exists()
    assert (source.read_bytes(), os.stat(source).st_mtime_ns) == before


def test_revoke_reports_a_changed_credential_and_still_deletes(source, home):
    broker = _broker(source)
    before = source.read_bytes()
    staged = broker.stage_agent_credential(uuid4(), KIND, home)
    staged.path.write_text('{"claudeAiOauth": {"accessToken": "refreshed"}}', encoding="utf-8")
    outcome = broker.revoke_staged_credential(staged)
    assert outcome.deleted and outcome.changed_during_run
    assert not staged.path.exists()
    assert source.read_bytes() == before  # never copied back


def test_revoke_of_an_already_removed_file(source, home):
    broker = _broker(source)
    staged = broker.stage_agent_credential(uuid4(), KIND, home)
    staged.path.unlink()
    outcome = broker.revoke_staged_credential(staged)
    assert outcome.deleted


def test_purge_removes_a_leftover_staged_file(source, home):
    broker = _broker(source)
    staged = broker.stage_agent_credential(uuid4(), KIND, home)
    assert broker.purge_staged_credentials(home) is True
    assert not staged.path.exists()
    assert broker.purge_staged_credentials(home) is True
    assert broker.purge_staged_credentials(home.parent / "absent") is True


@windows_only
def test_purge_never_deletes_through_a_junction(source, tmp_path):
    import _winapi

    outside = tmp_path / "real-home"
    (outside / ".claude").mkdir(parents=True)
    victim = outside / ".claude" / ".credentials.json"
    victim.write_text("the user's real login", encoding="utf-8")
    ac = tmp_path / "AC3"
    ac.mkdir()
    _winapi.CreateJunction(str(outside), str(ac / "home"))
    assert _broker(source).purge_staged_credentials(ac / "home") is True
    assert victim.read_text(encoding="utf-8") == "the user's real login"


def test_constructing_a_broker_does_not_read_the_home_directory(monkeypatch):
    def refuse():
        raise AssertionError("Path.home() must not be consulted at construction")

    monkeypatch.setattr(Path, "home", staticmethod(refuse))
    CredentialBroker(InMemoryCredentialStore())
