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

