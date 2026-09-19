"""Normalized GitHub outcome models, bound to an exact commit SHA."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]


class ProvidersModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PullRequestState(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


class CheckConclusion(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    NEUTRAL = "NEUTRAL"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    STALE = "STALE"
    PENDING = "PENDING"


class PullRequestOutcome(ProvidersModel):
    repository: str
    branch: str
    number: int
    url: str
    head_sha: Sha
    state: PullRequestState
    observed_at: AwareDatetime


class CheckRunOutcome(ProvidersModel):
    name: str
    conclusion: CheckConclusion
    head_sha: Sha
    observed_at: AwareDatetime


class RequiredChecksVerification(ProvidersModel):
    head_sha: Sha
    checks: list[CheckRunOutcome]
    all_passed: bool
    evidence_complete: bool
    mismatched_sha_discarded: int = Field(default=0, ge=0)
