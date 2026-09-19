"""Stable verification errors exposed through the shared API error envelope."""

from __future__ import annotations

from backend.app.core.errors import AppError


def executable_not_allowed(executable: str) -> AppError:
    return AppError(
        "VERIFICATION_EXECUTABLE_NOT_ALLOWED",
        f"The executable '{executable}' is not permitted for verification.",
        status_code=400,
        details={"executable": executable},
    )


def executable_not_found(executable: str) -> AppError:
    return AppError(
        "VERIFICATION_EXECUTABLE_NOT_FOUND",
        f"The executable '{executable}' could not be located on PATH.",
        status_code=400,
        details={"executable": executable},
    )
