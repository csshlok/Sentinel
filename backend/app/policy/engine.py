"""Pure, deterministic policy evaluation.

Every branch defaults to deny. Authority (a delegation's
`AuthorizationDecision`) is checked first: policy never grants an
operation that identity has already refused, and policy narrows further
from there. This module has no I/O and no dependency on unfrozen shared
contracts, so it stays testable independent of `[SD]`'s eventual
Change/lifecycle freeze.
"""

from __future__ import annotations

from collections.abc import Iterable
from posixpath import normpath

from backend.app.identity.models import AuthorizationDecision
from backend.app.policy.models import PolicyDecision, PolicyDenialReason, PolicyOperation, RiskLevel

DEFAULT_DENIED_OPERATIONS = frozenset(
    {PolicyOperation.PROVIDER_FORCE_PUSH, PolicyOperation.PROVIDER_SECRET_READ}
)


def _path_is_forbidden(target_path: str, forbidden_prefixes: Iterable[str]) -> bool:
    normalized = normpath(target_path.replace("\\", "/")).lstrip("/")
    for prefix in forbidden_prefixes:
        normalized_prefix = normpath(prefix.replace("\\", "/")).lstrip("/")
        if normalized == normalized_prefix or normalized.startswith(
            normalized_prefix + "/"
        ):
            return True
    return False


def evaluate(
    *,
    operation: PolicyOperation,
    authorization: AuthorizationDecision,
    risk: RiskLevel = RiskLevel.LOW,
    target_path: str | None = None,
    forbidden_path_prefixes: Iterable[str] = (),
    lifecycle_state: str | None = None,
    permitted_lifecycle_states: Iterable[str] | None = None,
) -> PolicyDecision:
    if not authorization.allowed:
        return PolicyDecision(
            allowed=False, risk=risk, denial_reason=PolicyDenialReason.AUTHORITY_DENIED
        )
    if operation in DEFAULT_DENIED_OPERATIONS:
        return PolicyDecision(
            allowed=False,
            risk=RiskLevel.HIGH,
            denial_reason=PolicyDenialReason.OPERATION_NOT_PERMITTED,
        )
    if target_path is not None and _path_is_forbidden(
        target_path, forbidden_path_prefixes
    ):
        return PolicyDecision(
            allowed=False,
            risk=RiskLevel.HIGH,
            denial_reason=PolicyDenialReason.PATH_FORBIDDEN,
        )
    if (
        permitted_lifecycle_states is not None
        and lifecycle_state not in permitted_lifecycle_states
    ):
        return PolicyDecision(
            allowed=False,
            risk=risk,
            denial_reason=PolicyDenialReason.LIFECYCLE_STATE_INVALID,
        )
    if risk is RiskLevel.HIGH:
        return PolicyDecision(
            allowed=False, risk=risk, denial_reason=PolicyDenialReason.RISK_TOO_HIGH
        )
    return PolicyDecision(allowed=True, risk=risk)
