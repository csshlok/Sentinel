import pytest

from backend.app.identity.models import AuthorizationDecision
from backend.app.policy.engine import evaluate
from backend.app.policy.models import PolicyDenialReason, PolicyOperation, RiskLevel

ALLOWED = AuthorizationDecision(allowed=True)
DENIED = AuthorizationDecision(allowed=False)


def test_authority_denied_overrides_everything() -> None:
    decision = evaluate(operation=PolicyOperation.PROVIDER_REPO_READ, authorization=DENIED)
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.AUTHORITY_DENIED


@pytest.mark.parametrize(
    "operation",
    [PolicyOperation.PROVIDER_FORCE_PUSH, PolicyOperation.PROVIDER_SECRET_READ],
)
def test_default_denied_operations(operation: PolicyOperation) -> None:
    decision = evaluate(operation=operation, authorization=ALLOWED)
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.OPERATION_NOT_PERMITTED
    assert decision.risk is RiskLevel.HIGH


def test_forbidden_path_prefix_denies() -> None:
    decision = evaluate(
        operation=PolicyOperation.GIT_RECOVERY_COMMIT,
        authorization=ALLOWED,
        target_path="secrets/prod.env",
        forbidden_path_prefixes=["secrets"],
    )
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.PATH_FORBIDDEN


def test_path_outside_forbidden_prefix_is_not_denied_for_that_reason() -> None:
    decision = evaluate(
        operation=PolicyOperation.GIT_RECOVERY_COMMIT,
        authorization=ALLOWED,
        target_path="src/app.py",
        forbidden_path_prefixes=["secrets"],
    )
    assert decision.denial_reason is not PolicyDenialReason.PATH_FORBIDDEN


def test_similarly_named_sibling_path_is_not_forbidden() -> None:
    decision = evaluate(
        operation=PolicyOperation.GIT_RECOVERY_COMMIT,
        authorization=ALLOWED,
        target_path="secrets-backup/file.txt",
        forbidden_path_prefixes=["secrets"],
    )
    assert decision.denial_reason is not PolicyDenialReason.PATH_FORBIDDEN


def test_forbidden_path_prefix_denies_regardless_of_case() -> None:
    # NTFS is case-insensitive, so "Secrets/prod.env" and "secrets/prod.env"
    # name the same file -- a case-sensitive comparison here would let this
    # bypass a forbidden prefix of "secrets".
    decision = evaluate(
        operation=PolicyOperation.GIT_RECOVERY_COMMIT,
        authorization=ALLOWED,
        target_path="Secrets/prod.env",
        forbidden_path_prefixes=["secrets"],
    )
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.PATH_FORBIDDEN


def test_lifecycle_state_not_permitted_denies() -> None:
    decision = evaluate(
        operation=PolicyOperation.ASSURANCE_RUN,
        authorization=ALLOWED,
        lifecycle_state="DRAFT",
        permitted_lifecycle_states={"ACTIVE", "LOCALLY_VERIFIED"},
    )
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.LIFECYCLE_STATE_INVALID


def test_high_risk_denies_even_with_authority() -> None:
    decision = evaluate(
        operation=PolicyOperation.ASSURANCE_RUN,
        authorization=ALLOWED,
        risk=RiskLevel.HIGH,
    )
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.RISK_TOO_HIGH


def test_allows_low_risk_permitted_operation() -> None:
    decision = evaluate(
        operation=PolicyOperation.PROVIDER_PR_CREATE,
        authorization=ALLOWED,
        risk=RiskLevel.LOW,
        target_path="src/app.py",
        forbidden_path_prefixes=["secrets"],
        lifecycle_state="ACTIVE",
        permitted_lifecycle_states={"ACTIVE"},
    )
    assert decision.allowed is True
    assert decision.denial_reason is None
