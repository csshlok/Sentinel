"""Hostile-repository acceptance suite for the hardened Git harness.

Methodology. ``build_hostile_repository`` first creates an ordinary history
with plain Git and only then installs a hostile configuration: every hook in
``HOOK_NAMES`` in both ``.git/hooks`` and a repository-configured
``core.hooksPath`` directory, smudge/clean/process filters with
``required=true``, a filter defined only through an
``includeIf "gitdir:**/worktrees/**"`` include, ``core.fsmonitor``,
``diff.external``, diff/merge driver commands, ``gpg.program`` with
``commit.gpgSign=true``, ``core.sshCommand``, ``core.pager``, ``core.editor``,
``sequence.editor``, ``credential.helper`` and ``core.askPass``. Each mechanism
runs a script that writes a distinct canary file into ``canary_dir`` using an
absolute path baked into the script (never an environment variable: Sentinel's
minimal environment strips those, which would make a canary silently miss).

``assert_no_canaries`` after a Sentinel operation is only evidence when the
same mechanism demonstrably fires under plain Git on this machine, so every
mechanism that can be triggered positively has a positive-control test here
(or in ``backend/tests/git/test_safe_exec.py`` for the merge driver). Those
controls fail -- never skip -- when a canary does not appear.

Mechanisms with no Sentinel-reachable trigger (asserted absent only as part of
the whole-directory ``assert_no_canaries`` check, never claimed as positively
controlled): ``core.sshCommand`` and ``credential.helper``/``core.askPass``
(Sentinel performs no network operation), ``core.pager`` (``--no-pager``, and
output is a pipe), ``core.editor``/``sequence.editor`` (``--no-edit`` and
``--no-commit`` flows never open an editor), and the hooks ``pre-push``,
``push-to-checkout``, ``pre-rebase``, ``pre-auto-gc``, ``applypatch-msg``,
``pre-applypatch``, ``post-applypatch``, ``post-merge``, ``post-rewrite`` and
``pre-merge-commit`` (Sentinel never pushes, rebases, merges or applies
patches, and gc is disabled). Their static neutralization is asserted at the
argv level in ``test_safe_exec.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import RecoveryStatus
from backend.app.contracts.models import ChangedPathStatus
from backend.app.core.lifecycle_facts_service import RuntimeLifecycleFacts
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.errors import GitCommandError
from backend.app.git.state import GitStateTracker
from backend.app.providers.repository_slug import resolve_github_repository_slug
from backend.app.recovery.git_recovery import GitRecoveryEngine
from backend.tests.recovery.test_git_recovery import (
    _database,
    _seed_change_and_checkpoint,
)

HOOK_NAMES: tuple[str, ...] = (
    "pre-commit", "prepare-commit-msg", "commit-msg", "post-commit",
    "post-checkout", "post-merge", "post-rewrite", "reference-transaction",
    "post-index-change", "pre-auto-gc", "pre-rebase", "pre-merge-commit",
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-push",
    "push-to-checkout",
)


def plain_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Unhardened Git exactly as a user would run it (positive controls, fixtures)."""

    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, shell=False,
    )
    if check:
        assert result.returncode == 0, result.stderr
    return result


def _history_git(root: Path, *args: str) -> str:
    return plain_git(
        root, "-c", "user.name=Hostile Test", "-c", "user.email=hostile@example.test",
        "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args,
    ).stdout.strip()


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def _script(path: Path, canary: Path, tail: str = "") -> Path:
    body = f"#!/bin/sh\necho hit > '{_posix(canary)}'\n{tail}"
    path.write_bytes(body.encode("utf-8"))
    return path


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_bytes(text.encode("utf-8"))


