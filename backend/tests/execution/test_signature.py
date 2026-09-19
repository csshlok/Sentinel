"""T1: tests for the Windows-Authenticode signature check (B.4/B.10).

The exit-code/output-parsing logic is tested by faking `capture` (the same
bounded-subprocess primitive `execution/_process.py` already provides), so
the parsing behavior is deterministic regardless of whether this machine has
`signtool.exe` installed. Two tests additionally run against a *real*
`signtool.exe` -- a system binary and a genuinely unsigned test binary -- and
are skipped (not faked, not failed) when `signtool` is unavailable, per this
project's "no safety theater" standard: a skip is honest, a fabricated pass
is not.
"""

from __future__ import annotations

import os

import pytest

from backend.app.execution import signature as sig_mod
from backend.app.execution._process import CapturedProcess


def _fake_capture(returncode, *, stdout=b"", stderr=b"", timed_out=False, cancelled=False):
    def _capture(argv, **kwargs):
        del argv, kwargs
        return CapturedProcess(
            returncode=returncode, stdout=stdout, stderr=stderr, truncated=False,
            timed_out=timed_out, incomplete=timed_out, stdout_digest="",
            cancelled=cancelled, pid=None,
        )
    return _capture


def test_returns_unknown_when_not_windows(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Linux")
    assert sig_mod.check_signature(str(tmp_path / "x.exe")) == "unknown"


def test_returns_unknown_when_signtool_is_unavailable(monkeypatch, tmp_path) -> None:
    """The dedicated 'simulated signtool absence' case from the plan's own
    test list: never fabricates 'unsigned', reports 'unknown' honestly."""

    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: None)
    assert sig_mod.check_signature(str(tmp_path / "x.exe")) == "unknown"


def test_returns_unknown_when_target_file_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: "signtool.exe")
    assert sig_mod.check_signature(str(tmp_path / "missing.exe")) == "unknown"


def test_returns_valid_on_exit_zero(monkeypatch, tmp_path) -> None:
    target = tmp_path / "signed.exe"
    target.write_bytes(b"x")
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: "signtool.exe")
    monkeypatch.setattr(sig_mod, "capture", _fake_capture(0))
    assert sig_mod.check_signature(str(target)) == "valid"


def test_returns_unsigned_when_signtool_reports_no_signature(monkeypatch, tmp_path) -> None:
    target = tmp_path / "unsigned.exe"
    target.write_bytes(b"x")
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: "signtool.exe")
    monkeypatch.setattr(sig_mod, "capture", _fake_capture(1, stderr=b"No signature found."))
    assert sig_mod.check_signature(str(target)) == "unsigned"


def test_returns_invalid_for_a_real_but_broken_signature(monkeypatch, tmp_path) -> None:
    target = tmp_path / "bad.exe"
    target.write_bytes(b"x")
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: "signtool.exe")
    monkeypatch.setattr(
        sig_mod, "capture", _fake_capture(1, stderr=b"A certificate chain could not be built.")
    )
    assert sig_mod.check_signature(str(target)) == "invalid"


def test_returns_unknown_on_timeout_rather_than_failing(monkeypatch, tmp_path) -> None:
    target = tmp_path / "x.exe"
    target.write_bytes(b"x")
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: "signtool.exe")
    monkeypatch.setattr(sig_mod, "capture", _fake_capture(None, timed_out=True))
    assert sig_mod.check_signature(str(target)) == "unknown"


def test_returns_unknown_when_capture_raises_os_error(monkeypatch, tmp_path) -> None:
    target = tmp_path / "x.exe"
    target.write_bytes(b"x")
    monkeypatch.setattr(sig_mod.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sig_mod, "_locate_signtool", lambda: "signtool.exe")

    def _raise(argv, **kwargs):
        del argv, kwargs
        raise OSError("boom")

    monkeypatch.setattr(sig_mod, "capture", _raise)
    assert sig_mod.check_signature(str(target)) == "unknown"


_SIGNTOOL_AVAILABLE = sig_mod._locate_signtool() is not None


@pytest.mark.skipif(not _SIGNTOOL_AVAILABLE, reason="signtool.exe is not installed in this environment")
def test_real_signtool_against_a_real_system_binary() -> None:
    """A real Windows system binary should give signtool a definitive
    answer -- never 'unknown' when the tool itself ran successfully."""

    result = sig_mod.check_signature(sig_mod._locate_signtool())
    assert result in {"valid", "invalid", "unsigned"}


@pytest.mark.skipif(not _SIGNTOOL_AVAILABLE, reason="signtool.exe is not installed in this environment")
def test_real_signtool_against_a_genuinely_unsigned_binary(tmp_path) -> None:
    target = tmp_path / "definitely-unsigned.exe"
    target.write_bytes(os.urandom(4096))
    assert sig_mod.check_signature(str(target)) == "unsigned"
