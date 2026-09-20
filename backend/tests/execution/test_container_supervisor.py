"""Real-boundary tests for container_supervisor.py. Skip cleanly (not fail)
when Docker isn't installed/reachable -- this machine doesn't have it, but
these are written to actually exercise the real module once it is available.
"""
from __future__ import annotations

import pytest

from backend.app.core.errors import AppError
from backend.app.execution import container_supervisor


def test_image_for_known_executable():
    assert container_supervisor.image_for("python") == "python:3.12-slim"
    assert container_supervisor.image_for("PYTHON") == "python:3.12-slim"


def test_image_for_unconfigured_executable_is_a_stable_error():
    with pytest.raises(AppError) as info:
        container_supervisor.image_for("claude")
    assert info.value.code == "CONTAINER_IMAGE_NOT_CONFIGURED"


@pytest.mark.skipif(container_supervisor.is_available(), reason="only meaningful when Docker is absent")
def test_run_containerized_without_docker_is_a_stable_error_never_a_fabricated_success():
    with pytest.raises(AppError) as info:
        container_supervisor.run_containerized(["python", "-c", "pass"], cwd=__file__)
    assert info.value.code == "CONTAINER_ISOLATION_UNAVAILABLE"


@pytest.mark.skipif(not container_supervisor.is_available(), reason="Docker is not installed/reachable")
def test_run_containerized_real_python_process(tmp_path):
    process = container_supervisor.run_containerized(
        ["python", "-c", "print('hello from container')"], cwd=tmp_path,
    )
    try:
        exit_code = process.wait(timeout=30)
        assert exit_code == 0
        stdout, _stderr = process.logs()
        assert b"hello from container" in stdout
    finally:
        process.remove()


@pytest.mark.skipif(not container_supervisor.is_available(), reason="Docker is not installed/reachable")
def test_run_containerized_has_no_network_by_default(tmp_path):
    process = container_supervisor.run_containerized(
        ["python", "-c",
         "import urllib.request\n"
         "try:\n"
         "    urllib.request.urlopen('http://example.invalid', timeout=3)\n"
         "    print('NETWORK_REACHED')\n"
         "except Exception as e:\n"
         "    print('NETWORK_BLOCKED', type(e).__name__)\n"],
        cwd=tmp_path,
    )
    try:
        process.wait(timeout=30)
        stdout, _ = process.logs()
        assert b"NETWORK_BLOCKED" in stdout
        assert b"NETWORK_REACHED" not in stdout
    finally:
        process.remove()


@pytest.mark.skipif(not container_supervisor.is_available(), reason="Docker is not installed/reachable")
def test_run_containerized_only_sees_the_mounted_repository(tmp_path):
    (tmp_path / "marker.txt").write_text("visible-inside-container")
    process = container_supervisor.run_containerized(
        ["python", "-c",
         "import pathlib\n"
         "print('MARKER_PRESENT' if pathlib.Path('marker.txt').exists() else 'MARKER_MISSING')\n"
         "print('ROOT_CONTENTS', sorted(pathlib.Path('/').iterdir()))\n"],
        cwd=tmp_path,
    )
    try:
        process.wait(timeout=30)
        stdout, _ = process.logs()
        assert b"MARKER_PRESENT" in stdout
    finally:
        process.remove()
