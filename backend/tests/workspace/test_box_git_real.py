"""Git run by the agent inside the workspace AppContainer sees a clean checkout and can rename/delete.

Real Windows AppContainer with the ``claude`` runtime profile's environment
(``GIT_CONFIG_NOSYSTEM=1``, staged home, Git ``cmd`` on PATH), with Git itself
as the launched process. Before the workspace pinned its line-ending settings,
the boxed Git reported every CRLF-checked-out file as modified and ``git rm``
refused them (measured in the plan 01-04 live Claude Code run).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus, WorkspaceState
from backend.app.execution.agent_profiles import BUILTIN_PROFILES
from backend.app.execution.launcher import AgentAdapter, AgentLauncher
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.manager import WorkspaceManager
from backend.tests.support_kb import git
from backend.tests.workspace.conftest import HOSTED_RUNNER_APPCONTAINER_GAP, repo_fingerprint

pytestmark = [
    pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only"),
    HOSTED_RUNNER_APPCONTAINER_GAP,
]


def _boxed_git(workspace_manager: WorkspaceManager) -> AgentLauncher:
    profile = dataclasses.replace(BUILTIN_PROFILES["claude"], adapter="boxed-git",
                                  tool_snapshot=False, credential_kind=None)
    return AgentLauncher(adapters={"boxed-git": AgentAdapter("boxed-git", frozenset({"git"}))},
                         profiles={"boxed-git": profile}, workspaces=workspace_manager)


def test_boxed_git_sees_a_clean_checkout_and_renames_and_deletes(
    workspace_manager: WorkspaceManager, user_repo: Path,
) -> None:
    launcher = _boxed_git(workspace_manager)
    change_id = uuid4()
    before = repo_fingerprint(user_repo)

    def run(*args: str):
        result = launcher.launch(change_id, str(user_repo), AgentLaunchRequest(
            adapter="boxed-git", executable="git", args=list(args), timeout_seconds=60), 65_536)
        assert result.status is AgentRunStatus.PASSED, (args, result.stdout, result.stderr)
        assert "AppContainer" in (result.authority_reduction or "")
        return result

    assert run("status", "--porcelain").stdout == ""  # no phantom modifications
    run("mv", "rename_me.txt", "renamed.txt")
    run("rm", "-q", "delete_me.txt")
    status = run("status", "--porcelain").stdout.splitlines()
    assert sorted(status) == ["D  delete_me.txt", "R  rename_me.txt -> renamed.txt"]
    record = workspace_manager.live_for_change(change_id)
    assert record.runs[-1]["facts"]["is_appcontainer"] is True
    assert repo_fingerprint(user_repo) == before

    preview = workspace_manager.preview(change_id)
    assert {(status, path) for status, path, *_ in preview.changed_paths} == {
        ("D", "delete_me.txt"), ("D", "rename_me.txt"), ("A", "renamed.txt")}
    applied = workspace_manager.apply(change_id, preview.approval_token)
    assert applied.state == WorkspaceState.CLEANED
    assert (user_repo / "renamed.txt").read_bytes().replace(b"\r\n", b"\n") == b"rename me\n"
    assert not (user_repo / "rename_me.txt").exists()
    assert not (user_repo / "delete_me.txt").exists()
    # Clean under the line-ending setting apply-back checked out with (the
    # support helper itself forces core.autocrlf=false, so pass the real one).
    autocrlf = git(user_repo, "config", "--system", "--get", "core.autocrlf", check=False).strip()
    host_view = ["-c", f"core.autocrlf={autocrlf}"] if autocrlf else []
    assert git(user_repo, *host_view, "status", "--porcelain") == ""
