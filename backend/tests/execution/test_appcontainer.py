"""SC1: the AppContainer launch primitive is verified before it runs and fails closed.

Real Windows AppContainers (no fakes of the boundary itself). Forced-failure cases
alter exactly one observed fact through a module-level seam and prove the child
was never resumed (its first statement writes a canary), is no longer running,
and that the restricted-token launcher was never used as a fallback.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import msvcrt
import os
import shutil
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.execution import appcontainer, process_supervisor
from backend.app.execution._process import capture
from backend.app.execution.appcontainer import (
    CAPABILITY_SIDS,
    LOW_INTEGRITY_RID,
    base_environment,
    delete_profile,
    derive_package_sid,
    ensure_profile,
    local_appdata_known_folder,
    profile_exists,
    query_token_facts,
    remove_tree_no_follow,
    spawn_appcontainer_supervised,
    verify_boundary,
)
from backend.app.execution.process_supervisor import IS_WINDOWS, is_process_running

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

TEST_PROFILE_PREFIX = "sentinel.test."
CHECKS = ("is_appcontainer", "package_sid", "integrity", "capabilities", "job")


@pytest.fixture
def node_exe() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is not installed")
    resolved = Path(found).resolve()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve()
    if program_files not in resolved.parents:
        pytest.skip("node must be installed under Program Files to be readable by an AppContainer")
    return str(resolved)


def _remove_with_retries(path: Path, attempts: int = 20) -> None:
    for attempt in range(attempts):
        try:
            remove_tree_no_follow(path)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)  # a terminated child may still hold files briefly


@pytest.fixture(scope="module", autouse=True)
def _sweep_orphan_test_folders():
    yield
    packages = local_appdata_known_folder() / "Packages"
    for folder in packages.glob(TEST_PROFILE_PREFIX + "*"):
        if folder.name.startswith(TEST_PROFILE_PREFIX) and not profile_exists(folder.name):
            _remove_with_retries(folder)


@pytest.fixture
def profile():
    name = TEST_PROFILE_PREFIX + uuid4().hex
    created, _ = ensure_profile(name, display_name="Sentinel test")
    try:
        yield created
    finally:
        try:
            _remove_with_retries(created.container_path)
        finally:
            delete_profile(name)
            _remove_with_retries(created.container_path.parent)
    assert not profile_exists(name)


@pytest.fixture
def no_restricted_fallback(monkeypatch):
    calls: list[object] = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("spawn_restricted_supervised must never be used as a fallback")

    monkeypatch.setattr(process_supervisor, "spawn_restricted_supervised", forbidden)
    return calls


def _env(profile, node_exe: str) -> dict[str, str]:
    return base_environment(profile.container_path, path_entries=[Path(node_exe).parent])


def _run(profile, node_exe: str, script: str, *, capabilities=(), timeout: float = 30):
    spawned = []

    def factory(argv, cwd, env):
        process = spawn_appcontainer_supervised(
            argv, cwd=cwd, env=env, redact=lambda text: text, profile_name=profile.name,
            expected_package_sid=profile.package_sid, capabilities=capabilities,
        )
        spawned.append(process)
        return process

    result = capture(
        [node_exe, "-e", script], cwd=profile.container_path, env=_env(profile, node_exe),
        timeout=timeout, limit=65_536, process_factory=factory,
    )
    return result, spawned[0]


def _canary_script(canary: Path, rest: str = "") -> str:
    return f"require('fs').writeFileSync({json.dumps(str(canary))}, 'ran');{rest}"


# --------------------------------------------------------------------- positive controls


def test_unboxed_positive_control_is_not_an_appcontainer() -> None:
    facts = query_token_facts(appcontainer._kernel32.GetCurrentProcess())
    assert facts.is_appcontainer is False
    assert facts.integrity_rid >= 0x2000
    assert facts.package_sid == ""
    with pytest.raises(AppError) as raised:
        verify_boundary(facts, expected_package_sid="S-1-15-2-1", expected_capability_sids=(),
                        job_member=True)
    assert raised.value.code == "APPCONTAINER_VERIFICATION_FAILED"
    assert raised.value.details == {"check": "is_appcontainer"}


@pytest.mark.parametrize("capabilities", [(), ("internetClient",)], ids=["none", "internetClient"])
def test_boxed_launch_reports_verified_live_token_facts(
    profile, node_exe, capabilities, monkeypatch,
) -> None:
    # A3: IsProcessInJob must answer on its own; the pid-list fallback is not used.
    def no_fallback(job):
        raise AssertionError("IsProcessInJob failed; the list_pids fallback was used")

    monkeypatch.setattr(appcontainer, "list_pids", no_fallback)
    result, process = _run(profile, node_exe, "process.stdout.write('boxed')",
                           capabilities=capabilities)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"boxed"
    facts = process.appcontainer
    assert facts.is_appcontainer is True
    assert facts.package_sid == derive_package_sid(profile.name) == profile.package_sid
    assert facts.integrity_rid == LOW_INTEGRITY_RID
    assert facts.capability_sids == tuple(CAPABILITY_SIDS[name] for name in capabilities)
    assert facts.job_verified is True
    assert process.restricted_token_applied is False
    payload = facts.to_payload()
    assert payload["integrity_rid"] == "0x1000"
    assert payload["capability_sids"] == list(facts.capability_sids)


def test_canary_positive_control_runs_without_a_forced_failure(profile, node_exe) -> None:
    canary = profile.container_path / "canary.txt"
    result, _ = _run(profile, node_exe, _canary_script(canary))
    assert result.returncode == 0, result.stderr
    assert canary.read_text(encoding="utf-8") == "ran"


# --------------------------------------------------------------------- fail closed


def _spawn_with_canary(profile, node_exe, canary: Path, *, capabilities=()):
    return spawn_appcontainer_supervised(
        [node_exe, "-e", _canary_script(canary)], cwd=profile.container_path,
        env=_env(profile, node_exe), redact=lambda text: text, profile_name=profile.name,
        expected_package_sid=profile.package_sid, capabilities=capabilities,
    )


def _record_pids(monkeypatch) -> list[int]:
    pids: list[int] = []
    real_assign = appcontainer._assign_to_job

    def recording_assign(job, process_handle):
        pids.append(int(appcontainer._kernel32.GetProcessId(process_handle)))
        return real_assign(job, process_handle)

    monkeypatch.setattr(appcontainer, "_assign_to_job", recording_assign)
    return pids


def _assert_never_ran(canary: Path, pids: list[int], fallback_calls: list[object]) -> None:
    assert len(pids) == 1 and pids[0] > 0
    time.sleep(1.0)  # a resumed node would have written the canary by now
    assert not canary.exists()
    assert is_process_running(pids[0]) is False
    assert fallback_calls == []


@pytest.mark.parametrize("check", CHECKS)
def test_each_failed_boundary_check_terminates_the_unresumed_child(
    profile, node_exe, check, monkeypatch, no_restricted_fallback,
) -> None:
    pids = _record_pids(monkeypatch)
    real_facts = appcontainer.query_token_facts
    altered = {
        "is_appcontainer": {"is_appcontainer": False},
        "package_sid": {"package_sid": "S-1-15-2-1-2-3-4-5-6-7"},
        "integrity": {"integrity_rid": 0x2000},
        "capabilities": {"capability_sids": (CAPABILITY_SIDS["internetClient"],)},
    }
    if check == "job":
        monkeypatch.setattr(appcontainer, "_process_in_job", lambda handle, job: False)
    else:
        def forged(process_handle):
            return dataclasses.replace(real_facts(process_handle), **altered[check])

        monkeypatch.setattr(appcontainer, "query_token_facts", forged)
    canary = profile.container_path / "canary.txt"

    with pytest.raises(AppError) as raised:
        _spawn_with_canary(profile, node_exe, canary)

    assert raised.value.code == "APPCONTAINER_VERIFICATION_FAILED"
    assert raised.value.details == {"check": check}
    _assert_never_ran(canary, pids, no_restricted_fallback)


def test_failed_job_assignment_terminates_the_unresumed_child(
    profile, node_exe, monkeypatch, no_restricted_fallback,
) -> None:
    pids: list[int] = []
    real_assign = appcontainer._assign_to_job

    def failing_assign(job, process_handle):
        pids.append(int(appcontainer._kernel32.GetProcessId(process_handle)))
        return real_assign(0, process_handle)  # a NULL job: the real API call fails

    monkeypatch.setattr(appcontainer, "_assign_to_job", failing_assign)
    canary = profile.container_path / "canary.txt"

    with pytest.raises(AppError) as raised:
        _spawn_with_canary(profile, node_exe, canary)

    assert raised.value.code == "APPCONTAINER_JOB_REQUIRED"
    assert raised.value.details == {"operation": "assign"}
    _assert_never_ran(canary, pids, no_restricted_fallback)


def test_failed_job_creation_refuses_before_any_process_exists(
    profile, node_exe, monkeypatch, no_restricted_fallback,
) -> None:
    def failing_create_job():
        raise AppError("PROCESS_SUPERVISION_FAILED", "CreateJobObjectW failed.")

    def no_process(*args, **kwargs):
        raise AssertionError("no process may be created without a Job")

    monkeypatch.setattr(appcontainer, "create_job", failing_create_job)
    monkeypatch.setattr(appcontainer, "_assign_to_job", no_process)
    canary = profile.container_path / "canary.txt"

    with pytest.raises(AppError) as raised:
        _spawn_with_canary(profile, node_exe, canary)

    assert raised.value.code == "APPCONTAINER_JOB_REQUIRED"
    assert raised.value.details == {"operation": "create"}
    time.sleep(0.5)
    assert not canary.exists()
    assert no_restricted_fallback == []


def test_appcontainer_module_never_references_the_restricted_launcher() -> None:
    assert "spawn_restricted_supervised" not in inspect.getsource(appcontainer)


# --------------------------------------------------------------------- handle whitelist


def test_concurrent_runs_reach_eof_independently(profile, node_exe) -> None:
    long_started = threading.Event()
    long_result: dict[str, object] = {}
    long_pid: list[int] = []

    def factory(argv, cwd, env):
        return spawn_appcontainer_supervised(
            argv, cwd=cwd, env=env, redact=lambda text: text, profile_name=profile.name,
            expected_package_sid=profile.package_sid, capabilities=(),
        )

    def run_long() -> None:
        def started(pid: int) -> None:
            long_pid.append(pid)
            long_started.set()

        long_result["value"] = capture(
            [node_exe, "-e", "process.stdout.write('long'); setTimeout(() => {}, 8000)"],
            cwd=profile.container_path, env=_env(profile, node_exe), timeout=60,
            limit=65_536, process_factory=factory, on_start=started,
        )

    thread = threading.Thread(target=run_long)
    thread.start()
    try:
        assert long_started.wait(20)
        began = time.monotonic()
        short = capture(
            [node_exe, "-e", "process.stdout.write('short')"], cwd=profile.container_path,
            env=_env(profile, node_exe), timeout=30, limit=65_536, process_factory=factory,
        )
        elapsed = time.monotonic() - began
        assert short.returncode == 0, short.stderr
        assert short.stdout == b"short"
        assert elapsed < 4.0, f"the short run waited {elapsed:.1f}s for its sibling"
        assert is_process_running(long_pid[0]) is True
    finally:
        thread.join(60)
    long = long_result["value"]
    assert long.returncode == 0
    assert long.stdout == b"long"


def _decoy_eof_seconds(start_child, *, wait: float) -> float | None:
    """Seconds until a parent-held inheritable pipe hits EOF after the parent closes
    its write end while a child launched by ``start_child`` is alive; None on timeout."""

    decoy_read, decoy_write = appcontainer._pipe()  # write end is inheritable
    child = start_child()
    try:
        appcontainer._kernel32.CloseHandle(decoy_write)
        reader = os.fdopen(msvcrt.open_osfhandle(decoy_read, os.O_RDONLY | os.O_BINARY), "rb", 0)
        done = threading.Event()
        began = time.monotonic()

        def drain() -> None:
            try:
                reader.read()
            finally:
                done.set()

        threading.Thread(target=drain, daemon=True).start()
        finished = done.wait(wait)
        elapsed = time.monotonic() - began
        return elapsed if finished else None
    finally:
        try:
            child.kill()
        finally:
            child.close()


def test_appcontainer_child_does_not_inherit_unlisted_handles(profile, node_exe) -> None:
    def start():
        return spawn_appcontainer_supervised(
            [node_exe, "-e", "setTimeout(() => {}, 8000)"], cwd=profile.container_path,
            env=_env(profile, node_exe), redact=lambda text: text, profile_name=profile.name,
            expected_package_sid=profile.package_sid, capabilities=(),
        )

    elapsed = _decoy_eof_seconds(start, wait=4.0)
    assert elapsed is not None and elapsed < 4.0


def test_decoy_positive_control_detects_inheritance_without_a_handle_list(
    tmp_path, node_exe,
) -> None:
    # The restricted launcher passes bInheritHandles=TRUE with no handle list, so the
    # same probe must observe the decoy held open by its child.
    def start():
        return process_supervisor.spawn_restricted_supervised(
            [node_exe, "-e", "setTimeout(() => {}, 8000)"], cwd=tmp_path,
            env={"SystemRoot": os.environ["SystemRoot"], "PATH": str(Path(node_exe).parent)},
            redact=lambda text: text,
        )

    assert _decoy_eof_seconds(start, wait=3.0) is None


# --------------------------------------------------------------------- refusals


def test_local_appdata_comes_from_the_known_folder(profile, node_exe, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    env = base_environment(profile.container_path)
    assert env["LOCALAPPDATA"] == str(local_appdata_known_folder())
    assert env["LOCALAPPDATA"] != str(tmp_path)
    assert set(env) == {"SystemRoot", "windir", "COMSPEC", "PATH", "LOCALAPPDATA", "TEMP", "TMP"}
    assert env["TEMP"] == env["TMP"] == str(profile.container_path / "Temp")
    result, process = _run(profile, node_exe, "process.stdout.write(process.env.LOCALAPPDATA)")
    assert result.returncode == 0, result.stderr
    assert process.appcontainer.is_appcontainer is True


@pytest.mark.parametrize("case", ["no LOCALAPPDATA", "relative executable", "unknown capability"])
def test_invalid_launch_requests_fail_before_any_process_exists(
    profile, node_exe, case, monkeypatch, no_restricted_fallback,
) -> None:
    def no_job():
        raise AssertionError("nothing may be created for an invalid request")

    monkeypatch.setattr(appcontainer, "create_job", no_job)
    env = _env(profile, node_exe)
    argv = [node_exe, "-e", "0"]
    capabilities: tuple[str, ...] = ()
    if case == "no LOCALAPPDATA":
        env.pop("LOCALAPPDATA")
    elif case == "relative executable":
        argv[0] = "node.exe"
    else:
        capabilities = ("documentsLibrary",)

    with pytest.raises(AppError) as raised:
        spawn_appcontainer_supervised(
            argv, cwd=profile.container_path, env=env, redact=lambda text: text,
            profile_name=profile.name, expected_package_sid=profile.package_sid,
            capabilities=capabilities,
        )
    assert raised.value.code == "APPCONTAINER_LAUNCH_FAILED"
    assert no_restricted_fallback == []


def test_non_windows_is_refused_with_a_stable_code(monkeypatch) -> None:
    monkeypatch.setattr(appcontainer, "IS_WINDOWS", False)
    with pytest.raises(AppError) as raised:
        spawn_appcontainer_supervised(
            [r"C:\x.exe"], cwd=".", env={"LOCALAPPDATA": "x"}, redact=lambda text: text,
            profile_name="sentinel.test.x", expected_package_sid="S-1-15-2-1", capabilities=(),
        )
    assert raised.value.code == "APPCONTAINER_UNSUPPORTED"
    assert raised.value.status_code == 501
