"""Hostile workspace configuration is inert during preview and apply (threat T-01-16).

The "agent" plants hooks, filters, ``core.fsmonitor``,
``uploadpack.packObjectsHook``, ``core.sshCommand``, ``diff.external`` and
``core.pager`` in ``AC\\ws\\.git`` (and a ``post-merge`` hook in the user
repository). Each mechanism writes a distinct canary file, using an absolute
path baked into a script, into a directory outside every repository.
Evidence only counts because the positive control shows the same planted
configuration firing under plain ``git.exe`` on this machine.

A5 probe: a node process inside the AppContainer tries to create a junction
and a directory symbolic link in the workspace pointing at the user's
``.git``; the outcome is recorded and either way the sealed tree never
contains anything below a link. Because Git for Windows descends into
junctions (measured here), a junction anywhere in the work tree refuses the
seal; a true symbolic link is sealed as a flagged ``120000`` link.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import WorkspaceState
from backend.app.core.errors import AppError
from backend.app.execution._process import capture
from backend.app.execution.appcontainer import base_environment, spawn_appcontainer_supervised
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.manager import PREVIEW_LIMITATIONS
from backend.tests.support_kb import git, write
from backend.tests.workspace.conftest import create_junction, has_object, repo_fingerprint

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="real AppContainers are Windows-only")

WS_HOOKS = ("pre-commit", "post-commit", "commit-msg", "post-checkout", "pre-push",
            "reference-transaction", "pre-auto-gc", "post-rewrite")


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def _script(path: Path, canary: Path, tail: str = "") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"#!/bin/sh\necho hit > '{_posix(canary)}'\n{tail}".encode("utf-8"))
    return _posix(path)


def _plain_git() -> str:
    found = shutil.which("git")
    assert found, "git must be on PATH for the positive control"
    return found


def _plain(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_plain_git(), "-C", str(repo), "-c", "user.name=Control", "-c",
         "user.email=control@example.test", *args],
        capture_output=True, text=True,
    )


def _canaries(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def _arm_workspace(ws: Path, tools: Path, canaries: Path) -> None:
    hooks = ws / ".git" / "hooks"
    for name in WS_HOOKS:
        _script(hooks / name, canaries / f"ws-hook-{name}", "exit 0\n")

    def tool(name: str, tail: str = "") -> str:
        return _script(tools / name, canaries / name, tail)

    config = {
        "filter.evil.clean": tool("filter-clean", "cat\n"),
        "filter.evil.smudge": tool("filter-smudge", "cat\n"),
        "filter.evil.process": tool("filter-process", "exit 1\n"),
        "core.fsmonitor": tool("fsmonitor", "exit 1\n"),
        "uploadpack.packObjectsHook": tool("pack-objects-hook", 'exec "$@"\n'),
        "core.sshCommand": tool("ssh-command", "exit 1\n"),
        "diff.external": tool("diff-external"),
        "core.pager": tool("pager", "cat\n"),
    }
    for key, value in config.items():
        git(ws, f"--git-dir={ws / '.git'}", "config", key, value)
    write(ws, ".gitattributes", "* filter=evil\n")


def test_planted_workspace_config_never_runs_during_preview_or_apply(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    canaries = tmp_path / "canaries"
    canaries.mkdir()
    tools = tmp_path / "evil-tools"
    _script(user_repo / ".git" / "hooks" / "post-merge", canaries / "user-hook-post-merge",
            "exit 0\n")
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    ws = record.workspace_path
    write(ws, "calc.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    _arm_workspace(ws, tools, canaries)
    control = tmp_path / "control-copy"
    shutil.copytree(ws, control, symlinks=True)  # armed exactly like the workspace

    preview = workspace_manager.preview(change_id)
    applied = workspace_manager.apply(change_id, preview.approval_token)

    assert _canaries(canaries) == []
    assert applied.state == WorkspaceState.CLEANED
    assert git(user_repo, "rev-parse", "HEAD").strip() == preview.sealed_sha
    assert "The repository's own Git hooks (for example post-merge) do not run during " \
           "apply-back." in preview.limitations
    assert set(PREVIEW_LIMITATIONS) <= set(preview.limitations)

    # Positive control: the same planted configuration fires under plain git. The
    # process filter (it exits 1) makes plain `git add` fatal, so step 1 proves it
    # and fsmonitor fire; step 2 drops only the process filter so the clean filter
    # and the commit hooks run.
    write(control, "control.txt", "control\n")
    first = _plain(control, "add", "-A")
    fired = _canaries(canaries)
    assert {"filter-process", "fsmonitor"} <= set(fired), (fired, first.stderr)
    assert _plain(control, "config", "--unset", "filter.evil.process").returncode == 0
    # Some Git versions still stage the file after the failed process filter; new
    # content forces the clean filter to run on this add either way.
    write(control, "control.txt", "control, second add\n")
    added = _plain(control, "add", "-A")
    committed = _plain(control, "commit", "-q", "-m", "control")
    fired = _canaries(canaries)
    assert added.returncode == 0 and committed.returncode == 0, (added.stderr, committed.stderr)
    assert {"filter-clean", "ws-hook-pre-commit", "ws-hook-commit-msg",
            "ws-hook-post-commit"} <= set(fired), fired

    # Positive control for the user repository's post-merge hook: apply-back runs
    # `merge --ff-only` there, and the same fast-forward under plain git fires it.
    merge_control = tmp_path / "merge-control"
    shutil.copytree(user_repo, merge_control, symlinks=True)
    assert _plain(merge_control, "reset", "-q", "--hard", preview.base_sha).returncode == 0
    merged = _plain(merge_control, "merge", "--ff-only", "-q", preview.sealed_sha)
    assert merged.returncode == 0, merged.stderr
    assert "user-hook-post-merge" in _canaries(canaries)




def _seal_blocked(manager, change_id, ws: Path, base: str) -> None:
    with pytest.raises(AppError) as raised:
        manager.preview(change_id)
    assert raised.value.code == "WORKSPACE_GIT_TAMPERED"
    assert raised.value.details == {"check": "worktree_links"}
    assert git(ws, "rev-parse", "HEAD").strip() == base  # nothing was sealed
    assert git(ws, "diff", "--cached", "--name-only").strip() == ""  # nothing staged


def test_a5_agent_links_to_the_user_git_never_reach_the_sealed_tree(
    workspace_manager, user_repo: Path, node_exe: str, record_property,
) -> None:
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    ws = record.workspace_path
    target = json.dumps(str(user_repo / ".git"))
    script = "\n".join([
        "const fs = require('fs');",
        "const out = {};",
        "for (const [name, kind] of [['agent-junction', 'junction'], ['agent-dirlink', 'dir']]) {",
        f"  try {{ fs.symlinkSync({target}, name, kind); out[kind] = 'created'; }}",
        "  catch (e) { out[kind] = e.code || String(e); }",
        "}",
        "process.stdout.write(JSON.stringify(out));",
    ])

    def factory(argv, cwd, env):
        return spawn_appcontainer_supervised(
            argv, cwd=cwd, env=env, redact=lambda text: text,
            profile_name=record.profile_name, expected_package_sid=record.package_sid,
            capabilities=(),
        )

    env = base_environment(record.container_path, path_entries=[Path(node_exe).parent])
    result = capture([node_exe, "-e", script], cwd=ws, env=env, timeout=60, limit=65_536,
                     process_factory=factory)
    assert result.returncode == 0, result.stderr
    outcome = json.loads(result.stdout)
    junction = os.path.lexists(ws / "agent-junction")
    dirlink = os.path.lexists(ws / "agent-dirlink")
    outcome.update(junction_on_disk=junction, dirlink_on_disk=dirlink)
    record_property("a5_container_links", json.dumps(outcome, sort_keys=True))
    before = repo_fingerprint(user_repo)

    if junction:
        _seal_blocked(workspace_manager, change_id, ws, record.base_sha)
    else:
        preview = workspace_manager.preview(change_id)
        tree = git(ws, "ls-tree", "-r", "--name-only", preview.sealed_sha).splitlines()
        assert not [path for path in tree if path.startswith(("agent-junction/",
                                                              "agent-dirlink/"))]
        flagged = {path: flags for _s, path, _o, _n, flags in preview.changed_paths}
        assert "agent-junction" not in flagged
        if dirlink:
            assert "symlink" in flagged.get("agent-dirlink", ()), preview.changed_paths
    assert repo_fingerprint(user_repo) == before


def test_worktree_junction_is_refused_before_anything_is_read_through_it(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    """Git for Windows descends into junctions, so a planted one must stop the seal."""

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = b"outside secret, unreadable by the container\n"
    (outside / "secret.txt").write_bytes(secret)
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    ws = record.workspace_path
    (ws / "deep" / "er").mkdir(parents=True)
    create_junction(outside, ws / "deep" / "er" / "planted-link")
    blob = subprocess.run([_plain_git(), "hash-object", "--stdin"], input=secret,
                          capture_output=True).stdout.decode().strip()

    _seal_blocked(workspace_manager, change_id, ws, record.base_sha)

    assert not has_object(ws, blob, kind="blob")  # never copied into the agent's store
    workspace_manager.cleanup(record.id)
    assert (outside / "secret.txt").read_bytes() == secret


def test_true_symbolic_link_is_sealed_as_a_flagged_link_not_followed(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside secret\n")
    change_id = uuid4()
    record = workspace_manager.create(change_id, user_repo)
    ws = record.workspace_path
    try:
        os.symlink(outside, ws / "dir-link", target_is_directory=True)
    except OSError as exc:  # needs Developer Mode or the symlink privilege
        pytest.fail(f"this machine cannot create symbolic links: {exc}")

    preview = workspace_manager.preview(change_id)

    tree = git(ws, "ls-tree", "-r", "--name-only", preview.sealed_sha).splitlines()
    assert "dir-link" in tree
    assert not [path for path in tree if path.startswith("dir-link/")]
    flagged = {path: (new, flags) for _s, path, _o, new, flags in preview.changed_paths}
    assert flagged["dir-link"] == ("120000", ("symlink",))
    assert "outside secret" not in preview.patch
    workspace_manager.cleanup(record.id)
    assert (outside / "secret.txt").read_bytes() == b"outside secret\n"
