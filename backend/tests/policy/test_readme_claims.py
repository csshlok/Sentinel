"""README boundary claims track the runtime profile declarations."""

from __future__ import annotations

from pathlib import Path

from backend.app.execution.agent_profiles import BUILTIN_PROFILES, BoundaryKind


def test_readme_names_each_builtin_boundary_and_pending_gate() -> None:
    root = Path(__file__).resolve().parents[3]
    readme = (root / "README.md").read_text(encoding="utf-8")
    expected = {"claude": BoundaryKind.APPCONTAINER,
                "generic": BoundaryKind.RESTRICTED_TOKEN,
                "codex": BoundaryKind.UNAVAILABLE}
    for name, boundary in expected.items():
        assert BUILTIN_PROFILES[name].boundary is boundary
        assert f"`{name}`" in readme
    assert "execution_boundary: UNKNOWN" in readme
    assert "lifecycle transition gate is still pending" in readme
    assert "no filesystem or network isolation" in readme
    assert "No license has been selected" in readme
    assert "1,022" not in readme and "66 operations" not in readme
