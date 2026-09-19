"""Policy domain models: operations, risk, and explainable decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyOperation(StrEnum):
    GIT_RECOVERY_COMMIT = "GIT_RECOVERY_COMMIT"
    PROVIDER_REPO_READ = "PROVIDER_REPO_READ"
    PROVIDER_BRANCH_PUSH = "PROVIDER_BRANCH_PUSH"
    PROVIDER_PR_CREATE = "PROVIDER_PR_CREATE"
    PROVIDER_FORCE_PUSH = "PROVIDER_FORCE_PUSH"
    PROVIDER_SECRET_READ = "PROVIDER_SECRET_READ"
    ASSURANCE_RUN = "ASSURANCE_RUN"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PolicyDenialReason(StrEnum):
    AUTHORITY_DENIED = "AUTHORITY_DENIED"
    OPERATION_NOT_PERMITTED = "OPERATION_NOT_PERMITTED"
    PATH_FORBIDDEN = "PATH_FORBIDDEN"
    LIFECYCLE_STATE_INVALID = "LIFECYCLE_STATE_INVALID"
    RISK_TOO_HIGH = "RISK_TOO_HIGH"


class PolicyDecision(PolicyModel):
    allowed: bool
    risk: RiskLevel
    denial_reason: PolicyDenialReason | None = None
