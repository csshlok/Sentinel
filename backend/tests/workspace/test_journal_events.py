"""D-07: every workspace transition is journaled atomically, with no secret material.

The flows run real AppContainer profiles and real Git (Windows-only); the
mapping, rollback and missing-Change cases use a real SQLite database with a
real ``changes`` row created through the HTTP API.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts.models import (
    ChangeWorkspace,
    JournalEventType,
    WorkspaceApplyPreview,
    WorkspaceState,
)
from backend.app.core.config import Settings
from backend.app.core.journal import JournalWriter
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.agent_ports import CredentialFingerprint
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.main import create_app
from backend.app.workspace.manager import WorkspaceManager
from backend.app.workspace.models import (
    ApplyPreview,
    SweepReport,
    WorkspaceRecord,
    preview_to_contract,
    record_to_contract,
    sweep_to_contract,
)
from backend.tests.support_kb import git, make_repo, write
from backend.tests.workspace.conftest import (
    DUMMY_ACCESS_TOKEN,
    DUMMY_CREDENTIAL_KIND,
    DUMMY_REFRESH_TOKEN,
    TEST_PROFILE_PREFIX,
    dummy_credential_bytes,
    teardown_workspaces,
)

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

SHA_A = "a" * 40
SHA_B = "b" * 40
FACTS = {
    "profile_name": "sentinel.test.x", "package_sid": "S-1-15-2-1-2-3",
    "is_appcontainer": True, "integrity_rid": "0x1000",
    "capability_sids": ["S-1-15-3-1"], "job_verified": True,
    "verified_at": "2026-09-30T12:00:00+00:00",
}


@pytest.fixture
def api(tmp_path: Path):
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    client.__enter__()
    yield app, client
    client.__exit__(None, None, None)


@pytest.fixture
def journaled_manager(api):
    app, _client = api
    manager = WorkspaceManager(app.state.database, profile_prefix=TEST_PROFILE_PREFIX,
                               journal=JournalWriter(app.state.database))
    yield manager
    teardown_workspaces(manager)


def _change(client: TestClient, repo: Path) -> UUID:
    created = client.post("/api/v1/changes", json={
        "title": "workspace journal", "intent": "journal workspace transitions",
        "repository_path": str(repo)})
    assert created.status_code == 201, created.text
    return UUID(created.json()["id"])


def _workspace_events(client: TestClient, change_id: UUID) -> list[dict]:
    response = client.get(f"/api/v1/changes/{change_id}/events")
    assert response.status_code == 200, response.text
    return [item for item in response.json()["items"]
            if item["event_type"].startswith("workspace.")]


def _repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "user-repo", {
        "calc.py": "def add(a, b):\n    return a + b\n", "README.md": "hello\n"})


def _record(**changes) -> WorkspaceRecord:
    now = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    base = dict(
        id=uuid4(), change_id=uuid4(), state=WorkspaceState.SEALED,
        profile_name="sentinel.test.x", created_at=now, updated_at=now,
        package_sid="S-1-15-2-1-2-3", container_path=Path("C:/p/AC"),
        workspace_path=Path("C:/p/AC/ws"), source_repository=Path("C:/repo"),
        base_branch="refs/heads/main", base_sha=SHA_A, sealed_sha=SHA_B,
        approval_digest="d" * 64, approved_base_sha=SHA_A, approved_sealed_sha=SHA_B,
    )
    base.update(changes)
    return WorkspaceRecord(**base)


# --------------------------------------------------------------------- mapping (pure)


def test_record_to_contract_exposes_facts_and_a_boolean_for_staged_credentials() -> None:
    fingerprint = CredentialFingerprint.from_bytes(
        DUMMY_CREDENTIAL_KIND, dummy_credential_bytes()).to_payload()
    run_id = uuid4()
    record = _record(
        runs=({"run_id": str(run_id), "status": "COMPLETED", "facts": FACTS,
               "limitations": ["limit one"], "finished_at": "2026-09-30T12:05:00+00:00"},
              {"run_id": str(uuid4()), "status": "ERROR", "facts": None,
               "limitations": [], "finished_at": None}),
        credential_fingerprints=(fingerprint,),
    )
    view = record_to_contract(record)
    assert isinstance(ChangeWorkspace.model_validate(view.model_dump()), ChangeWorkspace)
    assert view.credential_staged is True
    assert view.profile_name == "sentinel.test.x"
    assert view.package_sid == "S-1-15-2-1-2-3"
    assert view.runs[0].run_id == run_id
    boundary = view.runs[0].boundary
    assert boundary is not None and boundary.is_appcontainer and boundary.job_verified
    assert boundary.integrity_rid == "0x1000"
    assert boundary.capability_sids == ["S-1-15-3-1"]
    assert view.runs[1].boundary is None
    dumped = view.model_dump_json()
    for secret in (fingerprint["file_sha256"], *fingerprint["token_digests"],
                   *fingerprint["blob_ids"], record.approval_digest):
        assert secret not in dumped
    assert "approval_digest" not in dumped and "fingerprint" not in dumped
    assert record_to_contract(_record()).credential_staged is False


def test_preview_and_sweep_map_to_their_contracts() -> None:
    preview = ApplyPreview(
        change_id=uuid4(), workspace_id=uuid4(), base_sha=SHA_A, sealed_sha=SHA_B,
        commits=((SHA_B, "Sentinel <s@example.invalid>", "seal"),),
        changed_paths=(("M", "calc.py", "100644", "100644", ()),
                       ("A", "run.bat", "000000", "100644", ("execution-bearing",))),
        approval_token="tok", user_branch="refs/heads/main", user_head=SHA_A,
        fast_forward_possible=True, patch="diff --git a/calc.py b/calc.py\n",
        limitations=("one",),
    )
    contract = preview_to_contract(preview)
    assert isinstance(WorkspaceApplyPreview.model_validate(contract.model_dump()),
                      WorkspaceApplyPreview)
    assert contract.changed_paths[1].flags == ["execution-bearing"]
    assert contract.commits[0].sha == SHA_B
    workspace_id = uuid4()
    report = sweep_to_contract(SweepReport(cleaned=(workspace_id,),
                                           failed=((uuid4(), "could not remove ws"),)))
    assert report.cleaned == [workspace_id] and report.preserved == []
    assert report.failed[0].reason == "could not remove ws"


# --------------------------------------------------------------------- atomicity


def test_a_failed_journal_append_rolls_the_transition_back(api, tmp_path) -> None:
    app, client = api
    change_id = _change(client, _repo(tmp_path))

    class FailingJournal(JournalWriter):
        def append(self, *args, **kwargs):
            raise RuntimeError("journal unavailable")

    manager = WorkspaceManager(app.state.database, profile_prefix=TEST_PROFILE_PREFIX,
                               journal=FailingJournal(app.state.database))
    record = _record(change_id=change_id, state=WorkspaceState.READY,
                     profile_name=TEST_PROFILE_PREFIX + uuid4().hex)
    manager.repository.insert(record)
    with pytest.raises(RuntimeError):
        manager._save(record, WorkspaceState.READY, state=WorkspaceState.SEALED,
                      event=JournalEventType.WORKSPACE_SEALED, payload={"sealed_sha": SHA_B})
    assert manager.get(record.id).state == WorkspaceState.READY
    assert _workspace_events(client, change_id) == []


def test_a_transition_for_a_deleted_change_skips_the_journal(api) -> None:
    app, _client = api
    manager = WorkspaceManager(app.state.database, profile_prefix=TEST_PROFILE_PREFIX,
                               journal=JournalWriter(app.state.database))
    record = _record(state=WorkspaceState.READY,
                     profile_name=TEST_PROFILE_PREFIX + uuid4().hex)  # no Change row
    manager.repository.insert(record)
    saved = manager._save(record, WorkspaceState.READY, state=WorkspaceState.SEALED,
                          event=JournalEventType.WORKSPACE_SEALED, payload={})
    assert saved.state == WorkspaceState.SEALED


# --------------------------------------------------------------------- real flows


def _assert_clean_payloads(events: list[dict], *secrets: str) -> None:
    text = json.dumps([event["payload"] for event in events])
    for secret in secrets:
        assert secret not in text
    for event in events:
        assert event["subject_type"] == "workspace"
        assert "patch" not in event["payload"]
        assert "approval_token" not in event["payload"]


@windows_only
def test_create_seal_apply_clean_is_journaled_in_order(api, journaled_manager, tmp_path):
    _app, client = api
    repo = _repo(tmp_path)
    change_id = _change(client, repo)
    record = journaled_manager.create(change_id, repo)
    fingerprint = CredentialFingerprint.from_bytes(DUMMY_CREDENTIAL_KIND,
                                                   dummy_credential_bytes())
    journaled_manager.record_credential(record.id, fingerprint)
    write(record.workspace_path, "calc.py",
          "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    preview = journaled_manager.preview(change_id)
    assert preview.approval_token
    journaled_manager.preview(change_id)  # same content: no second workspace.sealed
    fresh = journaled_manager.preview(change_id)
    applied = journaled_manager.apply(change_id, fresh.approval_token)
    assert applied.state == WorkspaceState.CLEANED

    events = _workspace_events(client, change_id)
    assert [event["event_type"] for event in events] == [
        "workspace.created", "workspace.sealed", "workspace.applied", "workspace.cleaned"]
    created, sealed, applied_event, cleaned = (event["payload"] for event in events)
    assert created["workspace_id"] == str(record.id)
    assert created["profile_name"] == record.profile_name
    assert created["base_sha"] == record.base_sha
    assert sealed["sealed_sha"] == preview.sealed_sha and sealed["base_sha"] == record.base_sha
    assert applied_event["applied_sha"] == preview.sealed_sha
    assert cleaned["reason"] == "applied"
    assert all(event["subject_id"] == str(record.id) for event in events)
    _assert_clean_payloads(
        events, preview.approval_token, fresh.approval_token, DUMMY_ACCESS_TOKEN,
        DUMMY_REFRESH_TOKEN, fingerprint.file_sha256, *fingerprint.token_digests,
        "return a * b")
    assert git(repo, "rev-parse", "HEAD").strip() == preview.sealed_sha


@windows_only
def test_refused_apply_and_discard_are_journaled(api, journaled_manager, tmp_path):
    _app, client = api
    repo = _repo(tmp_path)
    change_id = _change(client, repo)
    record = journaled_manager.create(change_id, repo)
    write(record.workspace_path, "new.txt", "agent output\n")
    preview = journaled_manager.preview(change_id)
    write(repo, "user.txt", "user moved on\n")
    git(repo, "add", "user.txt")
    git(repo, "commit", "-q", "-m", "user commit")
    refused = journaled_manager.apply(change_id, preview.approval_token)
    assert refused.state == WorkspaceState.APPLY_REFUSED
    journaled_manager.discard(change_id)

    events = _workspace_events(client, change_id)
    assert [event["event_type"] for event in events] == [
        "workspace.created", "workspace.sealed", "workspace.apply_refused",
        "workspace.cleaned"]
    assert events[2]["payload"]["reason"] == "USER_BRANCH_MOVED"
    assert events[2]["payload"]["workspace_id"] == str(record.id)
    assert events[3]["payload"]["reason"] == "discarded"
    _assert_clean_payloads(events, preview.approval_token, "agent output")


@windows_only
def test_sweep_cleanup_is_journaled_as_swept(api, journaled_manager, tmp_path):
    _app, client = api
    repo = _repo(tmp_path)
    change_id = _change(client, repo)
    record = journaled_manager.create(change_id, repo)
    journaled_manager._save(record, WorkspaceState.READY, state=WorkspaceState.DISCARDED)
    report = journaled_manager.sweep()
    assert report.cleaned == (record.id,)
    events = _workspace_events(client, change_id)
    assert [event["event_type"] for event in events] == [
        "workspace.created", "workspace.cleaned"]
    assert events[-1]["payload"]["reason"] == "swept"


@windows_only
def test_cleanup_without_a_change_row_still_reaches_cleaned(api, journaled_manager, tmp_path):
    repo = _repo(tmp_path)
    orphan = uuid4()  # never created as a Change: the journal append is skipped
    record = journaled_manager.create(orphan, repo)
    assert record.state == WorkspaceState.READY
    cleaned = journaled_manager.cleanup(record.id)
    assert cleaned.state == WorkspaceState.CLEANED
