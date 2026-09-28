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


def workspace_busy() -> AppError:
    return AppError(
        "WORKSPACE_BUSY",
        "Another run or operation currently holds this Change's workspace.",
        status_code=409,
    )


def workspace_cleanup_pending(state: str) -> AppError:
    return AppError(
        "WORKSPACE_CLEANUP_PENDING",
        "This Change's previous workspace must be cleaned up before a new run can start.",
        status_code=409,
        details={"state": state},
    )


def workspace_source_dirty() -> AppError:
    return AppError(
        "WORKSPACE_SOURCE_DIRTY",
        "The source repository has uncommitted changes to tracked files; commit or stash "
        "them before launching, because the workspace only contains committed content.",
        status_code=409,
    )


def workspace_source_detached() -> AppError:
    return AppError(
        "WORKSPACE_SOURCE_DETACHED",
        "The source repository HEAD is detached; check out a branch before launching.",
        status_code=409,
    )


def workspace_source_alternates() -> AppError:
    return AppError(
        "WORKSPACE_SOURCE_ALTERNATES",
        "The source repository borrows objects from another repository (object "
        "alternates), which a workspace clone cannot use.",
        status_code=409,
    )


def workspace_source_mismatch() -> AppError:
    return AppError(
        "WORKSPACE_SOURCE_MISMATCH",
        "This Change's workspace was cloned from a different source repository.",
        status_code=409,
    )


def workspace_base_mismatch() -> AppError:
    return AppError(
        "WORKSPACE_BASE_MISMATCH",
        "The source repository HEAD is not the commit recorded by this Change's BASELINE "
        "checkpoint.",
        status_code=409,
    )


def workspace_git_tampered(check: str) -> AppError:
    return AppError(
        "WORKSPACE_GIT_TAMPERED",
        "The workspace Git metadata was altered in a way Sentinel refuses to operate on.",
        status_code=409,
        details={"check": check},
    )
