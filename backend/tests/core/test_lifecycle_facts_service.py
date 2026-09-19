"""Unit coverage for `RuntimeLifecycleFacts`, the real `LifecycleFactsPort`.

Each fact is exercised directly against the shared-schema repositories it
reads, independent of the HTTP layer — complementing the end-to-end
lifecycle-transition coverage in
`backend/tests/acceptance/test_runtime_routes.py`.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.contracts.models import (
    ChangeContract,
    ChangeLifecycleState,
    ChangeView,
    Delegation,
    GitSummary,
    Outcome,
    OutcomeKind,
    OutcomeStatus,
    ProviderOperation,
    ProviderOperationRequest,
    ProviderOperationStatus,
    RecoveryAction,
    RecoveryPlan,
    RecoveryStatus,
    ReviewState,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.lifecycle_facts_service import RuntimeLifecycleFacts
from backend.app.core.runtime_repositories import (
    OutcomeRepository,
    ProviderOperationRepository,
    RecoveryRepository,
)
from backend.app.identity.repository import DelegationRepository


def _build(tmp_path):
    """Wires a real `Database` plus every repository `RuntimeLifecycleFacts`
    reads, and seeds one real `changes` row (returned as a `ChangeView`) so
    the shared-schema foreign keys on `delegations`/`provider_operations`/
    `outcomes`/`recovery_plans` are satisfiable, exactly like a real Change
    would be."""

    database = Database(tmp_path / "facts.sqlite3")
    database.initialize()
    delegations = DelegationRepository(database)
    provider_operations = ProviderOperationRepository(database)
    outcomes = OutcomeRepository(database)
    recovery = RecoveryRepository(database)
    facts_port = RuntimeLifecycleFacts(delegations, provider_operations, outcomes, recovery)

    now = datetime.now(UTC)
    change_id = uuid4()
    ChangeRepository(database).create(
        StoredChange(
            id=change_id,
            title="Fact composition",
            intent="Exercise RuntimeLifecycleFacts",
            repository_path="C:\\repo",
            created_at=now,
            updated_at=now,
            last_refreshed_at=None,
            git_summary=None,
            verification=None,
        )
    )
    change = ChangeView(
        id=change_id,
        title="Fact composition",
        intent="Exercise RuntimeLifecycleFacts",
        repository_path="C:\\repo",
        created_at=now,
        updated_at=now,
        git_summary=None,
        verification=None,
        review_state=ReviewState.NO_CHANGES,
        lifecycle_state=ChangeLifecycleState.ACTIVE,
        contract=ChangeContract(),
    )

    return facts_port, delegations, provider_operations, outcomes, recovery, change


def _with_head_sha(change: ChangeView, head_sha: str) -> ChangeView:
    return change.model_copy(
        update={
            "git_summary": GitSummary(
                repository_root=change.repository_path,
                branch="main",
                head_sha=head_sha,
                is_clean=True,
                total_additions=0,
                total_deletions=0,
                patch="",
                refreshed_at=datetime.now(UTC),
            )
        }
    )


def test_facts_default_false_except_structural_guarantees(tmp_path) -> None:
    facts_port, *_rest, change = _build(tmp_path)

    facts = facts_port.get_facts(change, "ACTIVE")

    assert facts.repository_valid is True
    assert facts.contract_present is True
    assert facts.authority_valid is False
    assert facts.pull_request_recorded is False
    assert facts.ci_passed_for_current_head is False
    assert facts.recovery_plan_approved is False
    # `[KB]`'s stream does not exist yet; these must stay honestly false.
    assert facts.required_assurance_passed is False
    assert facts.assurance_fresh is False
    assert facts.deviations_resolved is False
    assert facts.artifact_recorded is False
    assert facts.deployment_recorded is False
    assert facts.observation_criteria_met is False


def test_authority_valid_reflects_non_revoked_unexpired_delegation(tmp_path) -> None:
    facts_port, delegations, _provider_operations, _outcomes, _recovery, change = _build(
        tmp_path
    )
    now = datetime.now(UTC)

    assert facts_port.get_facts(change, "ACTIVE").authority_valid is False

    active = delegations.create(
        Delegation(
            id=uuid4(),
            grantor_id=uuid4(),
            grantee_id=uuid4(),
            change_id=change.id,
            repository_path=change.repository_path,
            scopes=["github.pr.create"],
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    assert facts_port.get_facts(change, "ACTIVE").authority_valid is True

    delegations.revoke(active.id, now)
    assert facts_port.get_facts(change, "ACTIVE").authority_valid is False

    delegations.create(
        Delegation(
            id=uuid4(),
            grantor_id=uuid4(),
            grantee_id=uuid4(),
            change_id=change.id,
            repository_path=change.repository_path,
            scopes=["github.pr.create"],
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    assert facts_port.get_facts(change, "ACTIVE").authority_valid is False


def test_pull_request_recorded_requires_a_succeeded_pr_create_operation(tmp_path) -> None:
    facts_port, _delegations, provider_operations, _outcomes, _recovery, change = _build(
        tmp_path
    )
    now = datetime.now(UTC)

    assert facts_port.get_facts(change, "PR_OPEN").pull_request_recorded is False

    failed = ProviderOperation(
        id=uuid4(),
        request=ProviderOperationRequest(
            provider="github",
            operation="github.pr.create",
            change_id=change.id,
            actor_id=uuid4(),
            idempotency_key="attempt-1",
        ),
        status=ProviderOperationStatus.FAILED,
        started_at=now,
        completed_at=now,
    )
    provider_operations.create(failed)
    assert facts_port.get_facts(change, "PR_OPEN").pull_request_recorded is False

    succeeded = ProviderOperation(
        id=uuid4(),
        request=ProviderOperationRequest(
            provider="github",
            operation="github.pr.create",
            change_id=change.id,
            actor_id=uuid4(),
            idempotency_key="attempt-2",
        ),
        status=ProviderOperationStatus.SUCCEEDED,
        started_at=now,
        completed_at=now,
    )
    provider_operations.create(succeeded)
    assert facts_port.get_facts(change, "PR_OPEN").pull_request_recorded is True


def test_ci_passed_only_for_the_current_head_sha(tmp_path) -> None:
    facts_port, _delegations, _provider_operations, outcomes, _recovery, base_change = _build(
        tmp_path
    )
    current_sha = "a" * 40
    stale_sha = "b" * 40
    change = _with_head_sha(base_change, current_sha)
    now = datetime.now(UTC)

    assert facts_port.get_facts(change, "CI_VERIFIED").ci_passed_for_current_head is False

    outcomes.create(
        Outcome(
            id=uuid4(),
            change_id=change.id,
            kind=OutcomeKind.CI,
            status=OutcomeStatus.PASSED,
            repository="acme/widgets",
            head_sha=stale_sha,
            provider_reference="acme/widgets@" + stale_sha,
            observed_at=now,
        )
    )
    assert facts_port.get_facts(change, "CI_VERIFIED").ci_passed_for_current_head is False

    outcomes.create(
        Outcome(
            id=uuid4(),
            change_id=change.id,
            kind=OutcomeKind.CI,
            status=OutcomeStatus.PASSED,
            repository="acme/widgets",
            head_sha=current_sha,
            provider_reference="acme/widgets@" + current_sha,
            observed_at=now,
        )
    )
    assert facts_port.get_facts(change, "CI_VERIFIED").ci_passed_for_current_head is True


def test_a_newer_ci_failure_overrides_an_older_pass_for_the_same_sha(tmp_path) -> None:
    """Reproduces the audit finding: a stale PASSED outcome for the current

    SHA must not keep the gate open once a newer run for that same SHA
    failed. ``any(...)`` over every matching outcome treated the gate as
    permanently open the instant any CI run for a SHA ever passed; only the
    *latest* outcome for the SHA should govern.
    """

    facts_port, _delegations, _provider_operations, outcomes, _recovery, base_change = _build(
        tmp_path
    )
    current_sha = "a" * 40
    change = _with_head_sha(base_change, current_sha)
    older = datetime.now(UTC) - timedelta(minutes=10)
    newer = datetime.now(UTC)

    outcomes.create(
        Outcome(
            id=uuid4(), change_id=change.id, kind=OutcomeKind.CI, status=OutcomeStatus.PASSED,
            repository="acme/widgets", head_sha=current_sha,
            provider_reference="acme/widgets@" + current_sha, observed_at=older,
        )
    )
    assert facts_port.get_facts(change, "CI_VERIFIED").ci_passed_for_current_head is True

    outcomes.create(
        Outcome(
            id=uuid4(), change_id=change.id, kind=OutcomeKind.CI, status=OutcomeStatus.FAILED,
            repository="acme/widgets", head_sha=current_sha,
            provider_reference="acme/widgets@" + current_sha, observed_at=newer,
        )
    )
    assert facts_port.get_facts(change, "CI_VERIFIED").ci_passed_for_current_head is False


def _git(repo, *args) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_recovery_facts_track_the_latest_plan_status(tmp_path) -> None:
    facts_port, _delegations, _provider_operations, _outcomes, recovery, base_change = _build(
        tmp_path
    )
    repo = tmp_path / "recovery-repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "user.email", "t@example.com")
    (repo / "a.txt").write_text("1\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "baseline")
    change = base_change.model_copy(update={"repository_path": str(repo)})
    now = datetime.now(UTC)

    assert facts_port.get_facts(change, "RECOVERING").recovery_plan_approved is False

    branch = f"change-assurance/recovery/{change.id}"
    result_sha = "d" * 40
    plan = RecoveryPlan(
        id=uuid4(),
        change_id=change.id,
        status=RecoveryStatus.PLANNED,
        actions=[
            RecoveryAction(
                id=uuid4(),
                kind="git.revert_commits",
                description="Revert one commit",
                supported=True,
                reversible_commit="c" * 40,
            )
        ],
        source_checkpoint_id=uuid4(),
        created_at=now,
    )
    recovery.create_plan(plan)
    facts = facts_port.get_facts(change, "RECOVERING")
    assert facts.recovery_plan_approved is False
    assert facts.unresolved_recovery_actions is True

    # Not yet verified: the plan claims a branch/SHA that does not exist in
    # the real repository, exactly the case a self-reported status alone
    # would wrongly call "verified".
    unverified_recovered = plan.model_copy(
        update={
            "status": RecoveryStatus.RECOVERED,
            "approved_at": now,
            "completed_at": now,
            "actions": [
                plan.actions[0].model_copy(
                    update={"provider_reference": f"branch:{branch}@{result_sha}"}
                )
            ],
        }
    )
    recovery.update_plan(unverified_recovered)
    facts = facts_port.get_facts(change, "RECOVERED_VERIFIED")
    assert facts.recovery_plan_approved is True
    assert facts.recovery_verified is False

    # Now create the real dedicated branch pointing at a real commit and
    # update the plan's action to reference that real SHA -- this is what a
    # genuine successful GitRecoveryEngine.execute() produces.
    _git(repo, "branch", branch)
    real_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", branch], capture_output=True
    ).stdout.decode().strip()
    verified_recovered = unverified_recovered.model_copy(
        update={
            "actions": [
                unverified_recovered.actions[0].model_copy(
                    update={"provider_reference": f"branch:{branch}@{real_sha}"}
                )
            ],
        }
    )
    recovery.update_plan(verified_recovered)
    facts = facts_port.get_facts(change, "RECOVERED_VERIFIED")
    assert facts.recovery_verified is True
    assert facts.recovery_conflict is False
    assert facts.recovery_failed is False
    assert facts.unresolved_recovery_actions is False


def test_recovery_conflict_and_failed_are_distinguished(tmp_path) -> None:
    facts_port, _delegations, _provider_operations, _outcomes, recovery, change = _build(
        tmp_path
    )
    now = datetime.now(UTC)
    base_plan = RecoveryPlan(
        id=uuid4(),
        change_id=change.id,
        status=RecoveryStatus.CONFLICTED,
        source_checkpoint_id=uuid4(),
        created_at=now,
        approved_at=now,
    )
    recovery.create_plan(base_plan)
    conflict_facts = facts_port.get_facts(change, "RECOVERY_CONFLICT")
    assert conflict_facts.recovery_conflict is True
    assert conflict_facts.recovery_failed is False
    assert conflict_facts.unresolved_recovery_actions is True

    failed_plan = base_plan.model_copy(update={"status": RecoveryStatus.RECOVERY_FAILED})
    recovery.update_plan(failed_plan)
    failed_facts = facts_port.get_facts(change, "RECOVERY_FAILED")
    assert failed_facts.recovery_failed is True
    assert failed_facts.recovery_conflict is False
    assert failed_facts.unresolved_recovery_actions is False
