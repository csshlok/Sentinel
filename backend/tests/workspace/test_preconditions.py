"""Launch preconditions and the single-run lease of ``WorkspaceManager.ensure`` (real Windows).

D-03: tracked modifications refuse the launch, untracked files are disclosed.
D-04: a source with object alternates is refused. A BASELINE/source HEAD
mismatch is refused. One run holds a workspace at a time.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.core.errors import AppError
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.manager import (
    NO_BASELINE_LIMITATION,
    UNTRACKED_SOURCE_LIMITATION,
    WorkspaceManager,
)
from backend.app.workspace.models import WorkspaceRecord
from backend.tests.support_kb import git, make_repo, write
from backend.tests.workspace.conftest import (
    TEST_PROFILE_PREFIX,
    registered_test_profiles,
    repo_fingerprint,
    teardown_workspaces,
)

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")


def _code(raised: pytest.ExceptionInfo[AppError]) -> str:
    return raised.value.code


def _refused_without_side_effects(manager: WorkspaceManager, source: Path, code: str) -> None:
    profiles_before = registered_test_profiles()
    change_id = uuid4()
    with pytest.raises(AppError) as raised:
        manager.ensure(change_id, str(source), run_id=uuid4())
    assert _code(raised) == code
    assert manager.repository.latest_for_change(change_id) is None  # no row inserted
    assert registered_test_profiles() == profiles_before  # no profile created


@pytest.fixture
def baseline_manager(workspace_database):
    """A manager whose BASELINE lookup the test controls."""

    heads: dict = {}
    manager = WorkspaceManager(
        workspace_database, profile_prefix=TEST_PROFILE_PREFIX,
        baseline_head=lambda change_id: heads.get(change_id),
    )
    manager.baseline_heads = heads  # type: ignore[attr-defined]
    yield manager
    teardown_workspaces(manager)


# --------------------------------------------------------------------- source preconditions


@pytest.mark.parametrize("staged", [False, True], ids=["unstaged", "staged"])
def test_tracked_modification_refuses_launch_before_any_profile_exists(
    workspace_manager, user_repo: Path, staged: bool,
) -> None:
    write(user_repo, "calc.py", "def add(a, b):\n    return a - b\n")
    if staged:
        git(user_repo, "add", "calc.py")

    _refused_without_side_effects(workspace_manager, user_repo, "WORKSPACE_SOURCE_DIRTY")


def test_untracked_files_only_are_disclosed_not_refused(
    workspace_manager, user_repo: Path,
) -> None:
    write(user_repo, "notes-untracked.txt", "local only\n")
    change_id, run_id = uuid4(), uuid4()

    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_id)

    assert record.state == WorkspaceState.READY
    assert record.limitations.count(UNTRACKED_SOURCE_LIMITATION) == 1
    assert not (record.workspace_path / "notes-untracked.txt").exists()
    workspace_manager.finish_run(record.id, run_id, facts=None, status="succeeded")
    # A second launch does not repeat the disclosure.
    second = uuid4()
    again = workspace_manager.ensure(change_id, str(user_repo), run_id=second)
    assert again.limitations.count(UNTRACKED_SOURCE_LIMITATION) == 1
    workspace_manager.finish_run(record.id, second, facts=None, status="succeeded")


def test_detached_source_head_is_refused(workspace_manager, user_repo: Path) -> None:
    git(user_repo, "checkout", "-q", "--detach", "HEAD")

    _refused_without_side_effects(workspace_manager, user_repo, "WORKSPACE_SOURCE_DETACHED")


def test_source_with_object_alternates_is_refused(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    shared = tmp_path / "shared-clone"
    git(tmp_path, "clone", "-q", "--shared", str(user_repo), str(shared))
    assert (shared / ".git" / "objects" / "info" / "alternates").is_file()

    _refused_without_side_effects(workspace_manager, shared, "WORKSPACE_SOURCE_ALTERNATES")


# --------------------------------------------------------------------- BASELINE vs source HEAD


def test_baseline_head_different_from_source_head_is_refused(
    baseline_manager, user_repo: Path,
) -> None:
    change_id = uuid4()
    baseline_manager.baseline_heads[change_id] = "0" * 40
    profiles_before = registered_test_profiles()

    with pytest.raises(AppError) as raised:
        baseline_manager.ensure(change_id, str(user_repo), run_id=uuid4())

    assert _code(raised) == "WORKSPACE_BASE_MISMATCH"
    assert baseline_manager.repository.latest_for_change(change_id) is None
    assert registered_test_profiles() == profiles_before


def test_missing_baseline_is_disclosed(baseline_manager, user_repo: Path) -> None:
    change_id, run_id = uuid4(), uuid4()

    record = baseline_manager.ensure(change_id, str(user_repo), run_id=run_id)

    assert NO_BASELINE_LIMITATION in record.limitations
    baseline_manager.finish_run(record.id, run_id, facts=None, status="succeeded")


def test_matching_baseline_adds_no_limitation(baseline_manager, user_repo: Path) -> None:
    change_id, run_id = uuid4(), uuid4()
    baseline_manager.baseline_heads[change_id] = git(user_repo, "rev-parse", "HEAD").strip()

    record = baseline_manager.ensure(change_id, str(user_repo), run_id=run_id)

    assert record.state == WorkspaceState.READY
    assert NO_BASELINE_LIMITATION not in record.limitations
    baseline_manager.finish_run(record.id, run_id, facts=None, status="succeeded")


# --------------------------------------------------------------------- single-run lease


def test_second_run_is_busy_until_the_first_finishes(workspace_manager, user_repo: Path) -> None:
    change_id, run_a, run_b = uuid4(), uuid4(), uuid4()
    first = workspace_manager.ensure(change_id, str(user_repo), run_id=run_a)
    assert first.active_run_id == str(run_a)

    with pytest.raises(AppError) as raised:
        workspace_manager.ensure(change_id, str(user_repo), run_id=run_b)
    assert _code(raised) == "WORKSPACE_BUSY"
    # Nothing else may use the workspace while the run holds it.
    for operation in (lambda: workspace_manager.preview(change_id),
                      lambda: workspace_manager.cleanup(first.id)):
        with pytest.raises(AppError) as blocked:
            operation()
        assert _code(blocked) == "WORKSPACE_STATE_CONFLICT"

    facts = {"appcontainer": {"integrity_rid": "0x1000"}, "exit_code": 0}
    workspace_manager.finish_run(first.id, run_a, facts=facts, status="succeeded",
                                 limitations=("one limitation",))
    workspace_manager.finish_run(first.id, run_a, facts=facts, status="succeeded")  # idempotent

    finished = workspace_manager.get(first.id)
    assert finished.active_run_id is None
    assert len(finished.runs) == 1
    entry = finished.runs[0]
    assert entry["run_id"] == str(run_a)
    assert entry["status"] == "succeeded"
    assert entry["facts"] == facts
    assert entry["limitations"] == ["one limitation"]
    assert entry["finished_at"]

    second = workspace_manager.ensure(change_id, str(user_repo), run_id=run_b)
    assert second.id == first.id
    assert second.active_run_id == str(run_b)
    workspace_manager.finish_run(first.id, run_b, facts=None, status="failed")
    assert [run["run_id"] for run in workspace_manager.get(first.id).runs] == [
        str(run_a), str(run_b)]


def test_saving_a_stale_record_never_releases_the_lease(
    workspace_manager, user_repo: Path,
) -> None:
    change_id, run_id = uuid4(), uuid4()
    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_id)
    stale = dataclasses.replace(record, active_run_id=None, limitations=("x",))

    workspace_manager.repository.update(stale, expected_state=WorkspaceState.READY)

    assert workspace_manager.get(record.id).active_run_id == str(run_id)
    workspace_manager.finish_run(record.id, run_id, facts=None, status="succeeded")


def test_new_run_on_a_sealed_workspace_voids_the_earlier_approval(
    workspace_manager, user_repo: Path,
) -> None:
    change_id, run_a, run_b = uuid4(), uuid4(), uuid4()
    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_a)
    write(record.workspace_path, "agent.txt", "first run\n")
    workspace_manager.finish_run(record.id, run_a, facts=None, status="succeeded")
    preview = workspace_manager.preview(change_id)
    assert workspace_manager.get(record.id).state == WorkspaceState.SEALED
    before = repo_fingerprint(user_repo)

    again = workspace_manager.ensure(change_id, str(user_repo), run_id=run_b)

    assert again.state == WorkspaceState.READY
    assert again.approval_digest is None
    assert again.approved_sealed_sha is None
    workspace_manager.finish_run(record.id, run_b, facts=None, status="succeeded")
    with pytest.raises(AppError) as raised:
        workspace_manager.apply(change_id, preview.approval_token)
    assert _code(raised) == "WORKSPACE_APPROVAL_INVALID"
    assert repo_fingerprint(user_repo) == before
    assert not (user_repo / "agent.txt").exists()


def test_different_source_path_for_the_same_change_is_refused(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    change_id, run_id = uuid4(), uuid4()
    record = workspace_manager.ensure(change_id, str(user_repo), run_id=run_id)
    workspace_manager.finish_run(record.id, run_id, facts=None, status="succeeded")
    other = make_repo(tmp_path / "other-repo")

    with pytest.raises(AppError) as raised:
        workspace_manager.ensure(change_id, str(other), run_id=uuid4())

    assert _code(raised) == "WORKSPACE_SOURCE_MISMATCH"
    assert workspace_manager.get(record.id).active_run_id is None


def _insert_live(manager: WorkspaceManager, change_id, state: WorkspaceState,
                 source: Path) -> WorkspaceRecord:
    from backend.app.contracts.models import utc_now

    now = utc_now()
    return manager.repository.insert(WorkspaceRecord(
        id=uuid4(), change_id=change_id, state=state,
        profile_name=TEST_PROFILE_PREFIX + uuid4().hex, created_at=now, updated_at=now,
        source_repository=source, base_branch="refs/heads/main",
        base_sha=git(source, "rev-parse", "HEAD").strip(),
    ))


def test_workspace_still_being_created_is_busy(workspace_manager, user_repo: Path) -> None:
    change_id = uuid4()
    _insert_live(workspace_manager, change_id, WorkspaceState.CREATING, user_repo)

    with pytest.raises(AppError) as raised:
        workspace_manager.ensure(change_id, str(user_repo), run_id=uuid4())

    assert _code(raised) == "WORKSPACE_BUSY"


@pytest.mark.parametrize("state", [
    WorkspaceState.APPLIED, WorkspaceState.DISCARDED, WorkspaceState.CLEANUP_FAILED,
])
def test_workspace_awaiting_cleanup_is_refused(
    workspace_manager, user_repo: Path, state: WorkspaceState,
) -> None:
    change_id = uuid4()
    _insert_live(workspace_manager, change_id, state, user_repo)

    with pytest.raises(AppError) as raised:
        workspace_manager.ensure(change_id, str(user_repo), run_id=uuid4())

    assert _code(raised) == "WORKSPACE_CLEANUP_PENDING"
    assert raised.value.details["state"] == state.value
