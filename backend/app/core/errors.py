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
