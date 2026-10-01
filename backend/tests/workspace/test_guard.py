"""WorkspaceGuardedGitState: no current/evaluation/diff-gate evidence while agent work is unapplied.

Unit cases use a fake manager (platform-independent); ``unapplied_work`` state
cases use inserted rows, and the Git-backed cases and the API flow use real
AppContainer workspaces (Windows only).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.contracts.models import WorkspaceState, utc_now
from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.main import create_app
from backend.app.workspace.guard import WorkspaceGuardedGitState
from backend.app.workspace.models import WorkspaceRecord
from backend.tests.support_kb import git, make_repo, write
from backend.tests.workspace.conftest import TEST_PROFILE_PREFIX, teardown_workspaces

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

SHA = "a" * 40


# ---------------------------------------------------------------- unit: the guard


class FakeManager:
    def __init__(self, unapplied: bool) -> None:
        self.unapplied = unapplied
        self.asked: list[UUID] = []

    def unapplied_work(self, change_id: UUID) -> bool:
        self.asked.append(change_id)
        return self.unapplied


def _guard(unapplied: bool, monkeypatch) -> tuple[WorkspaceGuardedGitState, FakeManager, list]:
    from backend.app.git.state import GitStateTracker

    calls: list[tuple] = []

    def capture(self, *args, **kwargs):
        calls.append(("capture", args))
        return "checkpoint"

    def compare(self, *args, **kwargs):
        calls.append(("compare", args))
        return "comparison"

    def is_current(self, *args, **kwargs):
        calls.append(("is_current", args))
        return True

    monkeypatch.setattr(GitStateTracker, "capture", capture)
    monkeypatch.setattr(GitStateTracker, "compare", compare)
    monkeypatch.setattr(GitStateTracker, "is_current", is_current)
    manager = FakeManager(unapplied)
    return WorkspaceGuardedGitState(manager), manager, calls  # type: ignore[arg-type]


def test_baseline_capture_always_delegates(monkeypatch) -> None:
    guard, manager, calls = _guard(True, monkeypatch)
    change_id = uuid4()
    assert guard.capture(change_id, "baseline", "repo", 1, 1024) == "checkpoint"
    assert [name for name, _ in calls] == ["capture"]
    assert manager.asked == []


@pytest.mark.parametrize("name", ["current", "evaluation", "diff-gate", "after-agent"])
def test_non_baseline_capture_is_refused_with_unapplied_work(name, monkeypatch) -> None:
    guard, manager, calls = _guard(True, monkeypatch)
    change_id = uuid4()
    with pytest.raises(AppError) as raised:
        guard.capture(change_id, name, "repo", 1, 1024)
    assert raised.value.code == "WORKSPACE_NOT_APPLIED"
    assert raised.value.status_code == 409
    assert calls == []
    assert manager.asked == [change_id]


@pytest.mark.parametrize("name", ["current", "evaluation", "diff-gate"])
def test_non_baseline_capture_delegates_without_unapplied_work(name, monkeypatch) -> None:
    guard, _manager, calls = _guard(False, monkeypatch)
    assert guard.capture(uuid4(), name, "repo", 2, 1024) == "checkpoint"
    assert [entry for entry, _ in calls] == ["capture"]


def test_compare_and_is_current_always_delegate(monkeypatch) -> None:
    guard, manager, calls = _guard(True, monkeypatch)
    assert guard.compare("b", "c") == "comparison"  # type: ignore[arg-type]
    assert guard.is_current("c") is True  # type: ignore[arg-type]
    assert [name for name, _ in calls] == ["compare", "is_current"]
    assert manager.asked == []


# ---------------------------------------------------------------- unapplied_work: row states


@pytest.fixture
def row_manager(workspace_database):
    from backend.app.workspace.manager import WorkspaceManager

    return WorkspaceManager(workspace_database, profile_prefix=TEST_PROFILE_PREFIX)


def _insert(manager, state: WorkspaceState, **fields) -> WorkspaceRecord:
    now = utc_now()
    record = WorkspaceRecord(
        id=uuid4(), change_id=uuid4(), state=state,
        profile_name=TEST_PROFILE_PREFIX + uuid4().hex, created_at=now, updated_at=now,
        **fields,
    )
    return manager.repository.insert(record)


def test_no_workspace_means_no_unapplied_work(row_manager) -> None:
    assert row_manager.unapplied_work(uuid4()) is False
    assert row_manager.has_live_workspace(uuid4()) is False


def test_creating_is_unapplied_work(row_manager) -> None:
    record = _insert(row_manager, WorkspaceState.CREATING)
    assert row_manager.unapplied_work(record.change_id) is True
    assert row_manager.has_live_workspace(record.change_id) is True


@pytest.mark.parametrize("state", [WorkspaceState.APPLIED, WorkspaceState.DISCARDED,
                                   WorkspaceState.CLEANUP_FAILED])
def test_applied_discarded_and_cleanup_failed_hold_no_unapplied_work(row_manager, state) -> None:
    record = _insert(row_manager, state, base_sha=SHA)
    assert row_manager.unapplied_work(record.change_id) is False
    assert row_manager.has_live_workspace(record.change_id) is True


def test_cleaned_is_neither_live_nor_unapplied(row_manager) -> None:
    record = _insert(row_manager, WorkspaceState.CLEANED, base_sha=SHA)
    assert row_manager.unapplied_work(record.change_id) is False
    assert row_manager.has_live_workspace(record.change_id) is False


def test_an_active_run_is_unapplied_work(row_manager) -> None:
    record = _insert(row_manager, WorkspaceState.READY, base_sha=SHA)
    assert row_manager.repository.begin_run(record.id, uuid4(), updated_at=utc_now())
    assert row_manager.unapplied_work(record.change_id) is True


@pytest.mark.parametrize("state", [WorkspaceState.SEALED, WorkspaceState.APPLY_REFUSED])
def test_a_sealed_commit_beyond_base_is_unapplied_work(row_manager, state) -> None:
    record = _insert(row_manager, state, base_sha=SHA, sealed_sha="b" * 40)
    assert row_manager.unapplied_work(record.change_id) is True


def test_an_unreadable_workspace_fails_closed(row_manager, tmp_path) -> None:
    # READY with recorded paths that are not a valid workspace: the .git
    # validation fails, which must answer True, never False.
    record = _insert(row_manager, WorkspaceState.READY, base_sha=SHA,
                     container_path=tmp_path / "AC", workspace_path=tmp_path / "AC" / "ws")
    assert row_manager.unapplied_work(record.change_id) is True


# ---------------------------------------------------------------- unapplied_work: real Git


def ws_git(workspace: Path, *args: str) -> str:
    """Plain Git in the workspace with its own (pinned) line-ending config, as an agent would."""

    import subprocess

    return subprocess.run(
        ["git", "-c", "user.name=Agent", "-c", "user.email=agent@example.test",
         "-c", "commit.gpgsign=false", *args],
        cwd=workspace, capture_output=True, text=True, check=True,
    ).stdout


@windows_only
def test_clean_ready_workspace_has_no_unapplied_work(workspace_manager, user_repo) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    assert workspace_manager.unapplied_work(record.change_id) is False


@windows_only
def test_dirty_tree_and_untracked_file_are_unapplied_work(workspace_manager, user_repo) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    write(record.workspace_path, "calc.py", "def add(a, b):\n    return b + a\n")
    assert workspace_manager.unapplied_work(record.change_id) is True
    ws_git(record.workspace_path, "checkout", "--", "calc.py")
    assert workspace_manager.unapplied_work(record.change_id) is False
    write(record.workspace_path, "new.txt", "untracked\n")
    assert workspace_manager.unapplied_work(record.change_id) is True


@windows_only
def test_head_beyond_base_is_unapplied_work(workspace_manager, user_repo) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    write(record.workspace_path, "agent.txt", "committed by the agent\n")
    ws_git(record.workspace_path, "add", "agent.txt")
    ws_git(record.workspace_path, "commit", "-q", "-m", "agent commit")
    assert ws_git(record.workspace_path, "status", "--porcelain").strip() == ""
    assert workspace_manager.unapplied_work(record.change_id) is True


@windows_only
def test_tampered_git_fails_closed(workspace_manager, user_repo) -> None:
    record = workspace_manager.create(uuid4(), user_repo)
    (record.workspace_path / ".git" / "commondir").write_text("..\n", encoding="utf-8")
    assert workspace_manager.unapplied_work(record.change_id) is True


# ---------------------------------------------------------------- API (real)


FACTS = {
    "profile_name": "set-below", "package_sid": "S-1-15-2-1-2-3",
    "is_appcontainer": True, "integrity_rid": "0x1000",
    "capability_sids": ["S-1-15-3-1"], "job_verified": True,
    "verified_at": "2026-09-30T12:00:00+00:00",
}


@pytest.fixture
def api(tmp_path: Path):
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    manager = app.state.workspace_manager
    manager._prefix = TEST_PROFILE_PREFIX  # swept by the workspace conftest finalizer
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    client.__enter__()
    yield app, client
    teardown_workspaces(manager)
    client.__exit__(None, None, None)


def _setup(client: TestClient, repo: Path):
    created = client.post("/api/v1/changes", json={
        "title": "guarded evidence", "intent": "no vacuous evidence",
        "repository_path": str(repo), "contract": {"required_checks": ["pytest"]}})
    assert created.status_code == 201, created.text
    change = created.json()
    human = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}).json()
    agent = client.post("/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}).json()
    delegation = client.post("/api/v1/delegations", json={
        "grantor_id": human["id"], "grantee_id": agent["id"], "change_id": change["id"],
        "scopes": ["workspace.apply"], "ttl_seconds": 3600})
    assert delegation.status_code == 201, delegation.text
    return change, agent["id"]


def _agent_edits(app, change_id: str, repo: Path):
    manager = app.state.workspace_manager
    run_id = uuid4()
    record = manager.ensure(UUID(change_id), str(repo), run_id=run_id)
    write(record.workspace_path, "calc.py",
          "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    write(record.workspace_path, "notes.txt", "agent notes\n")
    manager.finish_run(record.id, run_id, facts={**FACTS, "profile_name": record.profile_name},
                       status="COMPLETED")
    return record


@windows_only
def test_current_evidence_is_refused_until_apply_back(api, tmp_path) -> None:
    app, client = api
    repo = make_repo(tmp_path / "user-repo", {
        "calc.py": "def add(a, b):\n    return a + b\n", "README.md": "hello\n"})
    change, agent = _setup(client, repo)
    base = f"/api/v1/changes/{change['id']}"

    baseline = client.post(f"{base}/evidence/baseline")
    assert baseline.status_code == 201, baseline.text
    _agent_edits(app, change["id"], repo)

    refused = client.post(f"{base}/evidence/current")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "WORKSPACE_NOT_APPLIED"

    plan = client.post(f"{base}/assurance/plan")
    assert plan.status_code == 201, plan.text
    facts = client.get(f"{base}/assurance/facts").json()
    assert facts["required_assurance_passed"] is False
    assert facts["assurance_fresh"] is False
    assert any("still in the Sentinel workspace" in reason for reason in facts["reasons"])

    preview = client.post(f"{base}/workspace/preview")
    assert preview.status_code == 200, preview.text
    applied = client.post(f"{base}/workspace/apply", json={
        "actor_id": agent, "approval_token": preview.json()["approval_token"]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True

    current = client.post(f"{base}/evidence/current")
    assert current.status_code == 201, current.text
    comparison = current.json()["comparison"]
    assert comparison["head_changed"] is True
    assert comparison["added_paths"] == ["notes.txt"]
    assert comparison["changed_paths"] == ["calc.py"]
    assert comparison["removed_paths"] == []
    assert set(comparison["added_paths"] + comparison["changed_paths"]) == {
        "calc.py", "notes.txt"}


@windows_only
def test_baseline_capture_is_allowed_after_a_workspace_exists(api, tmp_path) -> None:
    app, client = api
    repo = make_repo(tmp_path / "user-repo", {"README.md": "hello\n"})
    change, _agent = _setup(client, repo)
    base = f"/api/v1/changes/{change['id']}"
    _agent_edits(app, change["id"], repo)
    assert app.state.workspace_manager.unapplied_work(UUID(change["id"])) is True

    baseline = client.post(f"{base}/evidence/baseline")
    assert baseline.status_code == 201, baseline.text
    duplicate = client.post(f"{base}/evidence/baseline")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "BASELINE_EXISTS"
