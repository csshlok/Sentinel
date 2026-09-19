"""Explicit placeholders used until parallel adapters are handed off."""

from backend.app.contracts.models import (
    ChangeView,
    GitSummary,
    LifecycleFacts,
    RepositoryInfo,
    VerificationRequest,
    VerificationResult,
)
from backend.app.core.errors import adapter_unavailable


class UnavailableGitInspection:
    def validate_repository(self, path: str) -> RepositoryInfo:
        raise adapter_unavailable("Git inspection")

    def inspect(self, path: str, patch_limit_bytes: int) -> GitSummary:
        raise adapter_unavailable("Git inspection")


class UnavailableVerification:
    def run(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
    ) -> VerificationResult:
        raise adapter_unavailable("verification")


class UnavailableLifecycleFacts:
    def get_facts(self, change: ChangeView, target_state: str) -> LifecycleFacts:
        raise adapter_unavailable("lifecycle evidence composition")
