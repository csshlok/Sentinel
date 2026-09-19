"""Owner-local result models for assurance and deviation analysis.

These do not extend the frozen shared contracts: they are derived views a
composition layer can serialize or map onto ``LifecycleFacts``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from backend.app.contracts.models import (
    AssuranceStatus, ContractModel, EvidenceStatus, ShortText,
)


class DeviationCategory(StrEnum):
    FORBIDDEN_PATH = "FORBIDDEN_PATH"
    OUTSIDE_ALLOWED_PATHS = "OUTSIDE_ALLOWED_PATHS"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    RISK_ABOVE_CEILING = "RISK_ABOVE_CEILING"
    RISK_NOT_ASSESSED = "RISK_NOT_ASSESSED"
    DEPENDENCY_CHANGE = "DEPENDENCY_CHANGE"
    DEPENDENCY_EVIDENCE_GAP = "DEPENDENCY_EVIDENCE_GAP"
    ENVIRONMENT_DRIFT = "ENVIRONMENT_DRIFT"


class DeviationSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class DeviationFinding(ContractModel):
    category: DeviationCategory
    severity: DeviationSeverity
    subject: Annotated[str, StringConstraints(max_length=1024)]
    detail: Annotated[str, StringConstraints(max_length=1000)]


class CheckResult(ContractModel):
    check_id: ShortText
    required: bool
    status: AssuranceStatus
    exit_code: int | None = None
    summary: Annotated[str, StringConstraints(max_length=300)] = ""


class AssuranceEvaluation(ContractModel):
    """Freshness-aware decision inputs for one plan and its runs."""

    plan_id: UUID
    checkpoint_id: UUID
    status: EvidenceStatus
    fresh: bool
    freshness_reasons: list[str] = Field(default_factory=list, max_length=32)
    results: list[CheckResult] = Field(default_factory=list, max_length=256)
    missing_required: list[str] = Field(default_factory=list, max_length=256)
    failed: list[str] = Field(default_factory=list, max_length=256)
    coverage_gaps: list[str] = Field(default_factory=list, max_length=512)
    deviations: list[DeviationFinding] = Field(default_factory=list, max_length=10000)
    required_assurance_passed: bool
    assurance_fresh: bool
    deviations_resolved: bool
    required_evidence_complete: bool
