"""Stable ``WORKSPACE_*`` errors for the AppContainer workspace lifecycle."""

from __future__ import annotations

from backend.app.core.errors import AppError


def workspace_not_found(change_id: str) -> AppError:
    return AppError(
        "WORKSPACE_NOT_FOUND",
        "No live workspace exists for this Change.",
        status_code=404,
        details={"change_id": change_id},
    )


def workspace_state_conflict(state: str, operation: str) -> AppError:
    return AppError(
        "WORKSPACE_STATE_CONFLICT",
        f"The workspace cannot '{operation}' in its current state.",
        status_code=409,
        details={"state": state, "operation": operation},
    )


def workspace_clone_failed(reason: str) -> AppError:
    return AppError(
        "WORKSPACE_CLONE_FAILED",
        "The workspace clone could not be created.",
        status_code=500,
        details={"reason": reason},
    )


def workspace_seal_failed(reason: str) -> AppError:
    return AppError(
        "WORKSPACE_SEAL_FAILED",
        "The workspace changes could not be sealed.",
        status_code=500,
        details={"reason": reason},
    )


def workspace_approval_invalid() -> AppError:
    return AppError(
        "WORKSPACE_APPROVAL_INVALID",
        "The apply-back approval is invalid or does not match the previewed commits.",
        status_code=403,
    )


def workspace_apply_failed(reason: str) -> AppError:
    return AppError(
        "WORKSPACE_APPLY_FAILED",
        "The workspace changes could not be applied.",
        status_code=500,
        details={"reason": reason},
    )


def workspace_cleanup_failed(reason: str) -> AppError:
    return AppError(
        "WORKSPACE_CLEANUP_FAILED",
        "The workspace could not be fully cleaned up.",
        status_code=500,
        details={"reason": reason},
    )
