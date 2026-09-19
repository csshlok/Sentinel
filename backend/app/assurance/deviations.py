"""Deterministic Change Contract deviation analysis.

Path patterns are relative to the repository root using ``/``:

* ``**`` matches any number of directories, ``*`` and ``?`` stay within one path
  segment.
* A pattern ending in ``/`` or naming a directory prefix covers everything under it.
* A pattern with no ``/`` matches that name at any depth (gitignore style).
* Matching is case-insensitive because the supported platform's file system is.
"""

from __future__ import annotations

import re
from functools import lru_cache

from backend.app.contracts.models import (
    ChangeView, DependencyReport, EnvironmentDrift, GitCheckpoint, RiskLevel,
)
from backend.app.assurance.models import (
    DeviationCategory as C, DeviationFinding, DeviationSeverity as S,
)

_RANK = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4}
_SEVERITY_ORDER = {S.BLOCKING: 0, S.WARNING: 1, S.INFO: 2}


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    normalized = pattern.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    anywhere = "/" not in normalized.rstrip("/")
    if normalized.endswith("/"):
        normalized += "**"
    parts = normalized.split("/")
    out: list[str] = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
            continue
        segment = "".join(
            "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch) for ch in part
        )
        out.append(segment + ("" if last else "/"))
    body = "".join(out)
    if anywhere:
        body = "(?:.*/)?" + body
    # A bare directory prefix also covers everything below it.
    return re.compile(rf"^{body}(?:/.*)?$", re.IGNORECASE | re.DOTALL)


def matches(path: str, pattern: str) -> bool:
    return _compile(pattern).match(path.replace("\\", "/")) is not None


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(matches(path, pattern) for pattern in patterns)


def _mentioned(text_items: list[str], needle: str) -> bool:
    lowered = needle.lower()
    return any(lowered in item.lower() for item in text_items)


def analyze_deviations(
    change: ChangeView,
    checkpoint: GitCheckpoint,
    dependencies: DependencyReport | None = None,
    environment_drift: EnvironmentDrift | None = None,
) -> list[DeviationFinding]:
    """Compare observed evidence with the Change Contract.

    Findings describe differences only. They never attribute a difference to an
    actor, process or command.
    """

    contract = change.contract
    findings: list[DeviationFinding] = []

    def add(category: C, severity: S, subject: str, detail: str) -> None:
        findings.append(DeviationFinding(
            category=category, severity=severity, subject=subject[:1024], detail=detail))

    for entry in checkpoint.summary.files:
        touched = [entry.path] + ([entry.old_path] if entry.old_path else [])
        for path in touched:
            if matches_any(path, contract.forbidden_paths):
                add(C.FORBIDDEN_PATH, S.BLOCKING, path, "The path matches a forbidden pattern.")
            if not matches_any(path, contract.allowed_paths):
                add(C.OUTSIDE_ALLOWED_PATHS, S.BLOCKING, path,
                    "The path is not covered by any allowed pattern.")
        if entry.status.value == "CONFLICTED":
            add(C.MERGE_CONFLICT, S.BLOCKING, entry.path, "The path has an unresolved merge conflict.")

    if change.risk_level is RiskLevel.UNKNOWN:
        add(C.RISK_NOT_ASSESSED, S.WARNING, "risk", "No risk level has been assessed for this Change.")
    elif _RANK.get(change.risk_level, 0) > _RANK.get(contract.max_risk, 0):
        add(C.RISK_ABOVE_CEILING, S.BLOCKING, change.risk_level.value,
            f"Assessed risk exceeds the contract ceiling {contract.max_risk.value}.")

    if dependencies is not None:
        for dep in dependencies.changes:
            label = f"{dep.ecosystem}:{dep.package}"
            expected = _mentioned(contract.expected_outcomes, dep.package)
            add(C.DEPENDENCY_CHANGE, S.INFO if expected else S.WARNING, label,
                ("Dependency change is named in the contract's expected outcomes."
                 if expected else "Dependency change is not named in the contract's expected outcomes.")
                + f" Source: {dep.source_path}.")
        for item in dependencies.unsupported_ecosystems:
            add(C.DEPENDENCY_EVIDENCE_GAP, S.WARNING, item,
                "Dependency evidence for this source is unsupported or incomplete.")

    if environment_drift is not None:
        for group, facts in (("added", environment_drift.added),
                             ("removed", environment_drift.removed),
                             ("changed", environment_drift.changed)):
            for fact in facts:
                expected = _mentioned(contract.expected_outcomes, fact.key)
                add(C.ENVIRONMENT_DRIFT, S.INFO if expected else S.WARNING, fact.key,
                    f"Environment fact {group} between passports; cause is not attributed.")
        for fact in environment_drift.unknown:
            add(C.ENVIRONMENT_DRIFT, S.WARNING, fact.key,
                "Environment fact could not be compared (partial or unsupported evidence).")

    unique = {(f.category, f.severity, f.subject, f.detail): f for f in findings}
    return sorted(unique.values(), key=lambda f: (
        _SEVERITY_ORDER[f.severity], f.category.value, f.subject, f.detail))
