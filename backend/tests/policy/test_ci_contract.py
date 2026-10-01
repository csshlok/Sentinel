"""The release workflow runs the default Python suite on every push."""

from __future__ import annotations

from pathlib import Path


def test_windows_ci_runs_default_suite_on_every_push() -> None:
    workflow = (Path(__file__).resolve().parents[3] / ".github/workflows/ci.yml")
    text = workflow.read_text(encoding="utf-8")
    assert "  push:" in text
    assert "runs-on: windows-latest" in text
    assert "python-version: ['3.12', '3.14']" in text
    assert "python-version: ${{ matrix.python-version }}" in text
    assert 'python -m pip install -e ".[test,tui]"' in text
    assert "run: python -m pytest -q" in text
