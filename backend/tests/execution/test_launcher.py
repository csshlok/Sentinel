from __future__ import annotations

import os
import sys
import threading
import time
from uuid import uuid4

import pytest

from backend.app.contracts.models import (
    AgentAttachRequest, AgentLaunchRequest, AgentRunStatus,
)
from backend.app.contracts.ports import AgentLauncherPort
from backend.app.core.errors import AppError
from backend.app.execution.launcher import (
    DESCENDANT_LIMITATION, AgentAdapter, AgentLauncher,
)
from backend.app.execution.process_supervisor import IS_WINDOWS

CHANGE = uuid4()


def request(code: str, **kw):
    kw.setdefault("timeout_seconds", 10)
    return AgentLaunchRequest(adapter="generic", executable="python",
                              args=["-c", code], **kw)


def launch(tmp_path, code, limit=10_000, **kw):
    return AgentLauncher().launch(CHANGE, str(tmp_path), request(code, **kw), limit)


def test_port_conformance():
    assert isinstance(AgentLauncher(), AgentLauncherPort)


def test_pass_fail_and_cwd_with_spaces(tmp_path):
    spaced = tmp_path / "dir with space"
    spaced.mkdir()
    ok = launch(spaced, "import os; print(os.getcwd())")
    assert ok.status is AgentRunStatus.PASSED and ok.exit_code == 0
    assert ok.stdout.strip() == str(spaced.resolve())
    assert ok.top_level_pid and ok.duration_ms is not None
    bad = launch(tmp_path, "raise SystemExit(3)")
    assert bad.status is AgentRunStatus.FAILED and bad.exit_code == 3


def test_reports_descendant_control_only_when_job_supervision_is_real(tmp_path):
    run = launch(tmp_path, "print(1)")
    assert run.descendant_control_available is IS_WINDOWS
    assert run.restricted_token_applied is IS_WINDOWS
    assert (DESCENDANT_LIMITATION in run.limitations) is (not IS_WINDOWS)
    if IS_WINDOWS:
        assert "maximum privileges" in (run.authority_reduction or "").lower()
        assert "integrity level is retained" in (run.authority_reduction or "").lower()
        assert "not a sandbox" in (run.authority_reduction or "").lower()
    assert type(run).model_validate_json(run.model_dump_json()) == run


def test_timeout_terminates_direct_child(tmp_path):
    started = time.monotonic()
    run = launch(tmp_path, "import time; time.sleep(30)", timeout_seconds=1)
    assert run.status is AgentRunStatus.TIMED_OUT and run.exit_code is None
    assert time.monotonic() - started < 6
    expected = "supervised process tree" if IS_WINDOWS else "direct child only"
    assert any(expected in item for item in run.limitations)


def test_output_budget_is_shared_and_bounded(tmp_path):
    run = launch(tmp_path,
                 "import sys\nsys.stdout.write('a'*5000)\nsys.stderr.write('b'*5000)",
                 limit=100)
    assert len(run.stdout) + len(run.stderr) <= 100 and run.output_truncated


def test_cancel_running_child(tmp_path):
    launcher = AgentLauncher()
    holder = {}

    def go():
        holder["run"] = launcher.launch(
            CHANGE, str(tmp_path), request("import time; time.sleep(60)", timeout_seconds=120), 1000)

    thread = threading.Thread(target=go)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not launcher._runs:
        time.sleep(0.02)
    run_id = next(iter(launcher._runs))
    time.sleep(0.3)
    stopped = launcher.stop(run_id)
    thread.join(10)
    assert stopped.status is AgentRunStatus.CANCELLED
    assert holder["run"].status is AgentRunStatus.CANCELLED
    assert launcher.get(run_id).status is AgentRunStatus.CANCELLED
    # Stopping a finished run is a harmless read of the final record.
    assert launcher.stop(run_id).status is AgentRunStatus.CANCELLED


