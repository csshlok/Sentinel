from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import VerificationRequest, VerificationStatus
from backend.app.contracts.ports import VerificationPort
from backend.app.core.errors import AppError
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.commands import unconfined_environment
from backend.app.execution.runner import BoundedVerificationRunner, _resolve
from backend.tests.support_checks import host_check_boxes
from backend.tests.support_kb import make_repo

# These are result-mapping and bounds tests. Commands go through the real
# run_confined_check/CheckBoxes code with the HOST harness (no containment);
# the real boundary is proven in backend/tests/verification/test_confined_runner.py.


def _runner(tmp_path: Path) -> BoundedVerificationRunner:
    boxes, _ = host_check_boxes(tmp_path.parent / f"{tmp_path.name}-boxes")
    return BoundedVerificationRunner(boxes)


def run(tmp_path: Path, code: str, limit: int = 1000, timeout: int = 3):
    if tmp_path.exists() and not (tmp_path / ".git").exists():
        make_repo(tmp_path, {"README.md": "hello\n"})
    return _runner(tmp_path).run(str(tmp_path), VerificationRequest(
        executable="python", args=["-c", code], timeout_seconds=timeout,
    ), limit, change_id=uuid4())


def test_contract_success_and_box_cwd(tmp_path):
    assert isinstance(BoundedVerificationRunner(), VerificationPort)
    result = run(tmp_path, "import os; print(os.getcwd())")
    assert result.status == VerificationStatus.PASSED
    assert result.exit_code == 0
    cwd = Path(result.stdout.strip())
    assert (cwd.parent.name, cwd.name) == ("AC", "tree")
    assert cwd != tmp_path.resolve()
    assert result.completed_at >= result.started_at
    assert type(result).model_validate_json(result.model_dump_json()) == result


def test_a_run_without_a_change_or_boxes_is_refused(tmp_path):
    make_repo(tmp_path, {"README.md": "hello\n"})
    request = VerificationRequest(executable="python", args=["-c", "print(1)"])
    with pytest.raises(AppError) as error:
        _runner(tmp_path).run(str(tmp_path), request, 100)
    assert error.value.code == "CHECK_CHANGE_REQUIRED"
    with pytest.raises(AppError) as error:
        BoundedVerificationRunner().run(str(tmp_path), request, 100, change_id=uuid4())
    assert error.value.code == "CHECK_RUNTIME_UNAVAILABLE"


def test_unconfined_toolchain_is_refused_without_the_opt_in(tmp_path):
    make_repo(tmp_path, {"README.md": "hello\n"})
    with pytest.raises(AppError) as error:
        _runner(tmp_path).run(str(tmp_path), VerificationRequest(executable="cargo"), 100,
                              change_id=uuid4())
    assert error.value.code == "CHECK_TOOLCHAIN_UNCONFINED"


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


def test_missing_cwd_is_refused_without_echoing_it(tmp_path):
    with pytest.raises(AppError) as error:
        run(tmp_path / "missing-private-path", "print('never')")
    assert error.value.code == "CHECK_TREE_FAILED"
    assert "private" not in str(error.value) and "private" not in str(error.value.details)


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
    make_repo(tmp_path, {"README.md": "x"})
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
    result = run(tmp_path, code, timeout=1)
    # The capture returns at its deadline; closing the box afterwards may wait
    # for the descendant to release the tree, which is not the caller's run.
    assert result.duration_ms < 1800
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
    # The capture primitive every check path (box and unconfined) shares.
    with pytest.raises(OSError):
        capture([sys.executable, "-c", "import time; time.sleep(10)"], cwd=tmp_path,
                env=minimal_environment(), timeout=3, limit=100)
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


def test_unconfined_path_omits_relative_and_repository_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(tmp_path), str(Path(sys.executable).parent)]))
    assert unconfined_environment(tmp_path)["PATH"] == str(Path(sys.executable).parent)


def test_box_child_sees_no_host_path_entry(tmp_path, monkeypatch):
    make_repo(tmp_path, {"README.md": "x"})
    import shutil

    git_dir = str(Path(shutil.which("git")).parent)  # Sentinel's own tree listing needs Git
    monkeypatch.setenv("PATH", os.pathsep.join(
        [".", str(tmp_path), str(Path(sys.executable).parent), git_dir]))
    result = run(tmp_path, "import os; print(os.environ['PATH'])")
    entries = result.stdout.strip().split(os.pathsep)
    assert str(tmp_path) not in entries and "." not in entries
    assert str(Path(sys.executable).parent) not in entries and git_dir not in entries


def test_invalid_directory_error_does_not_echo_input():
    with pytest.raises(AppError) as error:
        BoundedVerificationRunner().run("sensitive\0path", VerificationRequest(executable="python"), 100)
    assert error.value.code == "INVALID_EXECUTION_DIRECTORY"
    assert "sensitive" not in str(error.value)


def test_api_flow_with_real_git_and_bounded_runner(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app.core.config import Settings
    from backend.app.main import create_app
    from backend.tests.integration.test_change_flow import authorized_actor, committed_repository, verify_body
    repo = committed_repository(tmp_path)
    settings = Settings(database_path=tmp_path / "owner-flow.sqlite3")
    boxes, _ = host_check_boxes(tmp_path / "boxes")
    app = create_app(settings=settings, verification=BoundedVerificationRunner(boxes))
    auth = {"Authorization": f"Bearer {app.state.api_token}"}
    with TestClient(app, headers=auth) as client:
        response = client.post("/api/v1/changes", json={
            "title": "Person 2 flow", "intent": "Exercise real owned evidence", "repository_path": str(repo),
        })
        assert response.status_code == 201
        identifier = response.json()["id"]
        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        assert client.post(f"/api/v1/changes/{identifier}/refresh").json()["review_state"] == "MISSING_EVIDENCE"
        actor_id = authorized_actor(client, identifier)
        response = client.post(f"/api/v1/changes/{identifier}/verify",
                               json=verify_body(actor_id, "python",
                                                ["-c", "import app; assert app.VALUE == 2"]))
        assert response.status_code == 200
        assert response.json()["review_state"] == "READY_FOR_HUMAN_REVIEW"
    with TestClient(
        create_app(settings=settings, verification=BoundedVerificationRunner(boxes)), headers=auth
    ) as client:
        assert client.get(f"/api/v1/changes/{identifier}").json()["verification"]["status"] == "PASSED"
        assert client.post(f"/api/v1/changes/{identifier}/refresh").json()["verification"] is None
