"""Tool snapshot (hash-verified, tamper fails closed) and the per-run staged home."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from backend.app.core.errors import AppError
from backend.app.execution.agent_staging import (
    ensure_tool_snapshot,
    rebuild_staged_home,
    sha256_file,
)
from backend.app.execution.process_supervisor import IS_WINDOWS

windows_only = pytest.mark.skipif(not IS_WINDOWS, reason="junctions are Windows-only")


def _junction(target: Path, link: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def tool(tmp_path: Path) -> Path:
    source = tmp_path / "host" / "fake-agent.exe"
    source.parent.mkdir()
    source.write_bytes(b"MZ" + os.urandom(4096))
    return source


def test_snapshot_copies_and_hashes_like_the_source(tmp_path, tool):
    tools = tmp_path / "ac" / "tools"
    tools.parent.mkdir()
    snapshot = ensure_tool_snapshot(tool, tools, trusted_digest=None)
    assert snapshot.path == tools / tool.name
    assert snapshot.sha256 == hashlib.sha256(tool.read_bytes()).hexdigest() == sha256_file(tool)
    assert snapshot.path.read_bytes() == tool.read_bytes()
    assert [p.name for p in tools.iterdir()] == [tool.name]  # no partial file left
    again = ensure_tool_snapshot(tool, tools, trusted_digest=snapshot.sha256)
    assert again == snapshot


def test_tampered_snapshot_fails_closed(tmp_path, tool):
    tools = tmp_path / "ac" / "tools"
    tools.parent.mkdir()
    snapshot = ensure_tool_snapshot(tool, tools, trusted_digest=None)
    snapshot.path.write_bytes(b"MZ evil replacement")
    with pytest.raises(AppError) as caught:
        ensure_tool_snapshot(tool, tools, trusted_digest=None)
    assert caught.value.code == "AGENT_TOOL_SNAPSHOT_TAMPERED"
    assert caught.value.status_code == 409


def test_source_that_differs_from_the_trusted_digest_fails(tmp_path, tool):
    tools = tmp_path / "ac" / "tools"
    tools.parent.mkdir()
    with pytest.raises(AppError) as caught:
        ensure_tool_snapshot(tool, tools, trusted_digest="0" * 64)
    assert caught.value.code == "AGENT_TOOL_SNAPSHOT_FAILED"
    assert not (tools / tool.name).exists()


def test_missing_source_fails(tmp_path):
    with pytest.raises(AppError) as caught:
        ensure_tool_snapshot(tmp_path / "absent.exe", tmp_path / "tools", trusted_digest=None)
    assert caught.value.code == "AGENT_TOOL_SNAPSHOT_FAILED"


@windows_only
def test_reparse_tools_dir_fails(tmp_path, tool):
    outside = tmp_path / "outside"
    outside.mkdir()
    ac = tmp_path / "ac"
    ac.mkdir()
    _junction(outside, ac / "tools")
    with pytest.raises(AppError) as caught:
        ensure_tool_snapshot(tool, ac / "tools", trusted_digest=None)
    assert caught.value.code == "AGENT_TOOL_SNAPSHOT_FAILED"
    assert list(outside.iterdir()) == []


@windows_only
def test_reparse_snapshot_fails(tmp_path, tool):
    tools = tmp_path / "ac" / "tools"
    tools.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _junction(elsewhere, tools / tool.name)
    with pytest.raises(AppError) as caught:
        ensure_tool_snapshot(tool, tools, trusted_digest=None)
    assert caught.value.code == "AGENT_TOOL_SNAPSHOT_FAILED"


def test_staged_home_is_rebuilt_without_planted_hooks(tmp_path):
    home = tmp_path / "ac" / "home"
    (home / ".claude").mkdir(parents=True)
    planted = home / ".claude" / "settings.json"
    planted.write_text('{"hooks": {"PreToolUse": "evil"}}', encoding="utf-8")
    (home / ".claude" / ".credentials.json").write_text("{}", encoding="utf-8")
    staged = rebuild_staged_home(home)
    assert not planted.exists()
    assert not (home / ".claude" / ".credentials.json").exists()
    for directory in (staged.claude_dir, staged.roaming, staged.local):
        assert directory.is_dir() and list(directory.iterdir()) == []
    assert staged.claude_dir == home / ".claude"
    assert staged.roaming == home / "AppData" / "Roaming"
    assert staged.local == home / "AppData" / "Local"


def test_staged_home_created_when_absent(tmp_path):
    (tmp_path / "ac").mkdir()
    staged = rebuild_staged_home(tmp_path / "ac" / "home")
    assert staged.root.is_dir() and staged.claude_dir.is_dir()


@windows_only
def test_junction_home_is_removed_as_a_link_only(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "keep.txt"
    canary.write_text("canary", encoding="utf-8")
    ac = tmp_path / "ac"
    ac.mkdir()
    _junction(outside, ac / "home")
    staged = rebuild_staged_home(ac / "home")
    assert canary.read_text(encoding="utf-8") == "canary"
    assert not (outside / ".claude").exists()
    info = os.lstat(staged.root)
    assert not (getattr(info, "st_file_attributes", 0) & 0x400)  # a real directory now


def _dir_not_empty() -> OSError:
    error = OSError(41, "The directory is not empty")
    error.winerror = 145
    return error


def test_rebuild_retries_a_home_that_is_briefly_not_empty(tmp_path, monkeypatch) -> None:
    """Live test 2026-10-08: a synced home can still hold files pending delete."""

    from backend.app.execution import appcontainer

    home = tmp_path / "home"
    (home / ".claude" / "skills").mkdir(parents=True)
    (home / ".claude" / "skills" / "SKILL.md").write_text("synced", encoding="utf-8")
    real_remove = appcontainer.remove_tree_no_follow
    calls = {"count": 0}

    def flaky(path):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _dir_not_empty()
        return real_remove(path)

    monkeypatch.setattr(appcontainer, "remove_tree_no_follow", flaky)
    monkeypatch.setattr(appcontainer.time, "sleep", lambda seconds: None)
    staged = rebuild_staged_home(home)
    assert calls["count"] == 2
    assert sorted(path.name for path in staged.root.iterdir()) == [".claude", "AppData"]


def test_rebuild_does_not_retry_a_non_transient_error(tmp_path, monkeypatch) -> None:
    from backend.app.execution import appcontainer

    home = tmp_path / "home"
    home.mkdir()
    calls = {"count": 0}

    def broken(path):
        calls["count"] += 1
        raise OSError(2, "gone wrong")

    monkeypatch.setattr(appcontainer, "remove_tree_no_follow", broken)
    with pytest.raises(AppError) as raised:
        rebuild_staged_home(home)
    assert raised.value.code == "AGENT_STAGED_HOME_FAILED"
    assert calls["count"] == 1
