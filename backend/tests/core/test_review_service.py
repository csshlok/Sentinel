from datetime import UTC, datetime

import pytest

from backend.app.contracts.models import (
    ChangedPath,
    ChangedPathStatus,
    GitSummary,
    PathCategory,
    ReviewState,
    VerificationResult,
    VerificationStatus,
)
from backend.app.core.review_service import determine_review_state


def make_summary(*, clean: bool) -> GitSummary:
    files = []
    if not clean:
        files = [
            ChangedPath(
                path="src/app.py",
                status=ChangedPathStatus.MODIFIED,
                staged=False,
                unstaged=True,
                additions=1,
                deletions=0,
                category=PathCategory.SOURCE,
            )
        ]
    return GitSummary(
        repository_root="C:\\work\\repo",
        branch="main",
        head_sha="a" * 40,
        is_clean=clean,
        files=files,
        total_additions=0 if clean else 1,
        total_deletions=0,
        patch="",
        refreshed_at=datetime.now(UTC),
    )


def make_verification(status: VerificationStatus) -> VerificationResult:
    now = datetime.now(UTC)
    return VerificationResult(
        executable="pytest",
        args=[],
        status=status,
        exit_code=0 if status is VerificationStatus.PASSED else 1,
        duration_ms=10,
        stdout="",
        stderr="",
        started_at=now,
        completed_at=now,
    )


@pytest.mark.parametrize(
    ("summary", "verification", "expected"),
    [
        (None, None, ReviewState.NO_CHANGES),
        (make_summary(clean=True), None, ReviewState.NO_CHANGES),
        (make_summary(clean=False), None, ReviewState.MISSING_EVIDENCE),
        (
            make_summary(clean=False),
            make_verification(VerificationStatus.FAILED),
            ReviewState.FAILED_VERIFICATION,
        ),
        (
            make_summary(clean=False),
            make_verification(VerificationStatus.PASSED),
            ReviewState.READY_FOR_HUMAN_REVIEW,
        ),
    ],
)
def test_review_state_precedence(
    summary: GitSummary | None,
    verification: VerificationResult | None,
    expected: ReviewState,
) -> None:
    assert determine_review_state(summary, verification) is expected