def build_hostile_repository(
    root: Path,
    canary_dir: Path,
    *,
    filtered_files: bool = True,
    with_merge_commit: bool = False,
) -> tuple[str, str, str]:
    """Create history with plain Git, then arm it. Returns (repo, baseline, current)."""

    canary_dir.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True)
    _history_git(root, "init", "-q", "-b", "main")
    _write(root, "app.txt", "baseline\n")
    _write(root, ".gitattributes", "*.dat filter=evil\n*.wt filter=wt\n*.txt diff=evil merge=evil\n")
    if filtered_files:
        _write(root, "data.dat", "dat payload\n")
        _write(root, "data.wt", "wt payload\n")
    _history_git(root, "add", "-A")
    _history_git(root, "commit", "-q", "-m", "baseline")
    baseline = _history_git(root, "rev-parse", "HEAD")

    if with_merge_commit:
        _history_git(root, "checkout", "-q", "-b", "feature")
        _write(root, "app.txt", "feature\n")
        _history_git(root, "commit", "-q", "-am", "feature edit")
        _history_git(root, "checkout", "-q", "main")
        _write(root, "notes.txt", "notes\n")
        _history_git(root, "add", "notes.txt")
        _history_git(root, "commit", "-q", "-m", "add notes")
        _history_git(root, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
    else:
        _write(root, "app.txt", "edited by agent\n")
        _history_git(root, "commit", "-q", "-am", "edit app")
        _write(root, "notes.txt", "notes\n")
        _history_git(root, "add", "notes.txt")
        _history_git(root, "commit", "-q", "-m", "add notes")
    current = _history_git(root, "rev-parse", "HEAD")
    _history_git(root, "remote", "add", "origin", "https://github.com/acme/widgets.git")

    support = root.parent / f"{root.name}-hostile"
    bin_dir = support / "evil-bin"
    evil_hooks = support / "evil-hooks"
    for directory in (bin_dir, evil_hooks):
        directory.mkdir(parents=True)
    dot_hooks = root / ".git" / "hooks"
    dot_hooks.mkdir(parents=True, exist_ok=True)
    for name in HOOK_NAMES:
        _script(evil_hooks / name, canary_dir / f"hook-{name}", "exit 0\n")
        _script(dot_hooks / name, canary_dir / f"dothook-{name}", "exit 0\n")

    def tool(name: str, tail: str = "") -> str:
        return _posix(_script(bin_dir / name, canary_dir / name, tail))

    include = support / "worktree-include.cfg"
    include.write_bytes(
        f'[filter "wt"]\n\tsmudge = {tool("filter-wt-smudge", "cat\n")}\n'.encode("utf-8")
    )
    config = {
        "core.hooksPath": _posix(evil_hooks),
        "filter.evil.smudge": tool("filter-smudge", "cat\n"),
        "filter.evil.clean": tool("filter-clean", "cat\n"),
        "filter.evil.process": tool("filter-process", "exit 1\n"),
        "filter.evil.required": "true",
        "includeIf.gitdir:**/worktrees/**.path": _posix(include),
        "core.fsmonitor": tool("fsmonitor", "exit 1\n"),
        "core.sshCommand": tool("ssh-command", "exit 1\n"),
        "core.pager": tool("pager", "cat\n"),
        "core.editor": tool("editor"),
        "sequence.editor": tool("sequence-editor"),
        "credential.helper": tool("credential-helper"),
        "core.askPass": tool("askpass"),
        "diff.external": tool("diff-external"),
        "diff.evil.command": tool("diff-command"),
        "diff.evil.textconv": tool("diff-textconv", 'cat "$1"\n'),
        "merge.evil.driver": tool("merge-driver", "exit 1\n"),
        "gpg.program": tool("gpg-program", "exit 1\n"),
        "commit.gpgSign": "true",
    }
    for key, value in config.items():
        plain_git(root, "config", key, value)
    return str(root), baseline, current


def canaries(canary_dir: Path) -> list[str]:
    return sorted(path.name for path in canary_dir.iterdir()) if canary_dir.exists() else []


def assert_no_canaries(canary_dir: Path) -> None:
    fired = canaries(canary_dir)
    assert not fired, f"hostile repository mechanisms executed: {fired}"


def _worktrees(repo: str) -> list[str]:
    listed = plain_git(Path(repo), "worktree", "list", "--porcelain").stdout
    return [line for line in listed.splitlines() if line.startswith("worktree ")]


# --- positive controls: plain Git really executes these mechanisms --------------------


def test_positive_control_checkout_mechanisms_fire_under_plain_git(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, _, current = build_hostile_repository(tmp_path / "repo", canary_dir)

    # The required process filter fires (and, failing, aborts this checkout).
    plain_git(Path(repo), "worktree", "add", "--detach", str(tmp_path / "wt-a"), current,
              check=False)
    # With the evil filter switched off, the worktree-conditional filter (invisible
    # to discovery against the main repository), the repository-configured
    # post-checkout/post-index-change hooks and core.fsmonitor all fire.
    plain_git(Path(repo), "-c", "filter.evil.process=", "-c", "filter.evil.required=false",
              "worktree", "add", "--detach", str(tmp_path / "wt-b"), current, check=False)
    # Git never falls back from a configured process filter to smudge/clean (not
    # even when process is emptied), so smudge and clean are controlled with the
    # process filter removed from the configuration.
    plain_git(Path(repo), "config", "--unset", "filter.evil.process")
    plain_git(Path(repo), "worktree", "add", "--detach", str(tmp_path / "wt-c"), current,
              check=False)
    (Path(repo) / "data.dat").write_bytes(b"agent edit\n")
    plain_git(Path(repo), "add", "data.dat", check=False)

    fired = set(canaries(canary_dir))
    missing = {"filter-process", "filter-smudge", "filter-clean", "filter-wt-smudge",
               "hook-post-checkout", "hook-post-index-change", "fsmonitor"} - fired
    assert not missing, f"positive control did not fire: {sorted(missing)}; fired={sorted(fired)}"


def test_positive_control_commit_mechanisms_fire_under_plain_git(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, _, _ = build_hostile_repository(tmp_path / "repo", canary_dir, filtered_files=False)
    root = Path(repo)

    # commit.gpgSign=true runs gpg.program (which fails, aborting the commit).
    plain_git(root, "commit", "--allow-empty", "-m", "signed", check=False)
    # Unsigned, the commit completes and fires the remaining commit hooks.
    plain_git(root, "-c", "commit.gpgSign=false", "commit", "--allow-empty", "-m", "unsigned",
              check=False)
    # Hooks in .git/hooks fire as soon as the repository stops redirecting hooksPath.
    plain_git(root, "config", "--unset", "core.hooksPath")
    plain_git(root, "-c", "commit.gpgSign=false", "commit", "--allow-empty", "-m", "again",
              check=False)

    fired = set(canaries(canary_dir))
    missing = {
        "gpg-program", "hook-pre-commit", "hook-prepare-commit-msg", "hook-commit-msg",
        "hook-post-commit", "hook-reference-transaction", "dothook-pre-commit",
        "dothook-prepare-commit-msg", "dothook-post-commit",
    } - fired
    assert not missing, f"positive control did not fire: {sorted(missing)}; fired={sorted(fired)}"


def test_positive_control_inspection_mechanisms_fire_under_plain_git(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, _, _ = build_hostile_repository(tmp_path / "repo", canary_dir, filtered_files=False)
    root = Path(repo)
    (root / "app.txt").write_bytes(b"agent edit\n")
    (root / ".gitattributes").write_bytes(
        b"*.dat filter=evil\n*.wt filter=wt\n*.txt diff=evil merge=evil\n# edited\n"
    )

    plain_git(root, "status", "--porcelain", check=False)      # core.fsmonitor
    plain_git(root, "diff", check=False)                       # diff.external / diff.evil.command
    plain_git(root, "diff", "--no-ext-diff", check=False)      # diff.evil.textconv

    fired = set(canaries(canary_dir))
    missing = {"fsmonitor", "diff-external", "diff-command", "diff-textconv"} - fired
    assert not missing, f"positive control did not fire: {sorted(missing)}; fired={sorted(fired)}"


# --- recovery preview ----------------------------------------------------------------


def test_recovery_preview_on_hostile_repository_executes_nothing(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, baseline, current = build_hostile_repository(tmp_path / "repo", canary_dir)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline, current)
    head_before = plain_git(Path(repo), "rev-parse", "HEAD").stdout.strip()
    branch_before = plain_git(Path(repo), "branch", "--show-current").stdout.strip()
    worktrees_before = _worktrees(repo)

    plan = GitRecoveryEngine(database).plan(change)

    assert_no_canaries(canary_dir)
    assert len(plan.actions) == 1
    assert plan.actions[0].kind == "git.revert_commits"
    assert plan.actions[0].supported is True
    assert plan.conflicts == []
    assert plain_git(Path(repo), "rev-parse", "HEAD").stdout.strip() == head_before
    assert plain_git(Path(repo), "branch", "--show-current").stdout.strip() == branch_before
    assert _worktrees(repo) == worktrees_before


def test_recovery_preview_conflict_on_hostile_repository_executes_nothing(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, baseline, current = build_hostile_repository(
        tmp_path / "repo", canary_dir, with_merge_commit=True,
    )
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline, current)
    worktrees_before = _worktrees(repo)

    plan = GitRecoveryEngine(database).plan(change)

    assert_no_canaries(canary_dir)
    assert len(plan.actions) == 1
    assert plan.actions[0].supported is False
    assert plan.conflicts
    assert _worktrees(repo) == worktrees_before


# --- recovery execute, lifecycle facts, repository slug -------------------------------


def test_recovery_execute_on_hostile_repository_uses_sentinel_identity_and_executes_nothing(
    tmp_path,
) -> None:
    canary_dir = tmp_path / "canary"
    repo, baseline, current = build_hostile_repository(tmp_path / "repo", canary_dir)
    root = Path(repo)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline, current)
    head_before = plain_git(root, "rev-parse", "HEAD").stdout.strip()
    branch_before = plain_git(root, "branch", "--show-current").stdout.strip()
    worktrees_before = _worktrees(repo)
    engine = GitRecoveryEngine(database)

    result = engine.execute(change, engine.plan(change), "approval-token-123")

    assert_no_canaries(canary_dir)
    assert result.status is RecoveryStatus.RECOVERED
    branch = f"change-assurance/recovery/{change.id}"
    tip = plain_git(root, "rev-parse", "--verify", f"refs/heads/{branch}").stdout.strip()
    identity = plain_git(root, "log", "-1", "--format=%an <%ae>|%cn <%ce>", tip).stdout.strip()
    assert identity == ("Sentinel Recovery <recovery@sentinel.invalid>|"
                        "Sentinel Recovery <recovery@sentinel.invalid>")
    assert plain_git(root, "show", f"{tip}:app.txt").stdout == "baseline\n"
    assert plain_git(root, "rev-parse", "HEAD").stdout.strip() == head_before
    assert plain_git(root, "branch", "--show-current").stdout.strip() == branch_before
    assert _worktrees(repo) == worktrees_before

    # Lifecycle branch-head lookup and repository-slug lookup on the same repo.
    assert RuntimeLifecycleFacts._branch_head_sha(repo, branch) == tip
    assert resolve_github_repository_slug(repo) == "acme/widgets"
    assert_no_canaries(canary_dir)


# --- inspection (adapter, checkpoints) ------------------------------------------------


def test_inspection_and_checkpoint_on_hostile_repository_execute_nothing(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, _, _ = build_hostile_repository(tmp_path / "repo", canary_dir, filtered_files=False)
    (Path(repo) / "app.txt").write_bytes(b"inspected edit\n")

    summary = GitRepositoryInspector().inspect(repo, 100_000)
    checkpoint = GitStateTracker().capture(uuid4(), "hostile", repo, 1, 100_000)

    assert_no_canaries(canary_dir)
    changed = {item.path: item.status for item in summary.files}
    assert changed == {"app.txt": ChangedPathStatus.MODIFIED}
    assert "+inspected edit" in summary.patch
    assert checkpoint.summary.files == summary.files


def test_inspection_refuses_content_filtered_hostile_repository(tmp_path) -> None:
    canary_dir = tmp_path / "canary"
    repo, _, _ = build_hostile_repository(tmp_path / "repo", canary_dir)
    (Path(repo) / "app.txt").write_bytes(b"inspected edit\n")

    with pytest.raises(GitCommandError, match="content filters are unsupported"):
        GitRepositoryInspector().inspect(repo, 100_000)

    assert_no_canaries(canary_dir)


@pytest.fixture(autouse=True)
def _no_inherited_git_overrides(monkeypatch) -> None:
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT"):
        monkeypatch.delenv(key, raising=False)