def test_pause_and_resume_a_real_running_agent(tmp_path):
    launcher = AgentLauncher()
    holder = {}

    def go():
        holder["run"] = launcher.launch(
            CHANGE, str(tmp_path),
            request("import sys, time\n"
                    "for i in range(6):\n"
                    "    print(i)\n"
                    "    sys.stdout.flush()\n"
                    "    time.sleep(0.2)\n", timeout_seconds=30),
            10_000,
        )

    thread = threading.Thread(target=go)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not launcher._runs:
        time.sleep(0.02)
    run_id = next(iter(launcher._runs))
    # Let it actually start producing before pausing.
    time.sleep(0.4)
    paused = launcher.pause(run_id)
    assert paused.status is AgentRunStatus.PAUSED and paused.paused_at is not None
    stdout_at_pause = launcher.get(run_id).stdout
    time.sleep(1.0)
    assert launcher.get(run_id).stdout == stdout_at_pause, (
        "no new output should be captured while the process is suspended")
    resumed = launcher.resume(run_id)
    assert resumed.status is AgentRunStatus.RUNNING and resumed.resumed_at is not None
    thread.join(15)
    final = holder["run"]
    assert final.status is AgentRunStatus.PASSED and final.exit_code == 0
    assert launcher.get(run_id).status is AgentRunStatus.PASSED


def test_pause_and_resume_reject_non_pausable_runs(tmp_path):
    launcher = AgentLauncher()
    with pytest.raises(AppError) as info:
        launcher.pause(uuid4())
    assert info.value.code == "AGENT_RUN_NOT_FOUND" and info.value.status_code == 404
    with pytest.raises(AppError) as info:
        launcher.resume(uuid4())
    assert info.value.code == "AGENT_RUN_NOT_FOUND"

    attached = launcher.attach(CHANGE, AgentAttachRequest(adapter="claude", external_run_id="ext-p"))
    with pytest.raises(AppError) as info:
        launcher.pause(attached.id)
    assert info.value.code == "AGENT_RUN_NOT_PAUSABLE"
    with pytest.raises(AppError) as info:
        launcher.resume(attached.id)
    assert info.value.code == "AGENT_RUN_NOT_RESUMABLE"

    finished = launcher.launch(CHANGE, str(tmp_path), request("print(1)"), 10_000)
    with pytest.raises(AppError) as info:
        launcher.pause(finished.id)
    assert info.value.code == "AGENT_RUN_NOT_PAUSABLE"
    with pytest.raises(AppError) as info:
        launcher.resume(finished.id)
    assert info.value.code == "AGENT_RUN_NOT_RESUMABLE"


def test_incremental_output_is_persisted_before_completion(tmp_path, monkeypatch):
    """Part C: on_update must see growing stdout while the run is still in
    flight, not only the final aggregate once it finishes."""

    from backend.app.execution import launcher as module
    monkeypatch.setattr(module, "CHUNK_NOTIFY_INTERVAL_SECONDS", 0.05)
    launcher = AgentLauncher()
    seen_running_stdout_lengths: list[int] = []
    launcher.on_update = lambda run: seen_running_stdout_lengths.append(
        len(run.stdout)) if run.status is AgentRunStatus.RUNNING else None
    run = launcher.launch(
        CHANGE, str(tmp_path),
        request("import sys, time\n"
                "for i in range(6):\n"
                "    print(i)\n"
                "    sys.stdout.flush()\n"
                "    time.sleep(0.2)\n"),
        10_000,
    )
    assert run.status is AgentRunStatus.PASSED
    growing = [n for n in seen_running_stdout_lengths if n > 0]
    assert growing, "at least one in-flight update should have carried partial output"
    assert len(set(growing)) > 1, "stdout should have grown across more than one in-flight update"


