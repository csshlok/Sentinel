"""Stable identity-domain errors exposed through the shared API envelope."""

from __future__ import annotations

from backend.app.core.errors import AppError


def actor_not_found(actor_id: str) -> AppError:
    return AppError(
        "ACTOR_NOT_FOUND",
        "The requested actor does not exist.",
        status_code=404,
        details={"actor_id": actor_id},
    )


def delegation_not_found(delegation_id: str) -> AppError:
    return AppError(
        "DELEGATION_NOT_FOUND",
        "The requested delegation does not exist.",
        status_code=404,
        details={"delegation_id": delegation_id},
    )
