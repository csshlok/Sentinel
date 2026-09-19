from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.app.contracts.models import VerificationRequest, VerificationStatus
from backend.app.contracts.ports import VerificationPort
from backend.app.core.errors import AppError
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.runner import BoundedVerificationRunner, _resolve


def run(tmp_path: Path, code: str, limit: int = 1000, timeout: int = 3):
    return BoundedVerificationRunner().run(str(tmp_path), VerificationRequest(
        executable="python", args=["-c", code], timeout_seconds=timeout,
    ), limit)


def test_contract_success_and_canonical_cwd(tmp_path):
    assert isinstance(BoundedVerificationRunner(), VerificationPort)
    result = run(tmp_path, "import os; print(os.getcwd())")
    assert result.status == VerificationStatus.PASSED
    assert result.exit_code == 0
    assert result.stdout.strip() == str(tmp_path.resolve())
    assert result.completed_at >= result.started_at
    assert type(result).model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize(("code", "status", "exit_code"), [
    ("raise SystemExit(7)", VerificationStatus.FAILED, 7),
    ("import time; time.sleep(10)", VerificationStatus.TIMED_OUT, None),
])
def test_failure_and_timeout(tmp_path, code, status, exit_code):
    start = time.monotonic()
    result = run(tmp_path, code, timeout=1)
    assert result.status == status
    assert result.exit_code == exit_code
    assert time.monotonic() - start < 3


def test_missing_cwd_is_safe_error(tmp_path):
    result = run(tmp_path / "missing-private-path", "print('never')")
    assert result.status == VerificationStatus.ERROR
    assert result.exit_code is None
    assert "private" not in result.model_dump_json()


@pytest.mark.parametrize("limit", [0, 1, 101, 200_000])
def test_simultaneous_large_output_is_bounded(tmp_path, limit):
    result = run(tmp_path,
        "import sys\nfor _ in range(100):\n"
        " sys.stdout.buffer.write(b'x' * 10000)\n"
        " sys.stderr.buffer.write(b'y' * 10000)\n", limit=limit)
    assert result.status == VerificationStatus.PASSED
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= limit
    assert result.output_truncated


def test_exact_limit_and_invalid_utf8(tmp_path):
    assert not run(tmp_path, "import sys; sys.stdout.buffer.write(b'x' * 100)", 100).output_truncated
    result = run(tmp_path, "import sys; sys.stdout.buffer.write(bytes([255, 195, 169]) * 100)", 101)
    assert result.output_truncated
    assert len(result.stdout.encode()) <= 101


def test_parent_credentials_and_injection_keys_are_not_inherited(tmp_path, monkeypatch):
    for key in ("KB_SECRET_CANARY", "GITHUB_TOKEN", "PYTHONPATH", "NODE_OPTIONS", "GIT_DIR"):
        monkeypatch.setenv(key, "synthetic-secret-canary")
    result = run(tmp_path,
        "import os; print(any(k in os.environ for k in "
        "['KB_SECRET_CANARY','GITHUB_TOKEN','PYTHONPATH','NODE_OPTIONS','GIT_DIR']))")
    assert result.status == VerificationStatus.PASSED
    assert result.stdout.strip() == "False"
    assert "synthetic-secret-canary" not in result.model_dump_json()


def test_environment_allowlist_is_case_insensitive():
    env = minimal_environment({"Path": "somewhere", "SystemRoot": "windows", "secret": "canary"})
    assert env["PATH"] == "somewhere"
    assert env["SYSTEMROOT"] == "windows"
    assert "canary" not in str(env)


@pytest.mark.parametrize("executable", ["powershell", "cmd", "./python", "C:\\python.exe"])
def test_disallowed_executable_never_starts(tmp_path, executable):
    with pytest.raises(AppError, match="not permitted"):
        BoundedVerificationRunner().run(str(tmp_path), VerificationRequest(executable=executable), 100)


def test_nul_arguments_and_invalid_output_limits(tmp_path):
    with pytest.raises(AppError) as error:
        BoundedVerificationRunner().run(str(tmp_path), VerificationRequest(executable="python", args=["\0"]), 100)
    assert error.value.code == "INVALID_EXECUTION_ARGUMENT"
    for limit in (-1, 1_048_577, 0.5, True, None, "100"):
        with pytest.raises(AppError) as error:
            run(tmp_path, "pass", limit)
        assert error.value.code == "INVALID_OUTPUT_LIMIT"


def test_resolution_excludes_repository_and_relative_path(tmp_path):
    with pytest.raises(AppError) as error:
        _resolve("node", tmp_path, {"PATH": os.pathsep.join(["", ".", str(tmp_path)])})
    assert error.value.code == "VERIFICATION_EXECUTABLE_NOT_FOUND"


