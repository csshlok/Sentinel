"""A hostile workspace ``.git`` is refused before Sentinel runs Git on it (Pitfall 7).

The host test plants each state the way an agent could inside ``AC\\ws`` and
proves preview (and apply) raise ``WORKSPACE_GIT_TAMPERED`` naming the failed
check, with the user repository byte-for-byte unchanged -- before the refusal
and after cleanup (which must never follow a planted link into the user repo).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.core.errors import AppError
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.models import WorkspaceRecord
from backend.tests.support_kb import git, write
from backend.tests.workspace.conftest import create_junction, has_object, repo_fingerprint

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")


def _set_aside(path: Path) -> None:
    path.rename(path.with_name(path.name + "-set-aside"))


def _gitfile(ws: Path, user: Path) -> None:
    _set_aside(ws / ".git")
    (ws / ".git").write_text(f"gitdir: {(user / '.git').as_posix()}\n", encoding="utf-8")


def _git_junction(ws: Path, user: Path) -> None:
    _set_aside(ws / ".git")
    create_junction(user / ".git", ws / ".git")


def _ws_junction(ws: Path, user: Path) -> None:
    _set_aside(ws)
    create_junction(user, ws)


def _core_worktree(ws: Path, user: Path) -> None:
    git(ws, f"--git-dir={ws / '.git'}", "config", "core.worktree", str(user))


def _alternates(ws: Path, user: Path) -> None:
    info = ws / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(str(user / ".git" / "objects") + "\n", encoding="utf-8")


def _commondir(ws: Path, user: Path) -> None:
    (ws / ".git" / "commondir").write_text(str(user / ".git") + "\n", encoding="utf-8")


def _refs_junction(ws: Path, user: Path) -> None:
    # A junction deeper inside .git: a seal commit would update the USER's branch ref.
    _set_aside(ws / ".git" / "refs" / "heads")
    create_junction(user / ".git" / "refs" / "heads", ws / ".git" / "refs" / "heads")


HOSTILE: list[tuple[str, Callable[[Path, Path], None], str]] = [
    ("gitfile", _gitfile, "git_dir_type"),
    ("git-junction", _git_junction, "git_dir_type"),
    ("ws-junction", _ws_junction, "workspace_path"),
    ("core-worktree", _core_worktree, "core_worktree"),
    ("alternates", _alternates, "alternates"),
    ("commondir", _commondir, "commondir"),
    ("refs-junction", _refs_junction, "git_dir_links"),
]


def _user_state(user: Path) -> tuple[dict[str, str], str, str]:
    return (repo_fingerprint(user), git(user, "status", "--porcelain"),
            git(user, "log", "-1", "--format=%H %s"))


def _assert_cleanup_leaves_user_repo(manager, record: WorkspaceRecord, user: Path,
                                     before) -> None:
    cleaned = manager.cleanup(record.id)
    assert cleaned.state == WorkspaceState.CLEANED
    assert _user_state(user) == before
    assert (user / ".git" / "refs" / "heads" / "main").is_file()
    assert (user / "calc.py").is_file()


@pytest.mark.parametrize(("plant", "check"), [(p, c) for _, p, c in HOSTILE],
                         ids=[name for name, _, _ in HOSTILE])
def test_preview_refuses_a_hostile_workspace_git(
    workspace_manager, user_repo: Path, plant, check: str,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    write(record.workspace_path, "agent.txt", "agent output\n")
    before = _user_state(user_repo)

    plant(record.workspace_path, user_repo)
    with pytest.raises(AppError) as raised:
        workspace_manager.preview(change_id)

    assert raised.value.code == "WORKSPACE_GIT_TAMPERED"
    assert raised.value.details == {"check": check}
    assert _user_state(user_repo) == before
    assert not (user_repo / "agent.txt").exists()
    assert workspace_manager.get(record.id).state == WorkspaceState.READY
    _assert_cleanup_leaves_user_repo(workspace_manager, record, user_repo, before)


@pytest.mark.parametrize(("plant", "check"), [(_gitfile, "git_dir_type"),
                                              (_core_worktree, "core_worktree")],
                         ids=["gitfile", "core-worktree"])
def test_apply_revalidates_the_workspace_git_before_any_fetch(
    workspace_manager, user_repo: Path, plant, check: str,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    write(record.workspace_path, "agent.txt", "agent output\n")
    preview = workspace_manager.preview(change_id)
    before = _user_state(user_repo)

    plant(record.workspace_path, user_repo)
    with pytest.raises(AppError) as raised:
        workspace_manager.apply(change_id, preview.approval_token)

    assert raised.value.code == "WORKSPACE_GIT_TAMPERED"
    assert raised.value.details == {"check": check}
    assert _user_state(user_repo) == before
    assert not has_object(user_repo, preview.sealed_sha)  # nothing was fetched
    assert git(user_repo, "for-each-ref", "refs/sentinel/").strip() == ""
    _assert_cleanup_leaves_user_repo(workspace_manager, record, user_repo, before)
