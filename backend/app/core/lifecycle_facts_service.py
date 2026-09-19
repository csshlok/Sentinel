"""Real `LifecycleFactsPort`: composes transition facts from wired evidence.

`repository_valid`/`contract_present` are structurally guaranteed once a
`ChangeView` exists (repository canonicalization and a `ChangeContract`
default both happen at Change-creation time), so they are always `True`
here rather than a fabricated default.

`authority_valid`, `pull_request_recorded`, `ci_passed_for_current_head`,
and the `recovery_*` facts are computed from the identity, provider
operation, outcome, and recovery evidence `[SD]` wired in
`backend.app.core.runtime_service`.

`required_assurance_passed`, `assurance_fresh`, `deviations_resolved` and
`required_evidence_complete` come from `[KB]`'s `EvidenceService.assurance_facts`
when a provider is injected: the repository is re-inspected, so any edit after the
plan makes them `False`. They are computed only for the `LOCALLY_VERIFIED` and
`REVIEW_READY` guards. `artifact_recorded`, `deployment_recorded` and
`observation_criteria_met` remain `False` (no real adapter exists), so
`ARTIFACT_BUILT`, `DEPLOYED`, `OBSERVING` and `STABLE` stay honestly unreachable
through the real API, per this product's "no safety theater" invariant.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime

from backend.app.assurance.service import AssuranceFacts
from backend.app.contracts.models import (
    ChangeView, LifecycleFacts, OutcomeKind, OutcomeStatus, RecoveryPlan, RecoveryStatus,
)
from backend.app.core.runtime_repositories import (
    OutcomeRepository,
    ProviderOperationRepository,
    RecoveryRepository,
)
from backend.app.identity.repository import DelegationRepository

_ASSURANCE_TARGETS = frozenset({"LOCALLY_VERIFIED", "REVIEW_READY"})

_UNRESOLVED_RECOVERY_STATUSES = frozenset(
    {
        RecoveryStatus.PLANNED,
        RecoveryStatus.APPROVED,
        RecoveryStatus.EXECUTING,
        RecoveryStatus.CONFLICTED,
    }
)


class RuntimeLifecycleFacts:
    """Implements `backend.app.contracts.ports.LifecycleFactsPort`."""

    def __init__(
        self,
        delegations: DelegationRepository,
        provider_operations: ProviderOperationRepository,
        outcomes: OutcomeRepository,
        recovery: RecoveryRepository,
        assurance_facts: Callable[[ChangeView], AssuranceFacts] | None = None,
    ) -> None:
        self.assurance_facts = assurance_facts
        self.delegations = delegations
        self.provider_operations = provider_operations
        self.outcomes = outcomes
        self.recovery = recovery

    def get_facts(self, change: ChangeView, target_state: str) -> LifecycleFacts:
        now = datetime.now(UTC)
        assurance = self._assurance(change, target_state)

        authority_valid = any(
            delegation.revoked_at is None and delegation.expires_at > now
            for delegation in self.delegations.list_for_change(change.id)
        )
        pull_request_recorded = self.provider_operations.has_succeeded_operation(
            change.id, "github.pr.create"
        )
        ci_passed_for_current_head = self._ci_passed(change)

        latest_plan = self.recovery.latest_for_change(change.id)
        recovery_plan_approved = (
            latest_plan is not None and latest_plan.approved_at is not None
        )
        recovery_verified = self._recovery_verified(change, latest_plan)
        recovery_conflict = (
            latest_plan is not None and latest_plan.status is RecoveryStatus.CONFLICTED
        )
        recovery_failed = (
            latest_plan is not None
            and latest_plan.status is RecoveryStatus.RECOVERY_FAILED
        )
        unresolved_recovery_actions = (
            latest_plan is not None
            and latest_plan.status in _UNRESOLVED_RECOVERY_STATUSES
        )

        return LifecycleFacts(
            repository_valid=True,
            contract_present=True,
            authority_valid=authority_valid,
            pull_request_recorded=pull_request_recorded,
            ci_passed_for_current_head=ci_passed_for_current_head,
            recovery_plan_approved=recovery_plan_approved,
            recovery_verified=recovery_verified,
            recovery_conflict=recovery_conflict,
            recovery_failed=recovery_failed,
            unresolved_recovery_actions=unresolved_recovery_actions,
            required_assurance_passed=assurance.required_assurance_passed,
            assurance_fresh=assurance.assurance_fresh,
            deviations_resolved=assurance.deviations_resolved,
            required_evidence_complete=assurance.required_evidence_complete,
        )

    def _assurance(self, change: ChangeView, target_state: str) -> AssuranceFacts:
        """The four `[KB]` facts, computed only for the guards that read them.

        Each computation re-inspects the repository to prove freshness, so it is
        skipped for every other transition. Without a provider, or when evidence
        is missing, stale or failing, all four stay `False`.
        """

        if self.assurance_facts is None or str(target_state) not in _ASSURANCE_TARGETS:
            return AssuranceFacts()
        return self.assurance_facts(change)

    def _recovery_verified(
        self, change: ChangeView, latest_plan: RecoveryPlan | None
    ) -> bool:
        """True only if the repository's *actual* dedicated recovery branch

        currently points at the SHA the plan claims to have produced --
        trusting the persisted `RecoveryPlan.status` field alone would make
        "verified" mean nothing more than "the plan record says so", the
        exact kind of self-report this product's other facts deliberately
        avoid (`_ci_passed`, `pull_request_recorded`). Independently
        re-reads the real Git ref rather than caching the SHA recovery
        already returned at execute() time, so a branch that was since
        force-moved, deleted, or never actually reached that commit is
        correctly reported unverified.
        """

        if latest_plan is None or latest_plan.status is not RecoveryStatus.RECOVERED:
            return False
        if not latest_plan.actions:
            # RECOVERED with no actions means the repository was already at
            # baseline -- nothing needed reverting, so there is no revert
            # commit to cross-check and the claim is trivially true.
            return True
        for action in latest_plan.actions:
            reference = action.provider_reference
            if not reference or not reference.startswith("branch:") or "@" not in reference:
                continue
            branch, _, expected_sha = reference.removeprefix("branch:").rpartition("@")
            if not branch or not expected_sha:
                continue
            actual_sha = self._branch_head_sha(change.repository_path, branch)
            return actual_sha is not None and actual_sha.lower() == expected_sha.lower()
        return False

    @staticmethod
    def _branch_head_sha(repository_path: str, branch: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", repository_path, "rev-parse", "--verify", f"refs/heads/{branch}"],
            capture_output=True, shell=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace").strip()

    def _ci_passed(self, change: ChangeView) -> bool:
        """True iff the *latest* CI outcome for the current HEAD passed.

        ``list_for_change`` returns outcomes newest-first, so the first CI
        outcome matching the current SHA is the most recent one for it. Using
        ``any(...)`` over every matching outcome (the prior implementation)
        let an old PASSED result outlive a newer FAILED re-run of the same
        commit -- once any CI run for a SHA ever passed, the gate stayed open
        forever for that SHA regardless of later evidence.
        """

        if change.git_summary is None:
            return False
        head_sha = change.git_summary.head_sha
        for outcome in self.outcomes.list_for_change(change.id):
            if outcome.kind is OutcomeKind.CI and outcome.head_sha == head_sha:
                return outcome.status is OutcomeStatus.PASSED
        return False
