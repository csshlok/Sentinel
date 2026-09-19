"""Stable credential-broker errors. Never include secret material."""

from __future__ import annotations

from backend.app.core.errors import AppError


def grant_not_found(grant_id: str) -> AppError:
    return AppError(
        "CREDENTIAL_GRANT_NOT_FOUND",
        "The requested credential grant does not exist.",
        status_code=404,
        details={"grant_id": grant_id},
    )


def grant_denied(grant_id: str) -> AppError:
    return AppError(
        "CREDENTIAL_GRANT_DENIED",
        "The credential grant is expired, revoked, or does not cover the requested scope.",
        status_code=403,
        details={"grant_id": grant_id},
    )


def provider_secret_not_configured(provider: str) -> AppError:
    return AppError(
        "PROVIDER_SECRET_NOT_CONFIGURED",
        f"No credential has been stored for provider '{provider}'.",
        status_code=409,
        details={"provider": provider},
    )
