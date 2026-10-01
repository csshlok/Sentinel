"""Deterministic, default-deny policy presets for signed Change evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Literal

PresetName = Literal["strict", "standard", "docs-only"]
ChangeType = Literal["code", "docs", "release"]
PRESET_VERSION = "1.3.0"


@dataclass(frozen=True, slots=True)
class PresetRule:
    minimum_coverage: int | None
    passing_checks: bool = True
    current_freshness: bool = True
    confined_checks: bool = False
    appcontainer_boundary: bool = False
    docs_paths_only: bool = False


_RULES: dict[tuple[str, str], PresetRule] = {
    ("strict", "code"): PresetRule(100, confined_checks=True, appcontainer_boundary=True),
    ("strict", "release"): PresetRule(100, confined_checks=True, appcontainer_boundary=True),
    ("strict", "docs"): PresetRule(None, confined_checks=True,
                                   appcontainer_boundary=True, docs_paths_only=True),
    ("standard", "code"): PresetRule(80),
    ("standard", "release"): PresetRule(90, confined_checks=True),
    ("standard", "docs"): PresetRule(None, docs_paths_only=True),
    ("docs-only", "docs"): PresetRule(None, docs_paths_only=True),
}


@dataclass(frozen=True, slots=True)
class PresetEvidence:
    checks_passed: bool | None = None
    diff_exercised: str = "UNKNOWN"
    measured_percent: float | None = None
    freshness: str = "UNKNOWN"
    confined_checks: str = "UNKNOWN"
    execution_boundary: str = "UNKNOWN"
    changed_paths: tuple[str, ...] = ()
    path_evidence_error: str | None = None
    deleted_paths: tuple[str, ...] = ()
    mode_changed_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PresetDecision:
    preset_name: str
    preset_version: str
    change_type: str
    status: Literal["ALLOW", "DENY"]
    reasons: tuple[str, ...]


def _docs_path(path: str) -> bool:
    if (not path or "\\" in path or ":" in path or path.startswith("/")
            or "//" in path):
        return False
    parsed = PurePosixPath(path)
    if ".." in parsed.parts or "." in parsed.parts:
        return False
    parts = tuple(part.casefold() for part in parsed.parts)
    name = parts[-1]
    if (name in {"claude.md", "agents.md", "copilot-instructions.md"}
            or ".claude" in parts):
        return False
    if (name.startswith(("requirements", "constraints", "pipfile"))
            or name in {"cmakelists.txt", "pyproject.toml", "poetry.lock", "uv.lock",
                        "pdm.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
            or name.startswith("setup.") or name.endswith((".lock", ".in"))):
        return False
    if name.startswith(("readme", "changelog", "contributing", "authors", "notice", "license")):
        return parsed.suffix.casefold() in {"", ".md", ".rst", ".txt", ".markdown", ".adoc"}
    return parsed.suffix.casefold() in {".md", ".rst"} or (
        parsed.suffix.casefold() == ".txt" and parts[0] in {"docs", "doc"})


def evaluate_preset(*, preset_name: str, change_type: str,
                    evidence: PresetEvidence) -> PresetDecision:
    """Return stable denial reasons; absent or unmeasured required facts deny."""
    rule = _RULES.get((preset_name, change_type))
    if rule is None:
        return PresetDecision(preset_name, PRESET_VERSION, change_type, "DENY",
                              ("preset/change type combination is not permitted",))
    reasons: list[str] = []
    if rule.docs_paths_only and evidence.path_evidence_error:
        reasons.append(f"documentation path evidence unavailable: {evidence.path_evidence_error}")
    if rule.docs_paths_only and (not evidence.changed_paths or
                                 any(not _docs_path(path) for path in evidence.changed_paths)):
        reasons.append("docs-only paths are missing or include non-documentation files")
    if rule.docs_paths_only and evidence.mode_changed_paths:
        reasons.append("documentation path mode changed: " + ", ".join(evidence.mode_changed_paths[:8]))
    if rule.passing_checks and evidence.checks_passed is not True:
        reasons.append("passing checks are required; result is FAIL or UNKNOWN")
    if rule.current_freshness and evidence.freshness != "CURRENT":
        reasons.append(f"current freshness is required; result is {evidence.freshness}")
    if rule.minimum_coverage is not None:
        if evidence.diff_exercised != "PASS":
            reasons.append("diff coverage must be PASS")
        try:
            measured = (Decimal(str(evidence.measured_percent))
                        if evidence.measured_percent is not None else None)
        except (InvalidOperation, ValueError):
            measured = None
        if (measured is None or not measured.is_finite() or measured < rule.minimum_coverage
                or measured > 100):
            reasons.append(f"diff coverage must measure at least {rule.minimum_coverage}%")
    if rule.confined_checks and evidence.confined_checks != "PASS":
        reasons.append("confined checks must be PASS")
    if rule.appcontainer_boundary and evidence.execution_boundary != "APPCONTAINER":
        reasons.append("observed AppContainer boundary is required")
    return PresetDecision(preset_name, PRESET_VERSION, change_type,
                          "DENY" if reasons else "ALLOW", tuple(reasons))
