"""Versioned request and response models shared across backend modules."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


TrimmedTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
TrimmedIntent = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
RepositoryPath = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32767)
]
ExecutableName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
CommandArgument = Annotated[str, StringConstraints(max_length=2048)]


class ContractModel(BaseModel):
    """Strict base class for public API contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ChangedPathStatus(StrEnum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    RENAMED = "RENAMED"
    COPIED = "COPIED"
    UNTRACKED = "UNTRACKED"
    CONFLICTED = "CONFLICTED"


class PathCategory(StrEnum):
    SOURCE = "SOURCE"
    TEST = "TEST"
    DEPENDENCY = "DEPENDENCY"
    CONFIG = "CONFIG"
    DOCUMENTATION = "DOCUMENTATION"
    OTHER = "OTHER"


class VerificationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    ERROR = "ERROR"


class ReviewState(StrEnum):
    NO_CHANGES = "NO_CHANGES"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    FAILED_VERIFICATION = "FAILED_VERIFICATION"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


class RepositoryPathRequest(ContractModel):
    path: RepositoryPath


class RepositoryInfo(ContractModel):
    root: RepositoryPath
    branch: str | None = Field(default=None, max_length=1024)
    head_sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]


class ChangedPath(ContractModel):
    path: Annotated[str, StringConstraints(min_length=1, max_length=32767)]
    old_path: Annotated[str, StringConstraints(min_length=1, max_length=32767)] | None = None
    status: ChangedPathStatus
    staged: bool
    unstaged: bool
    additions: int | None = Field(default=None, ge=0)
    deletions: int | None = Field(default=None, ge=0)
    category: PathCategory
    binary: bool = False


class GitSummary(ContractModel):
    repository_root: RepositoryPath
    branch: str | None = Field(default=None, max_length=1024)
    head_sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$")]
    is_clean: bool
    files: list[ChangedPath] = Field(default_factory=list)
    total_additions: int = Field(ge=0)
    total_deletions: int = Field(ge=0)
    patch: str
    patch_truncated: bool = False
    untracked_patch_omitted: bool = False
    refreshed_at: AwareDatetime


class VerificationRequest(ContractModel):
    executable: ExecutableName
    args: list[CommandArgument] = Field(default_factory=list, max_length=64)
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class VerificationResult(ContractModel):
    executable: ExecutableName
    args: list[CommandArgument] = Field(default_factory=list, max_length=64)
    status: VerificationStatus
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout: str
    stderr: str
    output_truncated: bool = False
    started_at: AwareDatetime
    completed_at: AwareDatetime


class ChangeCreateRequest(ContractModel):
    title: TrimmedTitle
    intent: TrimmedIntent
    repository_path: RepositoryPath


class ChangeView(ContractModel):
    id: UUID
    title: str
    intent: str
    repository_path: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    last_refreshed_at: AwareDatetime | None = None
    git_summary: GitSummary | None = None
    verification: VerificationResult | None = None
    review_state: ReviewState


class ChangeListResponse(ContractModel):
    items: list[ChangeView]
    count: int = Field(ge=0)


class HealthResponse(ContractModel):
    status: str
    api_version: str


class ErrorDetail(ContractModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(ContractModel):
    error: ErrorDetail


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp without hiding the time source in models."""

    from datetime import UTC

    return datetime.now(UTC)

