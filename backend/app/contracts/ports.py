"""Stable adapter protocols for parallel backend implementation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.app.contracts.models import (
    GitSummary,
    RepositoryInfo,
    VerificationRequest,
    VerificationResult,
)


@runtime_checkable
class GitInspectionPort(Protocol):
    def validate_repository(self, path: str) -> RepositoryInfo:
        """Validate a path and return its canonical committed Git repository."""

    def inspect(self, path: str, patch_limit_bytes: int) -> GitSummary:
        """Read the current Git working tree without mutating it."""


@runtime_checkable
class VerificationPort(Protocol):
    def run(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
    ) -> VerificationResult:
        """Run one bounded verification command in the repository root."""

