"""README claims track the runtime profile declarations and the frozen contract."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.execution.agent_profiles import BUILTIN_PROFILES, BoundaryKind

_ROOT = Path(__file__).resolve().parents[3]


def _readme() -> str:
    return (_ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_boundary_claims_match_the_builtin_profiles() -> None:
    readme = _readme()
    assert BUILTIN_PROFILES["claude"].boundary is BoundaryKind.APPCONTAINER
    assert "Launch Claude Code inside a Windows AppContainer" in readme
    assert BUILTIN_PROFILES["generic"].boundary is BoundaryKind.RESTRICTED_TOKEN
    assert "restricted access token" in readme
    # Codex (spike 008) and the bring-your-own `boxed` adapter run only in the AppContainer.
    assert BUILTIN_PROFILES["codex"].boundary is BoundaryKind.APPCONTAINER
    assert BUILTIN_PROFILES["boxed"].boundary is BoundaryKind.APPCONTAINER
    assert "Launch Codex, or any native agent CLI, in the same box" in readme
    assert "never retried unconfined" in " ".join(readme.split())


def test_readme_contract_counts_match_openapi() -> None:
    spec = json.loads((_ROOT / "openapi.json").read_text(encoding="utf-8"))
    operations = sum(1 for item in spec["paths"].values() for method in item
                     if method in {"get", "post", "put", "patch", "delete"})
    readme = " ".join(_readme().split())
    assert (f"{operations} operations across {len(spec['paths'])} routes, described by "
            f"{len(spec['components']['schemas'])} typed schemas") in readme
    assert "1,022" not in readme and "66 operations" not in readme
