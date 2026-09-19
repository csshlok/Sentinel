"""Stable recovery errors."""

from __future__ import annotations

from backend.app.core.errors import AppError


def recovery_no_checkpoint_evidence(change_id: str) -> AppError:
    return AppError(
        "RECOVERY_NO_CHECKPOINT_EVIDENCE",
        "No Git checkpoint evidence exists for this Change; recovery cannot be planned.",
        status_code=409,
        details={"change_id": change_id},
    )


def recovery_not_approved() -> AppError:
    return AppError(
        "RECOVERY_NOT_APPROVED",
        "Recovery execution requires an explicit, non-empty approval token.",
        status_code=403,
    )
