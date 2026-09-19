"""Loopback API bearer-token authentication.

`BACKEND_IMPLEMENTATION_PLAN.md` section 17 requires authenticating every
non-health route; `OVERALL_CONTEXT.md`'s local-first invariant describes
"a loopback-only authenticated API." Until this module, no such check
existed anywhere: every route was reachable by any local process that could
reach the port.

This is a single-user, local shared-secret token, not a multi-user session
system — consistent with the product's one-operator, local-first scope
(there is no login flow, no user directory, and `[AC]`'s `Actor`/`Delegation`
model already answers "who may do what to this Change," which is a
different question from "may this caller talk to the API at all"). The
token is generated once per database directory, stored next to the
database, and never echoed back in any response, log, or error.
"""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path

from fastapi import Header

from backend.app.core.errors import AppError

TOKEN_FILENAME = "api_token"


def load_or_create_api_token(database_path: Path) -> str:
    """Return the persisted token for this database, generating one if absent."""

    token_path = database_path.parent / TOKEN_FILENAME
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if token_path.exists():
        existing = token_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    token_path.write_text(token, encoding="utf-8")
    return token


def unauthenticated(message: str) -> AppError:
    return AppError("UNAUTHENTICATED", message, status_code=401)


def require_bearer_token(expected_token: str):
    """Build a FastAPI dependency that requires `Authorization: Bearer <token>`.

    Comparison is constant-time (`hmac.compare_digest`) so response timing
    cannot be used to guess the token byte by byte.
    """

    def _dependency(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        if authorization is None or not authorization.startswith("Bearer "):
            raise unauthenticated("A bearer token is required.")
        presented = authorization.removeprefix("Bearer ").strip()
        if not presented or not hmac.compare_digest(presented, expected_token):
            raise unauthenticated("The bearer token is invalid.")

    return _dependency
