"""Pure review-state composition from currently available evidence."""

from backend.app.contracts.models import (
    GitSummary,
    ReviewState,
    VerificationResult,
    VerificationStatus,
)


def determine_review_state(
    git_summary: GitSummary | None,
    verification: VerificationResult | None,
) -> ReviewState:
    if git_summary is None or git_summary.is_clean or not git_summary.files:
        return ReviewState.NO_CHANGES
    if verification is None:
        return ReviewState.MISSING_EVIDENCE
    if verification.status is not VerificationStatus.PASSED:
        return ReviewState.FAILED_VERIFICATION
    return ReviewState.READY_FOR_HUMAN_REVIEW

