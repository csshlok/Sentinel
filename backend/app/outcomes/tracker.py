"""Outcome verification: CI for one SHA must never verify another SHA."""

from __future__ import annotations

from collections.abc import Sequence

from backend.app.providers.github import GitHubProvider
from backend.app.providers.models import CheckConclusion, RequiredChecksVerification


class OutcomeTracker:
    def __init__(self, provider: GitHubProvider) -> None:
        self.provider = provider

    def verify_required_checks(
        self,
        *,
        token: str,
        repository: str,
        expected_head_sha: str,
        required_check_names: Sequence[str],
    ) -> RequiredChecksVerification:
        raw = self.provider.list_check_runs_for_sha(
            token=token, repository=repository, head_sha=expected_head_sha
        )

        # Defense in depth: discard any record whose head_sha does not
        # match the requested SHA, even though the API is already
        # SHA-scoped. A provider bug or stale cache must not let CI for
        # one commit verify a different one.
        matching = [check for check in raw if check.head_sha == expected_head_sha]
        mismatched_count = len(raw) - len(matching)

        found_names = {check.name for check in matching}
        missing_required = [
            name for name in required_check_names if name not in found_names
        ]
        required_matching = [
            check for check in matching if check.name in required_check_names
        ]
        all_passed = not missing_required and all(
            check.conclusion is CheckConclusion.SUCCESS for check in required_matching
        )

        return RequiredChecksVerification(
            head_sha=expected_head_sha,
            checks=matching,
            all_passed=all_passed,
            evidence_complete=not missing_required,
            mismatched_sha_discarded=mismatched_count,
        )
