"""Contract-conforming fakes used only by CORE unit tests."""

from backend.app.contracts.models import (
    GitSummary,
    RepositoryInfo,
    VerificationRequest,
    VerificationResult,
)


class FakeGitInspection:
    def __init__(self, info: RepositoryInfo, summary: GitSummary | None = None) -> None:
        self.info = info
        self.summary = summary
        self.validated_paths: list[str] = []

    def validate_repository(self, path: str) -> RepositoryInfo:
        self.validated_paths.append(path)
        return self.info

    def inspect(self, path: str, patch_limit_bytes: int) -> GitSummary:
        if self.summary is None:
            raise AssertionError("No Git summary configured for fake")
        return self.summary


class FakeVerification:
    def __init__(self, result: VerificationResult | None = None) -> None:
        self.result = result

    def run(
        self,
        repository_path: str,
        request: VerificationRequest,
        output_limit_bytes: int,
    ) -> VerificationResult:
        if self.result is None:
            raise AssertionError("No verification result configured for fake")
        return self.result

