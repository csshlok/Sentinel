"""Unit and real-Git tests for the hardened Git harness (``backend.app.git.safe_exec``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from backend.app.execution._process import CapturedProcess
from backend.app.git import safe_exec
from backend.app.git.errors import GitCommandError, GitExecutableNotFoundError
from backend.app.git.safe_exec import (
    CARRIED_SYSTEM_KEYS,
    RECOVERY_IDENTITY,
    STATIC_CONFIG_OVERRIDES,
    GitIdentity,
    empty_hooks_directory,
    run_git,
)


def _plain(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        capture_output=True, text=True, shell=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    _plain(root, "init", "-q", "-b", "main")
    _plain(root, "config", "user.name", "Test")
    _plain(root, "config", "user.email", "test@example.com")
    (root / "file.txt").write_bytes(b"base\n")
    _plain(root, "add", "file.txt")
    _plain(root, "commit", "-q", "-m", "baseline")
    return root


def _ok(stdout: bytes = b"") -> CapturedProcess:
    return CapturedProcess(0, stdout, b"", False, False, False, "digest")


def _recording_fake(calls: list[tuple[list[str], dict]], config_stdout: bytes = b""):
    def fake(argv, **kwargs):
        calls.append((list(argv), kwargs))
        subcommand = argv[argv.index("-C") + 2]
        return _ok(config_stdout if subcommand == "config" else b"")
    return fake


def _config_values(argv: list[str]) -> list[str]:
    return [argv[index + 1] for index, token in enumerate(argv) if token == "-c"]


@pytest.fixture(autouse=True)
def _no_inherited_git_overrides(monkeypatch) -> None:
    for key in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_WORK_TREE"):
        monkeypatch.delenv(key, raising=False)


# --- argv / environment contract ------------------------------------------------------


def test_argv_environment_and_cwd_are_hardened(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(repo / "bin"), os.environ["PATH"]]))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "other"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("backend.app.git.safe_exec.capture", _recording_fake(calls))

    run_git(repo, ["status", "--porcelain"])

    assert [argv[argv.index("-C") + 2] for argv, _ in calls] == ["config", "status"]
    argv, kwargs = calls[-1]
    assert argv[1:3] == ["--no-pager", "--no-optional-locks"]
    assert argv.count("-C") == 1
    position = argv.index("-C")
    assert argv[position + 1] == os.path.abspath(repo)
    assert argv[position + 2:] == ["status", "--porcelain"]
    values = _config_values(argv)
    hooks = [value for value in values if value.startswith("core.hooksPath=")]
    assert len(hooks) == 1
    hooks_dir = Path(hooks[0].split("=", 1)[1])
    assert hooks_dir.is_dir() and not any(hooks_dir.iterdir())
    for override in STATIC_CONFIG_OVERRIDES:
        assert override in values
    assert Path(argv[0]).is_absolute() and Path(argv[0]).suffix.lower() not in {".cmd", ".bat"}

    env = kwargs["env"]
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    for leaked in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT"):
        assert leaked not in env
    resolved_repo = repo.resolve()
    for entry in env["PATH"].split(os.pathsep):
        assert Path(entry).is_absolute()
        assert resolved_repo != Path(entry) and resolved_repo not in Path(entry).parents
    cwd = Path(kwargs["cwd"]).resolve()
    assert cwd != resolved_repo and resolved_repo not in cwd.parents
    assert cwd == hooks_dir.parent.resolve()


def test_discovery_reads_system_scope_but_commands_ignore_it(tmp_path, monkeypatch) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("backend.app.git.safe_exec.capture", _recording_fake(calls))

    run_git(tmp_path, ["rev-parse", "HEAD"])

    discovery, command = calls
    assert "GIT_CONFIG_NOSYSTEM" not in discovery[1]["env"]
    assert discovery[0][discovery[0].index("-C") + 2:][:4] == [
        "config", "--null", "--show-scope", "--get-regexp",
    ]
    assert command[1]["env"]["GIT_CONFIG_NOSYSTEM"] == "1"


def test_real_repository_drivers_are_discovered_and_overridden(tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path / "repo")
    for key, value in {
        "filter.x.clean": "clean-cmd", "filter.x.smudge": "smudge-cmd",
        "filter.x.process": "process-cmd", "filter.x.required": "true",
        "diff.y.command": "diff-cmd", "diff.y.textconv": "textconv-cmd",
        "merge.z.driver": "merge-cmd",
    }.items():
        _plain(repo, "config", key, value)
    seen: list[list[str]] = []
    real_capture = safe_exec.capture

    def spy(argv, **kwargs):
        seen.append(list(argv))
        return real_capture(argv, **kwargs)

    monkeypatch.setattr("backend.app.git.safe_exec.capture", spy)
    result = run_git(repo, ["rev-parse", "HEAD"])

    assert result.returncode == 0
    values = _config_values(seen[-1])
    for expected in ("filter.x.clean=", "filter.x.smudge=", "filter.x.process=",
                     "filter.x.required=false", "diff.y.command=", "diff.y.textconv=",
                     "merge.z.driver="):
        assert expected in values


# --- system carry-forward ------------------------------------------------------------


@pytest.mark.parametrize(("records", "expected", "absent"), [
    (b"system\0core.autocrlf\ntrue\0", ["core.autocrlf=true"], []),
    (b"system\0core.autocrlf\ntrue\0local\0core.autocrlf\ninput\0", [], ["core.autocrlf"]),
    (b"system\0core.autocrlf\ntrue\0global\0core.autocrlf\nfalse\0", [], ["core.autocrlf"]),
    (b"system\0core.autocrlf\nmaybe\0", [], ["core.autocrlf"]),
    (b"system\0core.whitespace\ntrailing-space\0", [], ["core.whitespace"]),
    (b"system\0core.symlinks\nFalse\0system\0core.fscache\ntrue\0",
     ["core.symlinks=false", "core.fscache=true"], []),
])
def test_system_content_keys_are_carried_only_when_safe(
    tmp_path, monkeypatch, records, expected, absent,
) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("backend.app.git.safe_exec.capture", _recording_fake(calls, records))

    run_git(tmp_path, ["status"])

    values = _config_values(calls[-1][0])
    for item in expected:
        assert item in values
    for key in absent:
        assert not any(value.lower().startswith(key + "=") for value in values)


def test_carried_keys_are_content_semantics_only() -> None:
    assert set(CARRIED_SYSTEM_KEYS) == {
        "core.autocrlf", "core.eol", "core.safecrlf", "core.symlinks",
        "core.longpaths", "core.fscache",
    }


# --- fail closed ---------------------------------------------------------------------


@pytest.mark.parametrize("records", [
    b"local\0filter.a=b.clean\nx\0",
    b"local\0merge.a=b.driver\nx\0",
    b"global\0diff.a=b.textconv\nx\0",
])
def test_driver_name_that_cannot_be_overridden_fails_closed(tmp_path, monkeypatch, records) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("backend.app.git.safe_exec.capture", _recording_fake(calls, records))
    with pytest.raises(GitCommandError, match="unsupported driver name"):
        run_git(tmp_path, ["status"])
    assert len(calls) == 1  # the command itself never ran


@pytest.mark.parametrize("stdout", [b"local\0", b"local\0core.autocrlf\ntrue", b"\0x\0", b"\xff\0a\0"])
def test_garbled_discovery_output_fails_closed(tmp_path, monkeypatch, stdout) -> None:
    monkeypatch.setattr("backend.app.git.safe_exec.capture", _recording_fake([], stdout))
    with pytest.raises(GitCommandError):
        run_git(tmp_path, ["status"])


@pytest.mark.parametrize("failure", ["timed_out", "incomplete", "truncated", "exit"])
def test_discovery_failures_fail_closed(tmp_path, monkeypatch, failure) -> None:
    from dataclasses import replace

    def fake(argv, **_):
        if failure == "exit":
            return replace(_ok(), returncode=128)
        return replace(_ok(), **{failure: True})

    monkeypatch.setattr("backend.app.git.safe_exec.capture", fake)
    with pytest.raises(GitCommandError):
        run_git(tmp_path, ["status"])


def test_missing_git_is_a_stable_424(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("backend.app.git.safe_exec.shutil.which", lambda _: None)
    with pytest.raises(GitExecutableNotFoundError) as info:
        run_git(tmp_path, ["status"])
    assert info.value.code == "GIT_EXECUTABLE_NOT_FOUND"
    assert info.value.status_code == 424


def test_repository_and_wrapper_executables_are_rejected(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    external = tmp_path / "external"
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(root), str(external)]))
    for found in (str(root / "git.exe"), str(external / "git.cmd"), str(external / "git.bat")):
        monkeypatch.setattr("backend.app.git.safe_exec.shutil.which", lambda _, found=found: found)
        with pytest.raises(GitExecutableNotFoundError):
            safe_exec.resolve_trusted_git(root)


def test_start_failure_never_leaks_os_error_text(tmp_path, monkeypatch) -> None:
    def fake(argv, **_):
        raise OSError("secret-canary")

    monkeypatch.setattr("backend.app.git.safe_exec.capture", fake)
    with pytest.raises(GitCommandError) as info:
        run_git(tmp_path, ["status"])
    assert "secret-canary" not in str(info.value)
    assert "secret-canary" not in repr(info.value.details)


def test_file_not_found_maps_to_missing_git(tmp_path, monkeypatch) -> None:
    def fake(argv, **_):
        raise FileNotFoundError("gone")

    monkeypatch.setattr("backend.app.git.safe_exec.capture", fake)
    with pytest.raises(GitExecutableNotFoundError):
        run_git(tmp_path, ["status"])


# --- identity ------------------------------------------------------------------------


def test_recovery_identity_is_the_sentinel_identity() -> None:
    assert RECOVERY_IDENTITY == GitIdentity(name="Sentinel Recovery", email="recovery@sentinel.invalid")
