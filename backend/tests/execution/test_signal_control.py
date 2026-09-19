"""Real-boundary tests for `execution/signal_control.py` (Part A: top-level
process suspend/resume), matching this codebase's real-process testing bar --
a real Windows subprocess is actually suspended and resumed, not mocked.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from backend.app.core.errors import AppError
from backend.app.execution import signal_control


def _spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, bufsize=0,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="suspend/resume is Windows-only")
def test_suspend_stops_output_growth_and_resume_lets_it_continue():
    process = _spawn(
        "import sys, time\n"
        "for i in range(30):\n"
        "    print(i)\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.1)\n"
    )
    os.set_blocking(process.stdout.fileno(), False)
    try:
        # Let it produce some real output before suspending.
        deadline = time.monotonic() + 5
        first_byte_seen = False
        while time.monotonic() < deadline and not first_byte_seen:
            try:
                if os.read(process.stdout.fileno(), 4096):
                    first_byte_seen = True
            except BlockingIOError:
                time.sleep(0.02)
        assert first_byte_seen, "the process never produced output before the pause test began"

        signal_control.suspend_process(process.pid)
        # Drain whatever was already in flight, then confirm nothing new
        # arrives while suspended.
        time.sleep(0.3)
        while True:
            try:
                if not os.read(process.stdout.fileno(), 4096):
                    break
            except BlockingIOError:
                break
        quiet_deadline = time.monotonic() + 1.0
        saw_output_while_paused = False
        while time.monotonic() < quiet_deadline:
            try:
                if os.read(process.stdout.fileno(), 4096):
                    saw_output_while_paused = True
                    break
            except BlockingIOError:
                time.sleep(0.02)
        assert not saw_output_while_paused
        assert process.poll() is None, "a suspended process must still be alive"

        signal_control.resume_process(process.pid)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="suspend/resume is Windows-only")
def test_unknown_pid_raises_a_stable_error():
    process = _spawn("pass")
    process.wait(timeout=5)
    # The PID is very likely already reclaimed by the OS; even in the rare
    # case it is not yet, the process has exited and cannot be opened for
    # SUSPEND_RESUME the same way a live process can.
    with pytest.raises(AppError) as info:
        signal_control.suspend_process(process.pid)
    assert info.value.code == "AGENT_PAUSE_FAILED"


def test_unsupported_platform_raises_a_stable_error_never_a_fabricated_success(monkeypatch):
    monkeypatch.setattr(signal_control, "_ntdll", None)
    monkeypatch.setattr(signal_control, "_kernel32", None)
    with pytest.raises(AppError) as info:
        signal_control.suspend_process(1234)
    assert info.value.code == "AGENT_PAUSE_UNSUPPORTED"
    with pytest.raises(AppError) as info:
        signal_control.resume_process(1234)
    assert info.value.code == "AGENT_PAUSE_UNSUPPORTED"
