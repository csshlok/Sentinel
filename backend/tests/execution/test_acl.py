"""Owner-only restriction helper (execution/acl.py)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from backend.app.execution import acl
from backend.app.execution.acl import restrict_to_current_user

windows_only = pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")


class _Recorder:
    def __init__(self, returncode: int = 0, error: BaseException | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.returncode = returncode
        self.error = error

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(argv, self.returncode, b"", b"")


FAKE_ICACLS = Path(r"C:\Windows\System32\icacls.exe")


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    fake = _Recorder()
    monkeypatch.setattr("backend.app.execution.acl.subprocess.run", fake)
    monkeypatch.setattr("backend.app.execution.acl.icacls_executable", lambda: FAKE_ICACLS)
    monkeypatch.setenv("USERNAME", "test-user")
    return fake


@windows_only
def test_file_mode_runs_one_icacls_with_the_current_user_only(tmp_path, recorder) -> None:
    target = tmp_path / "api_token"
    target.write_text("x", encoding="utf-8")

    assert restrict_to_current_user(target) is True

    assert len(recorder.calls) == 1
    argv, kwargs = recorder.calls[0]
    assert argv == [str(FAKE_ICACLS), str(target), "/inheritance:r", "/grant:r", "test-user:F"]
    assert kwargs["shell"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == acl.ICACLS_TIMEOUT_SECONDS
    assert kwargs["cwd"] == FAKE_ICACLS.parent


@windows_only
def test_directory_mode_grants_user_and_system_with_inheritance(tmp_path, recorder) -> None:
    assert restrict_to_current_user(tmp_path, directory=True) is True

    assert [argv for argv, _ in recorder.calls] == [[
        str(FAKE_ICACLS), str(tmp_path), "/inheritance:r",
        "/grant:r", "test-user:(OI)(CI)F",
        "/grant:r", "*S-1-5-18:(OI)(CI)F",
    ]]


@windows_only
def test_a_non_zero_exit_is_reported_as_not_applied(tmp_path, recorder) -> None:
    recorder.returncode = 5
    assert restrict_to_current_user(tmp_path, directory=True) is False


@windows_only
def test_a_missing_username_is_not_applied_and_runs_nothing(tmp_path, recorder, monkeypatch) -> None:
    monkeypatch.delenv("USERNAME", raising=False)
    assert restrict_to_current_user(tmp_path) is False
    assert recorder.calls == []


@windows_only
def test_a_missing_system_icacls_is_not_applied_and_runs_nothing(
    tmp_path, recorder, monkeypatch
) -> None:
    monkeypatch.setattr("backend.app.execution.acl.icacls_executable", lambda: None)
    assert restrict_to_current_user(tmp_path) is False
    assert recorder.calls == []


@windows_only
def test_a_relative_target_is_passed_as_an_absolute_path(tmp_path, recorder, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "token").write_text("x", encoding="utf-8")

    assert restrict_to_current_user(Path("token")) is True

    argv, _ = recorder.calls[0]
    assert argv[1] == str(tmp_path / "token")


@windows_only
def test_icacls_resolves_to_the_system_directory() -> None:
    icacls = acl.icacls_executable()
    system_directory = acl.windows_system_directory()
    assert icacls is not None and system_directory is not None
    assert icacls.is_absolute()
    assert icacls.parent == system_directory
    assert icacls.name.lower() == "icacls.exe"


@windows_only
@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("icacls not found"),
        PermissionError("denied"),
        subprocess.SubprocessError("broken"),
        subprocess.TimeoutExpired(["icacls"], 10),
    ],
)
def test_process_failures_never_raise(tmp_path, recorder, error) -> None:
    recorder.error = error
    assert restrict_to_current_user(tmp_path, directory=True) is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_posix_modes_are_owner_only(tmp_path) -> None:
    target = tmp_path / "token"
    target.write_text("x", encoding="utf-8")
    directory = tmp_path / "store"
    directory.mkdir()

    assert restrict_to_current_user(target) is True
    assert restrict_to_current_user(directory, directory=True) is True

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def _ace_lines(path) -> list[str]:
    icacls = acl.icacls_executable()
    assert icacls is not None, "icacls is part of Windows and must be available"
    completed = subprocess.run(
        [str(icacls), str(path)], capture_output=True, shell=False, timeout=30, check=True,
        cwd=icacls.parent,
    )
    text = completed.stdout.decode(errors="replace")
    block = text.strip().split("\n\n", 1)[0].replace("\r", "")
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    # The first line starts with the path itself.
    lines[0] = lines[0][len(str(path)):].strip()
    return lines


@windows_only
def test_real_icacls_leaves_only_the_user_and_system_without_inheritance(tmp_path) -> None:
    if acl.icacls_executable() is None:
        pytest.fail("icacls is part of Windows and must be available")
    username = os.environ.get("USERNAME")
    assert username, "USERNAME must be set on Windows"
    directory = tmp_path / "Sentinel"
    directory.mkdir()

    assert _ace_lines(directory) and any("(I)" in line for line in _ace_lines(directory))
    assert restrict_to_current_user(directory, directory=True) is True

    lines = _ace_lines(directory)
    assert not any("(I)" in line for line in lines), lines
    assert len(lines) == 2, lines
    assert sum(username.casefold() in line.casefold() for line in lines) == 1, lines

    child = directory / "api_token"
    child.write_text("x", encoding="utf-8")
    child_lines = _ace_lines(child)
    assert len(child_lines) == 2, child_lines
    assert all("(I)" in line for line in child_lines), child_lines


def _plant(directory: Path, name: str) -> Path:
    """Copy a harmless system binary to ``directory/name`` (a planted look-alike)."""

    system_directory = acl.windows_system_directory()
    assert system_directory is not None
    planted = directory / name
    shutil.copyfile(system_directory / "hostname.exe", planted)
    return planted


@windows_only
def test_an_icacls_planted_in_the_current_directory_never_runs(tmp_path, monkeypatch) -> None:
    """CR-01 regression: a repository-planted icacls.exe in cwd is not executed."""

    cwd = tmp_path / "repo"
    cwd.mkdir()
    planted = _plant(cwd, "icacls.exe")
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    # Positive control: a bare-name lookup from this cwd finds the planted binary.
    found = shutil.which("icacls")
    assert found is not None and Path(found).resolve() == planted.resolve()

    real_run = subprocess.run
    calls: list[tuple[list[str], dict]] = []

    def spy(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return real_run(argv, **kwargs)

    monkeypatch.setattr("backend.app.execution.acl.subprocess.run", spy)
    target = tmp_path / "store"
    target.mkdir()

    assert restrict_to_current_user(target, directory=True) is True

    assert len(calls) == 1
    argv, kwargs = calls[0]
    executable = Path(argv[0])
    assert executable.is_absolute()
    assert executable.resolve() != planted.resolve()
    assert executable.parent == acl.windows_system_directory()
    assert Path(kwargs["cwd"]) == acl.windows_system_directory()
    # The real icacls ran: inherited ACEs are gone (the planted hostname copy
    # would have exited non-zero and changed nothing).
    monkeypatch.setattr("backend.app.execution.acl.subprocess.run", real_run)
    assert not any("(I)" in line for line in _ace_lines(target))