def test_batch_wrapper_rejected(tmp_path, monkeypatch):
    external = tmp_path / "external"
    external.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("backend.app.execution.runner.shutil.which", lambda _: str(external / "npm.cmd"))
    with pytest.raises(AppError, match="Batch wrappers"):
        _resolve("npm", repo, {"PATH": str(external)})


def test_full_hash_includes_discarded_output(tmp_path):
    result = capture([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 1000000)"],
                     cwd=tmp_path, env=minimal_environment(), timeout=3, limit=7)
    assert result.stdout == b"x" * 7
    assert result.stdout_digest == hashlib.sha256(b"x" * 1000000).hexdigest()
    assert result.truncated


def test_inherited_pipe_does_not_hold_caller_past_deadline(tmp_path):
    # The descendant ends by itself; the runtime must not claim or perform tree cleanup.
    code = ("import subprocess,sys; subprocess.Popen([sys.executable,'-c',"
            "'import time; time.sleep(2)'], stdout=sys.stdout, stderr=sys.stderr)")
    start = time.monotonic()
    result = run(tmp_path, code, timeout=1)
    assert time.monotonic() - start < 1.8
    assert result.status == VerificationStatus.ERROR
    assert result.output_truncated
    assert result.exit_code is None


def test_capture_setup_failure_reaps_direct_child(tmp_path, monkeypatch):
    processes = []
    real_popen = subprocess.Popen
    def create(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr("backend.app.execution._process.subprocess.Popen", create)
    def fail(*_):
        raise OSError("synthetic")
    monkeypatch.setattr("backend.app.execution._process.os.set_blocking", fail)
    result = run(tmp_path, "import time; time.sleep(10)")
    assert result.status == VerificationStatus.ERROR
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


@pytest.mark.parametrize(("timeout", "limit"), [
    (0, 1), (1, -1), (301, 1), (float("nan"), 1), (float("inf"), 1),
    (True, 1), (None, 1), ("1", 1), (1, 0.5), (1, True), (1, None),
    (1, "100"), (1, 8 * 1_048_576 + 1),
])
def test_invalid_capture_bounds_never_start(tmp_path, timeout, limit):
    with pytest.raises(ValueError, match="bounds"):
        capture([sys.executable], cwd=tmp_path, env={}, timeout=timeout, limit=limit)


def test_native_executable_resolution_and_symlink_escape(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    external = tmp_path / "external"
    env = {"PATH": str(external)}
    monkeypatch.setattr("backend.app.execution.runner.shutil.which", lambda _: str(external / "node.exe"))
    assert _resolve("node", repo, env) == str((external / "node.exe").resolve())
    monkeypatch.setattr("backend.app.execution.runner.shutil.which", lambda _: str(repo / "node.exe"))
    with pytest.raises(AppError):
        _resolve("node", repo, env)
    monkeypatch.setattr("backend.app.execution.runner.shutil.which", lambda _: None)
    with pytest.raises(AppError):
        _resolve("node", repo, env)


def test_child_path_omits_relative_and_repository_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tmp_path), str(Path(sys.executable).parent)]))
    result = run(tmp_path, "import os; print(os.environ['PATH'])")
    assert result.stdout.strip() == str(Path(sys.executable).parent)


def test_invalid_directory_error_does_not_echo_input():
    with pytest.raises(AppError) as error:
        BoundedVerificationRunner().run("sensitive\0path", VerificationRequest(executable="python"), 100)
    assert error.value.code == "INVALID_EXECUTION_DIRECTORY"
    assert "sensitive" not in str(error.value)


def test_api_flow_with_real_git_and_bounded_runner(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.core.config import Settings
    from backend.app.main import create_app
    from backend.tests.integration.test_change_flow import committed_repository
    repo = committed_repository(tmp_path)
    settings = Settings(database_path=tmp_path / "owner-flow.sqlite3")
    app = create_app(settings=settings, verification=BoundedVerificationRunner())
    with TestClient(app) as client:
        response = client.post("/api/v1/changes", json={
            "title": "Person 2 flow", "intent": "Exercise real owned evidence", "repository_path": str(repo),
        })
        assert response.status_code == 201
        identifier = response.json()["id"]
        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        assert client.post(f"/api/v1/changes/{identifier}/refresh").json()["review_state"] == "MISSING_EVIDENCE"
        response = client.post(f"/api/v1/changes/{identifier}/verify", json={
            "executable": "python", "args": ["-c", "import app; assert app.VALUE == 2"],
        })
        assert response.status_code == 200
        assert response.json()["review_state"] == "READY_FOR_HUMAN_REVIEW"
    with TestClient(create_app(settings=settings, verification=BoundedVerificationRunner())) as client:
        assert client.get(f"/api/v1/changes/{identifier}").json()["verification"]["status"] == "PASSED"
        assert client.post(f"/api/v1/changes/{identifier}/refresh").json()["verification"] is None
