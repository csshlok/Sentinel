"""Real Windows proof: the snapshot runtime runs in a box only while it is granted.

Builds ``python_runtime(sys.executable)`` into a throwaway cache, then launches
the snapshot ``python.exe`` inside a fresh ``sentinel.test.*`` AppContainer
profile: without the per-run package-SID grant it cannot load (negative
control), with the grant it imports pytest and coverage, and after the revoke it
cannot load again. The profile and the cache are removed afterwards.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.execution.process_supervisor import IS_WINDOWS

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

# GitHub-hosted runners install Python under C:\hostedtoolcache with a reparse point
# inside the install (CI run 36831151656). Sentinel deliberately refuses to snapshot a
# runtime source containing a link (CHECK_RUNTIME_UNSAFE_SOURCE; proven by
# test_check_runtime.py::test_python_runtime_refuses_an_install_with_a_reparse_point),
# so this real-box proof cannot build its snapshot there. It runs on any machine
# whose interpreter install is link-free, and on hosted runners only when opted in.
HOSTED_PYTHON_HAS_REPARSE_POINT = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("SENTINEL_CI_REAL_APPCONTAINER") != "1",
    reason="hosted runner Python install contains a reparse point, which the check-runtime "
           "snapshot refuses by design (CHECK_RUNTIME_UNSAFE_SOURCE); "
           "set SENTINEL_CI_REAL_APPCONTAINER=1 to run",
)

TEST_PROFILE_PREFIX = "sentinel.test."


def _remove_with_retries(path: Path, attempts: int = 20) -> None:
    from backend.app.execution.appcontainer import remove_tree_no_follow

    for attempt in range(attempts):
        try:
            remove_tree_no_follow(path)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)  # a terminated child may still hold files briefly


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    from backend.app.execution.check_runtime import python_runtime

    cache = tmp_path_factory.mktemp("check-runtime-real") / "check-runtimes"
    try:
        yield cache, python_runtime(sys.executable, root=cache)
    finally:
        shutil.rmtree(cache, ignore_errors=True)


@pytest.fixture
def profile():
    from backend.app.execution.appcontainer import delete_profile, ensure_profile, profile_exists

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


def _run_snapshot_python(profile, runtime, code: str):
    from backend.app.execution._process import capture
    from backend.app.execution.appcontainer import base_environment, spawn_appcontainer_supervised

    interpreter, dependencies, _ = runtime
    env = base_environment(profile.container_path)
    env.update({
        "PYTHONHOME": str(interpreter.path),
        "PYTHONPATH": str(dependencies.path),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    spawned = []

    def factory(argv, cwd, env):
        process = spawn_appcontainer_supervised(
            argv, cwd=cwd, env=env, redact=lambda text: text, profile_name=profile.name,
            expected_package_sid=profile.package_sid, capabilities=(),
        )
        spawned.append(process)
        return process

    result = capture(
        [str(interpreter.path / "python.exe"), "-c", code], cwd=profile.container_path, env=env,
        timeout=120, limit=65_536, process_factory=factory,
    )
    return result, spawned[0]


STATUS_DLL_NOT_FOUND = 0xC0000135


def _cannot_load(result) -> bool:
    """The box could not even load the interpreter (spike 006 A), so nothing ran."""

    return (result.returncode is not None
            and result.returncode & 0xFFFFFFFF == STATUS_DLL_NOT_FOUND
            and result.stdout == b"")


IMPORT_PROBE = "import pytest, coverage, sys; print(sys.prefix); print(pytest.__file__)"


@HOSTED_PYTHON_HAS_REPARSE_POINT
def test_snapshot_python_runs_in_the_box_only_while_granted(runtime, profile) -> None:
    from backend.app.execution.acl import grant_package_read, revoke_package_read

    cache, snapshots = runtime
    interpreter, dependencies, _ = snapshots
    entries = (interpreter.path, dependencies.path)

    # Negative control: the snapshot exists, but the box holds no grant on it.
    denied, process = _run_snapshot_python(profile, snapshots, IMPORT_PROBE)
    assert process.appcontainer.is_appcontainer is True
    assert _cannot_load(denied)

    for entry in entries:
        grant_package_read(entry, profile.package_sid, allowed_root=cache)
    try:
        allowed, process = _run_snapshot_python(profile, snapshots, IMPORT_PROBE)
        facts = process.appcontainer
        assert facts.is_appcontainer is True
        assert facts.package_sid == profile.package_sid
        assert facts.job_verified is True
        assert allowed.returncode == 0, allowed.stderr.decode(errors="replace")
        lines = allowed.stdout.decode().splitlines()
        assert Path(lines[0]) == interpreter.path
        assert Path(lines[1]).is_relative_to(dependencies.path)
    finally:
        for entry in entries:
            revoke_package_read(entry, profile.package_sid, allowed_root=cache)

    # After the revoke the same launch is denied again.
    revoked, _ = _run_snapshot_python(profile, snapshots, IMPORT_PROBE)
    assert _cannot_load(revoked)
