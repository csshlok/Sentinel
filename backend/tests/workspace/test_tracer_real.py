"""Tracer: a node agent inside a verified AppContainer edits a Sentinel workspace and the
sealed change fast-forwards into the user's repository (real Windows, no fakes)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.execution._process import capture
from backend.app.execution.appcontainer import (
    LOW_INTEGRITY_RID,
    base_environment,
    local_appdata_known_folder,
    profile_exists,
    spawn_appcontainer_supervised,
)
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.support_kb import git
from backend.tests.workspace.conftest import repo_fingerprint

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

AGENT_SCRIPT = "\n".join([
    "const fs = require('fs');",
    f"fs.writeFileSync('created.txt', {json.dumps('created by the boxed agent' + chr(10))});",
    f"fs.appendFileSync('calc.py', {json.dumps(chr(10) + 'def sub(a, b):' + chr(10) + '    return a - b' + chr(10))});",
    "fs.renameSync('rename_me.txt', 'renamed.txt');",
    "fs.unlinkSync('delete_me.txt');",
    "process.stdout.write('agent done');",
])


def _lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _loose_object(workspace: Path) -> Path:
    objects = workspace / ".git" / "objects"
    for directory in sorted(objects.iterdir()):
        if len(directory.name) == 2 and directory.is_dir():
            for item in directory.iterdir():
                return item
    for item in objects.rglob("*"):
        if item.is_file():
            return item
    raise AssertionError("the workspace has no object files")


def test_node_agent_edits_workspace_and_changes_fast_forward_into_user_repo(
    workspace_manager, user_repo: Path, node_exe: str,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    assert record.state == WorkspaceState.READY
    packages = local_appdata_known_folder() / "Packages" / record.profile_name
    assert os.path.normcase(str(record.workspace_path)) == os.path.normcase(
        str(packages / "AC" / "ws"))
    assert record.base_sha == git(user_repo, "rev-parse", "HEAD").strip()
    assert record.base_branch == "refs/heads/main"
    assert os.stat(_loose_object(record.workspace_path)).st_nlink == 1  # --no-hardlinks

    before = repo_fingerprint(user_repo)

    spawned = []

    def factory(argv, cwd, env):
        process = spawn_appcontainer_supervised(
            argv, cwd=cwd, env=env, redact=lambda text: text,
            profile_name=record.profile_name, expected_package_sid=record.package_sid,
            capabilities=(),
        )
        spawned.append(process)
        return process

    env = base_environment(record.container_path, path_entries=[Path(node_exe).parent])
    result = capture(
        [node_exe, "-e", AGENT_SCRIPT], cwd=record.workspace_path, env=env,
        timeout=60, limit=65_536, process_factory=factory,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"agent done"
    facts = spawned[0].appcontainer
    assert facts.is_appcontainer is True
    assert facts.package_sid == record.package_sid
    assert facts.integrity_rid == LOW_INTEGRITY_RID
    assert facts.capability_sids == ()
    assert facts.job_verified is True
    assert spawned[0].restricted_token_applied is False

    assert repo_fingerprint(user_repo) == before  # the agent run never touched the user repo

    preview = workspace_manager.preview(change_id)
    assert preview.base_sha == record.base_sha
    assert preview.sealed_sha != preview.base_sha
    assert len(preview.commits) == 1
    assert set(preview.changed_paths) == {
        ("A", "created.txt"), ("M", "calc.py"), ("D", "delete_me.txt"),
        ("D", "rename_me.txt"), ("A", "renamed.txt"),
    }
    assert preview.approval_token
    sealed = workspace_manager.get(record.id)
    assert sealed.state == WorkspaceState.SEALED
    assert preview.approval_token not in sealed.to_json()
    assert repo_fingerprint(user_repo) == before  # preview is workspace-only

    applied = workspace_manager.apply(change_id, preview.approval_token)

    assert git(user_repo, "rev-parse", "HEAD").strip() == preview.sealed_sha
    assert git(user_repo, "symbolic-ref", "HEAD").strip() == "refs/heads/main"
    assert _lf(user_repo / "created.txt") == "created by the boxed agent\n"
    assert _lf(user_repo / "calc.py") == (
        "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    assert _lf(user_repo / "renamed.txt") == "rename me\n"
    assert not (user_repo / "rename_me.txt").exists()
    assert not (user_repo / "delete_me.txt").exists()
    assert git(user_repo, "log", "-1", "--format=%an <%ae>").strip() == (
        "Sentinel Recovery <recovery@sentinel.invalid>")
    assert git(user_repo, "for-each-ref", "refs/sentinel/").strip() == ""
    after = repo_fingerprint(user_repo)
    for key in ("sddl_root", "sddl_git", "config_sha256", "head_ref"):
        assert after[key] == before[key], key

    assert applied.state == WorkspaceState.CLEANED
    assert applied.applied_sha == preview.sealed_sha
    assert applied.cleaned_at is not None
    assert not os.path.lexists(packages)
    assert profile_exists(record.profile_name) is False
