"""Read-only preview and the full apply-back refusal matrix (real Windows, real Git).

Workspace edits are made by the host directly in ``AC\\ws`` to simulate the
agent (the in-container edit path is proven by the tracer). Every refusal
asserts the user HEAD is unchanged, no ``refs/sentinel/*`` ref remains and
the recorded ``refusal_reason``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.core.errors import AppError
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace import manager as manager_module
from backend.app.workspace.manager import PREVIEW_LIMITATIONS
from backend.app.workspace.models import PREVIEW_PATCH_LIMIT, ApplyRefusal, path_flags
from backend.tests.support_kb import git, write
from backend.tests.workspace.conftest import has_object, repo_fingerprint

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")


def _head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def _no_private_refs(repo: Path) -> bool:
    return git(repo, "for-each-ref", "refs/sentinel/").strip() == ""


def _agent_edit(ws: Path) -> None:
    write(ws, "calc.py", "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    write(ws, "created.txt", "created by the agent\n")


def _assert_refused(manager, change_id, record_id, user_repo: Path, head: str,
                    reason: ApplyRefusal, token: str, sealed: str) -> None:
    refused = manager.apply(change_id, token)
    assert refused.state == WorkspaceState.APPLY_REFUSED
    assert refused.refusal_reason == reason.value
    assert refused.approval_digest is None  # a refusal voids the approval
    assert _head(user_repo) == head
    assert _no_private_refs(user_repo)
    assert manager.get(record_id).refusal_reason == reason.value
    with pytest.raises(AppError) as replay:  # the same token can never be retried
        manager.apply(change_id, token)
    assert replay.value.code == "WORKSPACE_APPROVAL_INVALID"
    assert _head(user_repo) == head


# --------------------------------------------------------------------- path flags (pure)


@pytest.mark.parametrize(("path", "old_mode", "new_mode", "expected"), [
    ("link", "000000", "120000", ("symlink",)),
    ("vendor/sub", "000000", "160000", ("gitlink",)),
    (".gitattributes", "100644", "100644", ("git-metadata",)),
    ("nested/.gitmodules", "000000", "100644", ("git-metadata",)),
    (".husky/pre-commit", "000000", "100755", ("hooks-like",)),
    (".githooks/post-merge", "000000", "100644", ("hooks-like",)),
    ("package.json", "100644", "100644", ("execution-bearing",)),
    ("web/package.json", "100644", "100644", ("execution-bearing",)),
    (".github/workflows/ci.yml", "000000", "100644", ("execution-bearing",)),
    ("tests/conftest.py", "000000", "100644", ("execution-bearing",)),
    ("setup.py", "100644", "100644", ("execution-bearing",)),
    ("setup.cfg", "100644", "100644", ("execution-bearing",)),
    ("pyproject.toml", "100644", "100644", ("execution-bearing",)),
    ("Makefile", "100644", "100644", ("execution-bearing",)),
    (".vscode/tasks.json", "000000", "100644", ("execution-bearing",)),
    ("scripts/build.PS1", "000000", "100644", ("execution-bearing",)),
    ("run.bat", "000000", "100644", ("execution-bearing",)),
    ("run.cmd", "000000", "100644", ("execution-bearing",)),
    ("src/app.py", "100644", "100644", ()),
    ("docs/package.json.md", "000000", "100644", ()),
])
def test_path_flags_classify_risky_paths(path, old_mode, new_mode, expected) -> None:
    assert path_flags(path, old_mode, new_mode) == expected


# --------------------------------------------------------------------- preview


@windows_only
def test_preview_is_read_only_and_describes_the_change(workspace_manager, user_repo) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    ws = record.workspace_path
    _agent_edit(ws)
    write(ws, "package.json", '{"scripts": {"postinstall": "node evil.js"}}\n')
    write(ws, ".gitattributes", "*.bin binary\n")
    write(ws, ".husky/pre-commit", "#!/bin/sh\n")
    write(ws, ".github/workflows/ci.yml", "on: push\n")
    # A symbolic link and a gitlink, staged the way an agent's own Git would.
    write(ws, "link", "../outside")
    # The agent's Git has symlinks disabled (host default varies: hosted runners
    # enable them), so the seal keeps the staged 120000 entry on any host.
    git(ws, "config", "--local", "core.symlinks", "false")
    blob = git(ws, "hash-object", "-w", "link").strip()
    git(ws, "-c", "core.symlinks=false", "update-index", "--add", "--cacheinfo",
        f"120000,{blob},link")
    (ws / "vendor-sub").mkdir()
    git(ws, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},vendor-sub")
    before = repo_fingerprint(user_repo)

    preview = workspace_manager.preview(change_id)

    assert repo_fingerprint(user_repo) == before
    assert not has_object(user_repo, preview.sealed_sha)  # nothing fetched into the user repo
    assert preview.approval_token
    assert preview.fast_forward_possible is True
    assert preview.refusal_reason is None
    assert preview.user_branch == "refs/heads/main"
    assert preview.user_head == _head(user_repo) == preview.base_sha
    assert len(preview.commits) == 1
    sha, author, subject = preview.commits[0]
    assert sha == preview.sealed_sha
    assert author == "Sentinel Recovery <recovery@sentinel.invalid>"
    assert subject == f"Sentinel workspace seal for change {change_id}"
    by_path = {path: (status, old, new, flags)
               for status, path, old, new, flags in preview.changed_paths}
    assert by_path["calc.py"] == ("M", "100644", "100644", ())
    assert by_path["created.txt"] == ("A", "000000", "100644", ())
    assert by_path["package.json"][3] == ("execution-bearing",)
    assert by_path[".gitattributes"][3] == ("git-metadata",)
    assert by_path[".husky/pre-commit"][3] == ("hooks-like",)
    assert by_path[".github/workflows/ci.yml"][3] == ("execution-bearing",)
    assert by_path["link"] == ("A", "000000", "120000", ("symlink",))
    assert by_path["vendor-sub"] == ("A", "000000", "160000", ("gitlink",))
    assert "+def mul(a, b):" in preview.patch
    assert preview.patch_truncated is False
    for limitation in PREVIEW_LIMITATIONS:
        assert limitation in preview.limitations


@windows_only
def test_large_change_truncates_the_patch(workspace_manager, user_repo) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    line = "x" * 99 + "\n"
    write(record.workspace_path, "big.txt", line * (PREVIEW_PATCH_LIMIT // 100 + 500))

    preview = workspace_manager.preview(change_id)

    assert preview.patch_truncated is True
    assert len(preview.patch.encode("utf-8")) <= PREVIEW_PATCH_LIMIT
    assert preview.approval_token  # truncation is disclosed, it does not block apply


@windows_only
def test_diverged_workspace_history_gets_no_approval(workspace_manager, user_repo) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    ws = record.workspace_path
    git(ws, "checkout", "-q", "--orphan", "unrelated")
    git(ws, "commit", "-q", "-m", "unrelated root")
    head = _head(user_repo)

    preview = workspace_manager.preview(change_id)

    assert preview.refusal_reason == ApplyRefusal.WORKSPACE_HISTORY_DIVERGED.value
    assert preview.approval_token is None
    assert preview.fast_forward_possible is False
    assert workspace_manager.get(record.id).approval_digest is None
    assert _head(user_repo) == head


# --------------------------------------------------------------------- user-side refusals


def _move(repo: Path) -> None:
    write(repo, "user.txt", "user work\n")
    git(repo, "add", "user.txt")
    git(repo, "commit", "-q", "-m", "user moved")


def _switch(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "elsewhere")


def _detach(repo: Path) -> None:
    git(repo, "checkout", "-q", "--detach", "HEAD")


USER_CHANGES: list[tuple[str, Callable[[Path], None], ApplyRefusal]] = [
    ("moved", _move, ApplyRefusal.USER_BRANCH_MOVED),
    ("switched", _switch, ApplyRefusal.USER_BRANCH_SWITCHED),
    ("detached", _detach, ApplyRefusal.USER_HEAD_DETACHED),
]


@windows_only
@pytest.mark.parametrize(("mutate", "reason"), [(m, r) for _, m, r in USER_CHANGES],
                         ids=[name for name, _, _ in USER_CHANGES])
def test_user_side_change_after_preview_refuses_apply(
    workspace_manager, user_repo, mutate, reason,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    _agent_edit(record.workspace_path)
    approved = workspace_manager.preview(change_id)
    mutate(user_repo)
    head = _head(user_repo)
    status = git(user_repo, "status", "--porcelain")

    # A fresh preview reports the same refusal and issues no token.
    again = workspace_manager.preview(change_id)
    assert again.fast_forward_possible is False
    assert again.refusal_reason == reason.value
    assert again.approval_token is None

    with pytest.raises(AppError) as voided:  # the fresh preview voided the old token
        workspace_manager.apply(change_id, approved.approval_token)
    assert voided.value.code == "WORKSPACE_APPROVAL_INVALID"
    assert _head(user_repo) == head
    assert not has_object(user_repo, approved.sealed_sha)
    assert git(user_repo, "status", "--porcelain") == status


@windows_only
@pytest.mark.parametrize(("mutate", "reason"), [(m, r) for _, m, r in USER_CHANGES],
                         ids=[name for name, _, _ in USER_CHANGES])
def test_apply_with_an_earlier_token_refuses_before_any_fetch(
    workspace_manager, user_repo, mutate, reason,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    _agent_edit(record.workspace_path)
    preview = workspace_manager.preview(change_id)
    mutate(user_repo)
    head = _head(user_repo)
    status = git(user_repo, "status", "--porcelain")

    _assert_refused(workspace_manager, change_id, record.id, user_repo, head, reason,
                    preview.approval_token, preview.sealed_sha)
    assert not has_object(user_repo, preview.sealed_sha)  # refused before the fetch
    assert git(user_repo, "status", "--porcelain") == status


@windows_only
def test_dirty_overlap_is_refused_and_keeps_the_users_edit(workspace_manager, user_repo) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    _agent_edit(record.workspace_path)
    preview = workspace_manager.preview(change_id)
    user_edit = "def add(a, b):\n    return b + a  # user's uncommitted edit\n"
    write(user_repo, "calc.py", user_edit)
    head = _head(user_repo)

    _assert_refused(workspace_manager, change_id, record.id, user_repo, head,
                    ApplyRefusal.FAST_FORWARD_REFUSED, preview.approval_token,
                    preview.sealed_sha)

    assert (user_repo / "calc.py").read_bytes().decode("utf-8") == user_edit
    assert not (user_repo / "created.txt").exists()
    limitation = workspace_manager.get(record.id).limitations[-1]
    assert limitation.startswith("git merge --ff-only refused:")
    assert len(limitation.encode("utf-8")) <= 4096 + 64


@windows_only
def test_non_overlapping_uncommitted_user_edit_still_applies(workspace_manager, user_repo) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    _agent_edit(record.workspace_path)
    preview = workspace_manager.preview(change_id)
    write(user_repo, "README.md", "user's uncommitted readme edit\n")

    applied = workspace_manager.apply(change_id, preview.approval_token)

    assert applied.applied_sha == preview.sealed_sha
    assert _head(user_repo) == preview.sealed_sha
    assert (user_repo / "README.md").read_bytes() == b"user's uncommitted readme edit\n"
    assert (user_repo / "created.txt").is_file()
    assert _no_private_refs(user_repo)


# --------------------------------------------------------------------- workspace-side refusals


def _ws_commit_after_preview(ws: Path) -> None:
    write(ws, "late.txt", "committed after the preview\n")
    git(ws, "add", "late.txt")
    git(ws, "commit", "-q", "-m", "late agent commit")


def _ws_dirty_after_preview(ws: Path) -> None:
    write(ws, "late.txt", "written after the preview\n")


@windows_only
@pytest.mark.parametrize("mutate", [_ws_commit_after_preview, _ws_dirty_after_preview],
                         ids=["head-moved", "dirty"])
def test_workspace_changed_after_preview_is_refused(workspace_manager, user_repo, mutate) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    _agent_edit(record.workspace_path)
    preview = workspace_manager.preview(change_id)
    mutate(record.workspace_path)
    head = _head(user_repo)
    before = repo_fingerprint(user_repo)

    _assert_refused(workspace_manager, change_id, record.id, user_repo, head,
                    ApplyRefusal.SEALED_COMMIT_MISMATCH, preview.approval_token,
                    preview.sealed_sha)
    assert repo_fingerprint(user_repo) == before
    assert not (user_repo / "late.txt").exists()


# --------------------------------------------------------------------- token lifecycle


@windows_only
def test_second_preview_voids_the_first_token_and_replay_runs_no_git(
    workspace_manager, user_repo, monkeypatch,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    _agent_edit(record.workspace_path)
    first = workspace_manager.preview(change_id)
    second = workspace_manager.preview(change_id)
    assert first.approval_token != second.approval_token
    assert first.sealed_sha == second.sealed_sha

    with pytest.raises(AppError) as raised:
        workspace_manager.apply(change_id, first.approval_token)
    assert raised.value.code == "WORKSPACE_APPROVAL_INVALID"

    applied = workspace_manager.apply(change_id, second.approval_token)
    assert applied.state == WorkspaceState.CLEANED
    assert _head(user_repo) == second.sealed_sha

    calls: list[object] = []
    real_run_git = manager_module.run_git

    def spy(*args, **kwargs):
        calls.append(args)
        return real_run_git(*args, **kwargs)

    monkeypatch.setattr(manager_module, "run_git", spy)
    replayed = workspace_manager.apply(change_id, second.approval_token)
    assert replayed == applied
    assert calls == []
    with pytest.raises(AppError) as wrong:
        workspace_manager.apply(change_id, first.approval_token)
    assert wrong.value.code == "WORKSPACE_APPROVAL_INVALID"
    assert calls == []
