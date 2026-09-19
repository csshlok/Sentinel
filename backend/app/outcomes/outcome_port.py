"""Adapts `OutcomeTracker` to the frozen `OutcomePort`.

`OutcomePort.refresh(change)` carries no actor/grant, but a GitHub call
always needs a resolved token. This class is constructed with a fixed
`read_grant_id` naming a previously issued, repo-read-scoped
`CredentialGrant`. Flagged for `[SD]` contract reconciliation:
`OutcomePort` may need an explicit actor/grant parameter, and
`ChangeView` has no GitHub repository slug (see
`backend.app.providers.repository_slug`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from backend.app.contracts.models import ChangeView, Outcome, OutcomeKind, OutcomeStatus
from backend.app.core.errors import AppError
from backend.app.credentials.broker import CredentialBroker
from backend.app.outcomes.tracker import OutcomeTracker
from backend.app.providers.repository_slug import resolve_github_repository_slug


class GitHubOutcomeTracker:
    """Implements `backend.app.contracts.ports.OutcomePort`."""

    def __init__(
        self,
        tracker: OutcomeTracker,
        broker: CredentialBroker,
        *,
        read_grant_id: UUID,
        required_check_names: list[str] | None = None,
    ) -> None:
        self.tracker = tracker
        self.broker = broker
        self.read_grant_id = read_grant_id
        self.required_check_names = required_check_names or []

    def refresh(self, change: ChangeView) -> list[Outcome]:
        observed_at = datetime.now(UTC)
        if change.git_summary is None:
            return []
        head_sha = change.git_summary.head_sha

        repository = resolve_github_repository_slug(change.repository_path)
        if repository is None:
            return [
                self._unavailable(change, head_sha, observed_at, "no GitHub remote configured")
            ]

        try:
            token = self.broker.resolve_secret(self.read_grant_id, scope="github.repo.read")
        except AppError:
            return [self._unavailable(change, head_sha, observed_at, "no valid read grant")]

        try:
            verification = self.tracker.verify_required_checks(
                token=token,
                repository=repository,
                expected_head_sha=head_sha,
                required_check_names=self.required_check_names,
            )
        except AppError as error:
            return [self._unavailable(change, head_sha, observed_at, error.code)]

        if not verification.checks:
            status = OutcomeStatus.PENDING
        elif not verification.evidence_complete:
            status = OutcomeStatus.PENDING
        elif verification.all_passed:
            status = OutcomeStatus.PASSED
        else:
            status = OutcomeStatus.FAILED

        return [
            Outcome(
                id=uuid4(),
                change_id=change.id,
                kind=OutcomeKind.CI,
                status=status,
                repository=repository,
                head_sha=head_sha,
                provider_reference=f"{repository}@{head_sha}",
                observed_at=observed_at,
                details={
                    "checks": {
                        check.name: check.conclusion.value
                        for check in verification.checks
                    },
                    "mismatched_sha_discarded": verification.mismatched_sha_discarded,
                },
            )
        ]

    @staticmethod
    def _unavailable(
        change: ChangeView, head_sha: str, observed_at: datetime, reason: str
    ) -> Outcome:
        return Outcome(
            id=uuid4(),
            change_id=change.id,
            kind=OutcomeKind.CI,
            status=OutcomeStatus.UNAVAILABLE,
            repository="",
            head_sha=head_sha,
            provider_reference="",
            observed_at=observed_at,
            details={"reason": reason},
        )
