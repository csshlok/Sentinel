"""Config discovery is shared within one logical Git operation and never beyond it.

``SafeGitSession`` (``backend.app.git.safe_exec``) lets one ``inspect()`` reuse a
single configuration discovery for all of its Git commands. These tests count
real discovery processes through the ``safe_exec.capture`` seam and prove the
security boundaries of that reuse: a new operation rediscovers (so config the
agent changed between operations is neutralized), and every distinct ``-C``
target -- another repository or a linked worktree -- is discovered on its own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.git import safe_exec
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.safe_exec import SafeGitSession, run_git
from backend.tests.git.test_git_adapter import git, repo  # noqa: F401 - fixture


def _is_discovery(argv: list[str]) -> bool:
    return "--show-scope" in argv and "--get-regexp" in argv


@pytest.fixture
def recorded(monkeypatch) -> list[list[str]]:
    """Every argv the harness starts, in order (real processes still run)."""

    calls: list[list[str]] = []
    original = safe_exec.capture

    def recording(argv, **kwargs):
        calls.append([str(item) for item in argv])
        return original(argv, **kwargs)

    monkeypatch.setattr(safe_exec, "capture", recording)
    return calls


def _discoveries(calls: list[list[str]]) -> int:
    return sum(1 for argv in calls if _is_discovery(argv))


def _init(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    git(path, "config", "user.name", "Tester")
    git(path, "config", "user.email", "tester@example.com")
    git(path, "config", "commit.gpgsign", "false")
    (path / "file.txt").write_text("content\n", encoding="utf-8")
    git(path, "add", "file.txt")
    git(path, "commit", "-m", "initial")
    return path


def test_one_inspect_performs_a_single_config_discovery(repo, recorded) -> None:  # noqa: F811
    (repo / "modify.py").write_text("changed\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    summary = GitRepositoryInspector().inspect(str(repo), 10_000)

    assert {item.path for item in summary.files} >= {"modify.py", "untracked.txt"}
    assert _discoveries(recorded) == 1
    commands = [argv for argv in recorded if not _is_discovery(argv)]
    # validate x2, status x2, numstat x2, patch x2, plus the filter-attribute
    # checks: all served by that one discovery.
    assert len(commands) >= 10


def test_each_inspection_rediscovers_configuration(repo, recorded) -> None:  # noqa: F811
    inspector = GitRepositoryInspector()
    inspector.inspect(str(repo), 1000)
    first = list(recorded)
    assert _discoveries(first) == 1
    assert not any("filter.late.process=" in argv for argv in first)

    # The agent changes configuration between two operations.
    git(repo, "config", "filter.late.process", "echo late")
    recorded.clear()
    inspector.inspect(str(repo), 1000)

    assert _discoveries(recorded) == 1
    commands = [argv for argv in recorded if not _is_discovery(argv)]
    assert commands and all("filter.late.process=" in argv for argv in commands)


def test_validate_repository_is_its_own_operation(repo, recorded) -> None:  # noqa: F811
    inspector = GitRepositoryInspector()
    inspector.validate_repository(str(repo))
    inspector.validate_repository(str(repo))
    assert _discoveries(recorded) == 2


def test_session_discovers_once_per_target_and_never_across_repositories(
    tmp_path, recorded
) -> None:
    first = _init(tmp_path / "first")
    second = _init(tmp_path / "second")
    git(second, "config", "filter.second.smudge", "echo second")

    session = SafeGitSession()
    for _ in range(3):
        assert session.run(first, ["rev-parse", "HEAD"]).returncode == 0
    assert session.discoveries == 1
    assert session.run(second, ["rev-parse", "HEAD"]).returncode == 0
    assert session.run(second, ["status", "--porcelain"]).returncode == 0

    assert session.discoveries == 2
    assert _discoveries(recorded) == 2
    assert "filter.second.smudge=" not in session.git(first).prefix
    assert "filter.second.smudge=" in session.git(second).prefix
    assert _discoveries(recorded) == 2  # cached lookups start nothing


def test_linked_worktree_is_discovered_inside_the_worktree(tmp_path, recorded) -> None:
    main = _init(tmp_path / "main")
    include = tmp_path / "worktree-only.gitconfig"
    include.write_text('[filter "wtonly"]\n\tsmudge = echo wtonly\n', encoding="utf-8")
    git(main, "config", "includeIf.gitdir:**/worktrees/**.path", include.as_posix())
    worktree = tmp_path / "linked"
    git(main, "worktree", "add", "--no-checkout", "--detach", str(worktree), "HEAD")

    session = SafeGitSession(extra_roots=(main,))
    main_git = session.git(main)
    linked_git = session.git(worktree)

    assert session.discoveries == 2
    assert _discoveries(recorded) == 2
    assert "filter.wtonly.smudge=" not in main_git.prefix
    assert "filter.wtonly.smudge=" in linked_git.prefix


def test_run_git_one_off_calls_stay_fresh(tmp_path, recorded) -> None:
    root = _init(tmp_path / "fresh")
    run_git(root, ["rev-parse", "HEAD"])
    run_git(root, ["rev-parse", "HEAD"])
    assert _discoveries(recorded) == 2


def test_hooks_placeholder_is_reverified_on_every_session_run(tmp_path, monkeypatch) -> None:
    root = _init(tmp_path / "hooks")
    session = SafeGitSession()
    session.run(root, ["rev-parse", "HEAD"])
    verified: list[Path] = []
    original = safe_exec.hooks_placeholder

    def counting() -> Path:
        verified.append(original())
        return verified[-1]

    monkeypatch.setattr(safe_exec, "hooks_placeholder", counting)
    session.run(root, ["rev-parse", "HEAD"])
    session.run(root, ["status", "--porcelain"])
    assert len(verified) == 2
