"""Stable provider errors. Details never carry the bearer token or raw body."""

from __future__ import annotations

from backend.app.core.errors import AppError

RETRYABLE_CODES = frozenset(
    {"PROVIDER_RATE_LIMITED", "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT"}
)


def provider_auth_failed(status_code: int) -> AppError:
    return AppError(
        "PROVIDER_AUTH_FAILED",
        "The provider rejected the request's authorization.",
        status_code=502,
        details={"provider_status": status_code},
    )


def provider_not_found() -> AppError:
    return AppError(
        "PROVIDER_NOT_FOUND",
        "The requested provider resource does not exist.",
        status_code=404,
    )


def provider_conflict() -> AppError:
    return AppError(
        "PROVIDER_CONFLICT",
        "The provider reported a conflicting state.",
        status_code=409,
    )


def provider_validation_failed(message: str | None) -> AppError:
    return AppError(
        "PROVIDER_VALIDATION_FAILED",
        "The provider rejected the request as invalid.",
        status_code=422,
        details={"provider_message": message} if message else {},
    )


def provider_rate_limited(retry_after_seconds: float | None) -> AppError:
    return AppError(
        "PROVIDER_RATE_LIMITED",
        "The provider is rate-limiting requests.",
        status_code=429,
        details={"retry_after_seconds": retry_after_seconds},
    )


def provider_unavailable(status_code: int) -> AppError:
    return AppError(
        "PROVIDER_UNAVAILABLE",
        "The provider is temporarily unavailable.",
        status_code=502,
        details={"provider_status": status_code},
    )


def provider_timeout() -> AppError:
    return AppError(
        "PROVIDER_TIMEOUT", "The provider request timed out.", status_code=504
    )
