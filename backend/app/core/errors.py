"""Stable application errors exposed through the API error envelope."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def change_not_found(change_id: str) -> AppError:
    return AppError(
        "CHANGE_NOT_FOUND",
        "The requested Change does not exist.",
        status_code=404,
        details={"change_id": change_id},
    )


def adapter_unavailable(capability: str) -> AppError:
    return AppError(
        "CAPABILITY_UNAVAILABLE",
        f"The {capability} capability has not been connected yet.",
        status_code=503,
        details={"capability": capability},
    )


def revision_conflict(*, expected: int, actual: int) -> AppError:
    return AppError(
        "REVISION_CONFLICT",
        "The Change was updated by another operation.",
        status_code=409,
        details={"expected_revision": expected, "actual_revision": actual},
    )


def idempotency_conflict(scope: str) -> AppError:
    return AppError(
        "IDEMPOTENCY_KEY_REUSED",
        "The idempotency key was already used for a different request.",
        status_code=409,
        details={"scope": scope},
    )


def invalid_transition(current: str, target: str) -> AppError:
    return AppError(
        "INVALID_CHANGE_TRANSITION",
        "The requested lifecycle transition is not allowed.",
        status_code=409,
        details={"current_state": current, "target_state": target},
    )


def transition_guard_failed(target: str, missing: list[str]) -> AppError:
    return AppError(
        "TRANSITION_GUARD_FAILED",
        "Authoritative evidence does not permit the requested transition.",
        status_code=409,
        details={"target_state": target, "missing_requirements": missing},
    )


def policy_denied(reason_code: str, explanation: str) -> AppError:
    return AppError(
        "POLICY_DENIED",
        explanation,
        status_code=403,
        details={"reason_code": reason_code},
    )


def provider_repository_unresolved(repository_path: str) -> AppError:
    return AppError(
        "PROVIDER_REPOSITORY_UNRESOLVED",
        "The Change's repository has no resolvable GitHub remote.",
        status_code=409,
        details={"repository_path": repository_path},
    )


def no_pull_request_to_compensate(change_id: str) -> AppError:
    return AppError(
        "NO_PULL_REQUEST_TO_COMPENSATE",
        "This Change has no succeeded pull-request-creation operation to compensate.",
        status_code=409,
        details={"change_id": change_id},
    )


def grant_binding_invalid(grant_id: str) -> AppError:
    return AppError(
        "CREDENTIAL_GRANT_BINDING_INVALID",
        "The credential grant is not bound to the requesting actor and Change.",
        status_code=403,
        details={"grant_id": grant_id},
    )


def recovery_plan_not_found(plan_id: str) -> AppError:
    return AppError(
        "RECOVERY_PLAN_NOT_FOUND",
        "The requested recovery plan does not exist.",
        status_code=404,
        details={"plan_id": plan_id},
    )


def passport_not_found(change_id: str) -> AppError:
    return AppError(
        "PASSPORT_NOT_FOUND",
        "No Change Passport has been generated for this Change yet.",
        status_code=404,
        details={"change_id": change_id},
    )


def tool_not_found(tool_id: str) -> AppError:
    return AppError(
        "TOOL_NOT_FOUND",
        "The requested tool is not registered.",
        status_code=404,
        details={"tool_id": tool_id},
    )


def tool_executable_unreadable(executable_path: str) -> AppError:
    return AppError(
        "TOOL_EXECUTABLE_UNREADABLE",
        "The tool's executable could not be read to compute its identity.",
        status_code=400,
        details={"executable_path": executable_path},
    )


def tool_trust_denied(tool_id: str) -> AppError:
    return AppError(
        "TOOL_TRUST_DENIED",
        "This tool is explicitly denied and may not be launched.",
        status_code=403,
        details={"tool_id": tool_id},
    )
