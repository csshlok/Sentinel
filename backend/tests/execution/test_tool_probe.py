"""Tool version probes run in a fresh Sentinel-owned directory, never the repository."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from backend.app.execution import tool_probe
from backend.app.execution._process import CapturedProcess
from backend.app.execution.tool_probe import (
    PROBE_OUTPUT_LIMIT,
    PROBE_TIMEOUT_SECONDS,
    run_tool_probe,
)

CWD_PROBE = [sys.executable, "-c", "import os; print(os.getcwd())"]


def _inside(path: Path, root: Path) -> bool:
    path, root = path.resolve(), root.resolve()
    return path == root or root in path.parents


def test_real_probe_runs_in_a_fresh_directory_outside_the_repository(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    # Repository-local tool configuration that must never be in the probe's cwd chain.
    (repo / ".npmrc").write_text("script-shell=evil\n", encoding="utf-8")

    code, output = run_tool_probe(CWD_PROBE, exclude_root=repo)

    assert code == 0
    reported = Path(output.strip())
    assert reported.name.startswith("sentinel-probe-")
    assert not _inside(reported, repo)
    assert not reported.exists()  # removed after the probe


def test_each_probe_gets_its_own_directory(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first = run_tool_probe(CWD_PROBE, exclude_root=repo)[1].strip()
    second = run_tool_probe(CWD_PROBE, exclude_root=repo)[1].strip()
    assert first and second and first != second


def _fake_capture(calls: list[dict], result: CapturedProcess):
    def fake(argv, **kwargs):
        calls.append({"argv": list(argv), **kwargs})
        assert Path(kwargs["cwd"]).is_dir()  # the directory exists while the probe runs
        return result

    return fake


def _result(**overrides) -> CapturedProcess:
    values = dict(returncode=0, stdout=b"v1.2.3\n", stderr=b"", truncated=False,
                  timed_out=False, incomplete=False, stdout_digest="d")
    values.update(overrides)
    return CapturedProcess(**values)


def test_probe_environment_and_bounds(tmp_path, monkeypatch) -> None:
    repo = (tmp_path / "repo").resolve()
    (repo / "bin").mkdir(parents=True)
    outside = (tmp_path / "tools").resolve()
    outside.mkdir()
    monkeypatch.setenv("PATH", os.pathsep.join([str(repo / "bin"), "relative-dir", str(outside)]))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    calls: list[dict] = []
    monkeypatch.setattr(tool_probe, "capture", _fake_capture(calls, _result()))

    assert run_tool_probe(["tool", "--version"], exclude_root=repo) == (0, "v1.2.3\n")

    (call,) = calls
    entries = [Path(entry) for entry in call["env"]["PATH"].split(os.pathsep) if entry]
    assert entries == [outside]
    assert all(entry.is_absolute() and not _inside(entry, repo) for entry in entries)
    assert call["env"]["HOME"] == str(tmp_path / "home")
    assert call["env"]["USERPROFILE"] == str(tmp_path / "profile")
    assert call["timeout"] == PROBE_TIMEOUT_SECONDS == 10
    assert call["limit"] == PROBE_OUTPUT_LIMIT == 4096
    assert not _inside(Path(call["cwd"]), repo)
    assert Path(call["cwd"]).name.startswith("sentinel-probe-")
    assert not Path(call["cwd"]).exists()


def test_home_is_not_invented_when_absent(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    calls: list[dict] = []
    monkeypatch.setattr(tool_probe, "capture", _fake_capture(calls, _result()))
    run_tool_probe(["tool"], exclude_root=tmp_path)
    assert "HOME" not in calls[0]["env"] and "USERPROFILE" not in calls[0]["env"]


@pytest.mark.parametrize("flag", ["timed_out", "incomplete"])
def test_timed_out_or_incomplete_probe_reports_nothing(tmp_path, monkeypatch, flag) -> None:
    monkeypatch.setattr(tool_probe, "capture", _fake_capture([], _result(**{flag: True})))
    assert run_tool_probe(["tool"], exclude_root=tmp_path) == (None, "")


def test_undecodable_output_is_replaced(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tool_probe, "capture",
                        _fake_capture([], _result(returncode=3, stdout=b"v\xff\n")))
    assert run_tool_probe(["tool"], exclude_root=tmp_path) == (3, "v�\n")