def test_secret_split_across_chunk_boundary_is_still_redacted(tmp_path, monkeypatch):
    """A secret written in two separate flushes (so it can arrive in two
    separate incremental on_chunk deltas) must still be redacted once fully
    accumulated, not just in the final aggregate -- redacting each delta in
    isolation (against the complete secret string) would never recognize
    either half alone, so the *combined* text would carry the complete,
    unredacted secret forever after, even though every individual delta was
    "checked". A snapshot taken before the second half has even arrived is
    expected to show the harmless partial prefix (nothing to redact yet);
    what matters is that once the full secret is present, it never survives
    unredacted in what's persisted.
    """

    from backend.app.execution import launcher as module
    monkeypatch.setattr(module, "CHUNK_NOTIFY_INTERVAL_SECONDS", 0.01)
    secret = "sk-canary-abcdef123456"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    launcher = AgentLauncher(adapters={
        "claude": AgentAdapter("claude", frozenset({"python"}), frozenset({"ANTHROPIC_API_KEY"}))})
    seen_running_stdout: list[str] = []
    launcher.on_update = lambda run: seen_running_stdout.append(
        run.stdout) if run.status is AgentRunStatus.RUNNING else None
    code = (
        "import os, sys, time\n"
        "secret = os.environ['ANTHROPIC_API_KEY']\n"
        "half = len(secret) // 2\n"
        "sys.stdout.write(secret[:half]); sys.stdout.flush()\n"
        "time.sleep(0.3)\n"
        "sys.stdout.write(secret[half:]); sys.stdout.flush()\n"
    )
    run = launcher.launch(CHANGE, str(tmp_path), AgentLaunchRequest(
        adapter="claude", executable="python", timeout_seconds=10,
        args=["-c", code], environment_keys=["ANTHROPIC_API_KEY"]), 1000)
    assert run.status is AgentRunStatus.PASSED
    assert secret not in run.stdout
    # No in-flight snapshot ever carried the *complete* secret unredacted --
    # a partial prefix before the second half arrives is expected and fine.
    assert all(secret not in s for s in seen_running_stdout)
    assert any("[REDACTED]" in s for s in seen_running_stdout), (
        "at least one in-flight snapshot should show the secret already "
        "redacted once fully accumulated, not only the final result"
    )


def test_stop_unknown_and_attached(tmp_path):
    launcher = AgentLauncher()
    with pytest.raises(AppError) as info:
        launcher.stop(uuid4())
    assert info.value.code == "AGENT_RUN_NOT_FOUND" and info.value.status_code == 404
    with pytest.raises(AppError):
        launcher.get(uuid4())
    attached = launcher.attach(CHANGE, AgentAttachRequest(adapter="claude", external_run_id="ext-1"))
    assert attached.status is AgentRunStatus.ATTACHED
    assert attached.external_run_id == "ext-1" and attached.top_level_pid is None
    assert attached.descendant_control_available is False
    stopped = launcher.stop(attached.id)
    assert stopped.status is AgentRunStatus.ATTACHED
    assert any("cannot be stopped" in item for item in stopped.limitations)
    assert launcher.stop(attached.id) == stopped


def test_attach_unknown_adapter_and_declared_time():
    launcher = AgentLauncher()
    with pytest.raises(AppError) as info:
        launcher.attach(CHANGE, AgentAttachRequest(adapter="nope", external_run_id="x"))
    assert info.value.code == "AGENT_ADAPTER_UNSUPPORTED"
    from datetime import UTC, datetime
    when = datetime(2026, 1, 1, tzinfo=UTC)
    run = launcher.attach(CHANGE, AgentAttachRequest(
        adapter="codex", external_run_id="r", declared_started_at=when))
    assert run.started_at == when and run.adapter == "codex"


@pytest.mark.parametrize("adapter,executable", [
    ("generic", "bash"), ("codex", "python"), ("claude", "codex"),
])
def test_executable_not_allowed_for_adapter(tmp_path, adapter, executable):
    with pytest.raises(AppError) as info:
        AgentLauncher().launch(CHANGE, str(tmp_path), AgentLaunchRequest(
            adapter=adapter, executable=executable), 100)
    assert info.value.code == "AGENT_EXECUTABLE_NOT_ALLOWED"


def test_unknown_adapter_and_bad_bounds(tmp_path):
    launcher = AgentLauncher()
    with pytest.raises(AppError) as info:
        launcher.launch(CHANGE, str(tmp_path), AgentLaunchRequest(
            adapter="zzz", executable="python"), 100)
    assert info.value.code == "AGENT_ADAPTER_UNSUPPORTED"
    for limit in (-1, 2_000_000, True, 1.5):
        with pytest.raises(AppError) as info:
            launcher.launch(CHANGE, str(tmp_path), request("pass"), limit)
        assert info.value.code == "INVALID_OUTPUT_LIMIT"
    with pytest.raises(AppError) as info:
        launcher.launch(CHANGE, str(tmp_path), request("pass\0"), 100)
    assert info.value.code == "INVALID_EXECUTION_ARGUMENT"
    with pytest.raises(AppError) as info:
        launcher.launch(CHANGE, str(tmp_path / "missing-private"), request("pass"), 100)
    assert info.value.code == "INVALID_EXECUTION_DIRECTORY"
    assert "private" not in info.value.message
    file = tmp_path / "f.txt"
    file.write_text("x")
    with pytest.raises(AppError):
        launcher.launch(CHANGE, str(file), request("pass"), 100)
    with pytest.raises(AppError):
        launcher.launch(CHANGE, "bad\0path", request("pass"), 100)


