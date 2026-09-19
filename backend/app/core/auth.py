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
import os
import secrets
import stat
import subprocess
from pathlib import Path

from fastapi import Header

from backend.app.core.errors import AppError

TOKEN_FILENAME = "api_token"


def _restrict_to_current_user(token_path: Path) -> None:
    """Best-effort ACL/mode restriction (threat model finding #12).

    Previously a plain `Path.write_text` with no ACL/mode set: another
    local OS account could read the shared bearer token if the parent
    directory wasn't already private. `os.chmod` is a real restriction on
    POSIX (correct there even though this product targets Windows first)
    and a harmless no-op on Windows, where the actual restriction is
    `icacls /inheritance:r` (strip inherited ACEs) plus an explicit grant
    limited to the current user. Never raises: a failure here (icacls
    missing, no permission to change ACLs, a restricted sandbox) must not
    break API startup over a defense-in-depth hardening step -- the token
    file still lives under the per-user database directory either way.
    """

    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if os.name == "nt":
        username = os.environ.get("USERNAME")
        if not username:
            return
        try:
            subprocess.run(
                ["icacls", str(token_path), "/inheritance:r",
                 "/grant:r", f"{username}:F"],
                capture_output=True, shell=False, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def load_or_create_api_token(database_path: Path) -> str:
    """Return the persisted token for this database, generating one if absent."""

    token_path = database_path.parent / TOKEN_FILENAME
    token_path.parent.mkdir(parents=True, exist_ok=True)
    if token_path.exists():
        existing = token_path.read_text(encoding="utf-8").strip()
        if existing:
            _restrict_to_current_user(token_path)
            return existing
    token = secrets.token_urlsafe(32)
    token_path.write_text(token, encoding="utf-8")
    _restrict_to_current_user(token_path)
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