def test_missing_executable_is_a_safe_error_run(tmp_path):
    launcher = AgentLauncher(adapters={"ghost": AgentAdapter("ghost", frozenset({"no-such-agent-xyz"}))})
    run = launcher.launch(CHANGE, str(tmp_path), AgentLaunchRequest(
        adapter="ghost", executable="no-such-agent-xyz"), 100)
    assert run.status is AgentRunStatus.ERROR and run.exit_code is None
    assert any("did not start" in item for item in run.limitations)
    assert str(tmp_path) not in run.model_dump_json()


def test_startup_oserror_is_a_safe_error_run(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("private detail")
    monkeypatch.setattr("backend.app.execution.launcher.capture", boom)
    run = launch(tmp_path, "pass")
    assert run.status is AgentRunStatus.ERROR
    assert "private" not in run.model_dump_json()


@pytest.mark.parametrize("key", [
    "PATH", "GIT_DIR", "PYTHONPATH", "NODE_OPTIONS", "LD_PRELOAD", "bad key", "1X",
    "MY_SECRET", "GITHUB_TOKEN", "CHANGE_ASSURANCE_GRANT",
])
def test_forbidden_environment_keys(tmp_path, key):
    with pytest.raises(AppError) as info:
        launch(tmp_path, "pass", environment_keys=[key])
    assert info.value.code == "AGENT_ENVIRONMENT_KEY_DENIED"


def test_environment_is_stripped_and_secrets_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_CANARY_SECRET_TOKEN", "canary-value-123456")
    monkeypatch.setenv("KB_HARMLESS", "visible")
    monkeypatch.setenv("KB_UNREQUESTED", "should-not-pass")
    code = ("import os,sys\n"
            "print(sorted(k for k in os.environ if k.startswith('KB_')))\n"
            "print('leak:canary-value-123456')")
    run = launch(tmp_path, code, environment_keys=["KB_HARMLESS"])
    assert "KB_HARMLESS" in run.stdout and "KB_UNREQUESTED" not in run.stdout
    assert "KB_CANARY" not in run.stdout
    assert "canary-value-123456" not in run.model_dump_json()
    assert "[REDACTED]" in run.stdout


def test_adapter_credential_key_is_forwarded_but_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-canary-abcdef123456")
    launcher = AgentLauncher(adapters={
        "claude": AgentAdapter("claude", frozenset({"python"}), frozenset({"ANTHROPIC_API_KEY"}))})
    run = launcher.launch(CHANGE, str(tmp_path), AgentLaunchRequest(
        adapter="claude", executable="python", timeout_seconds=10,
        args=["-c", "import os; print(os.environ['ANTHROPIC_API_KEY'])"],
        environment_keys=["ANTHROPIC_API_KEY"]), 1000)
    assert run.status is AgentRunStatus.PASSED
    assert "sk-canary" not in run.stdout and "[REDACTED]" in run.stdout


def test_encoded_secret_is_still_redacted(tmp_path, monkeypatch):
    """A compromised agent base64/hex-encoding a forwarded secret before
    printing it must not defeat redaction -- exact-substring matching alone
    would let this through untouched."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-canary-abcdef123456")
    launcher = AgentLauncher(adapters={
        "claude": AgentAdapter("claude", frozenset({"python"}), frozenset({"ANTHROPIC_API_KEY"}))})
    code = (
        "import os, base64\n"
        "raw = os.environ['ANTHROPIC_API_KEY'].encode()\n"
        "print(base64.b64encode(raw).decode())\n"
        "print(base64.urlsafe_b64encode(raw).decode())\n"
        "print(raw.hex())\n"
    )
    run = launcher.launch(CHANGE, str(tmp_path), AgentLaunchRequest(
        adapter="claude", executable="python", timeout_seconds=10,
        args=["-c", code], environment_keys=["ANTHROPIC_API_KEY"]), 1000)
    assert run.status is AgentRunStatus.PASSED
    assert "sk-canary" not in run.stdout
    assert run.stdout.count("[REDACTED]") == 3


def test_absent_requested_key_is_simply_not_set(tmp_path, monkeypatch):
    monkeypatch.delenv("KB_ABSENT", raising=False)
    run = launch(tmp_path, "import os; print('KB_ABSENT' in os.environ)",
                 environment_keys=["KB_ABSENT"])
    assert run.stdout.strip() == "False"


def test_invalid_utf8_is_marked_truncated(tmp_path):
    run = launch(tmp_path, "import sys; sys.stdout.buffer.write(b'ok\\xff')")
    assert run.output_truncated


def test_repository_scripts_shadowing_path_are_not_used(tmp_path, monkeypatch):
    marker = tmp_path / "python.bat"
    marker.write_text("@echo hijacked")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    run = launch(tmp_path, "print('real')")
    assert run.stdout.strip() == "real"
    assert run.status is AgentRunStatus.PASSED


def test_concurrent_runs_are_independent(tmp_path):
    launcher = AgentLauncher()
    results = []

    def go(n):
        results.append(launcher.launch(CHANGE, str(tmp_path), request(f"print({n})"), 100))

    threads = [threading.Thread(target=go, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.stdout.strip() for r in results) == ["0", "1", "2", "3"]
    assert len({r.id for r in results}) == 4
    assert sys.executable


def test_finished_runs_are_evicted_beyond_the_cap(tmp_path, monkeypatch):
    from backend.app.execution import launcher as module
    monkeypatch.setattr(module, "MAX_RETAINED_RUNS", 3)
    launcher = AgentLauncher()
    ids = [launcher.attach(CHANGE, AgentAttachRequest(adapter="claude", external_run_id=f"r{i}")).id
           for i in range(6)]
    assert len(launcher._runs) == 3
    assert set(launcher._runs) == set(ids[-3:])
    run = launcher.launch(CHANGE, str(tmp_path), request("print(1)"), 100)
    assert len(launcher._runs) == 3 and launcher.get(run.id).status is AgentRunStatus.PASSED


def test_adapter_metadata_reports_availability_without_paths(tmp_path):
    launcher = AgentLauncher(adapters={"ghost": AgentAdapter("ghost", frozenset({"no-such-agent-xyz"}),
                                                            frozenset({"GHOST_API_KEY"}))})
    listing = {item["adapter"]: item for item in launcher.adapters(str(tmp_path))}
    assert set(listing) == {"generic", "codex", "claude", "ghost"}
    assert listing["generic"]["executables"]["python"] is True
    assert listing["ghost"]["executables"] == {"no-such-agent-xyz": False}
    assert listing["ghost"]["credential_keys"] == ["GHOST_API_KEY"]
    assert all(item["descendant_control_available"] is IS_WINDOWS for item in listing.values())
    assert all(item["restricted_token_available"] is IS_WINDOWS for item in listing.values())
    assert str(tmp_path) not in repr(listing) and sys.executable not in repr(listing)
    assert launcher.adapters()      # default location works
    with pytest.raises(AppError):
        launcher.adapters(str(tmp_path / "missing"))


def test_observer_sees_every_state_and_cannot_break_the_run(tmp_path):
    seen = []
    launcher = AgentLauncher()
    launcher.on_update = lambda run: seen.append((run.status, run.top_level_pid))
    run = launcher.launch(CHANGE, str(tmp_path), request("print(1)"), 100)
    statuses = [status for status, _ in seen]
    assert statuses[0] is AgentRunStatus.RUNNING and statuses[-1] is AgentRunStatus.PASSED
    assert any(pid for _, pid in seen) and run.status is AgentRunStatus.PASSED

    def broken(_run):
        raise RuntimeError("observer down")

    launcher.on_update = broken
    assert launcher.launch(CHANGE, str(tmp_path), request("print(2)"), 100).status is AgentRunStatus.PASSED
