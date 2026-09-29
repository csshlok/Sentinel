"""GitHub App installation auth and exact-head Check publication primitives."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.credentials.broker import CredentialBroker
from backend.app.providers.github_app import app_provider_name
from backend.app.providers.http_transport import HttpTransport, TransportTimeout

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_API = "https://api.github.com"
_MAX_RESPONSE = 1_048_576


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class InstallationResult:
    state: Literal["INSTALLED", "GITHUB_APP_NOT_INSTALLED"]
    installation_url: str | None = None
    installation_id: int | None = None


class GitHubAppClient:
    """Resolve brokered App credentials only for the duration of one request."""

    def __init__(self, broker: CredentialBroker, transport: HttpTransport, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._broker = broker
        self._transport = transport
        self._clock = clock

    @staticmethod
    def _repository(repository: str) -> tuple[str, str]:
        parts = repository.split("/")
        if (len(parts) != 2 or any(part in {".", ".."} or not _REPOSITORY.fullmatch(part)
                                   for part in parts)):
            raise ValueError("Invalid GitHub repository")
        return parts[0], parts[1]

    def _app_secret(self, *, owner: str, actor_id: UUID, change_id: UUID) -> dict[str, object]:
        provider = app_provider_name(owner)
        scope = f"{provider}.publish"
        grant = self._broker.issue_grant(actor_id, change_id, [scope], 30)
        try:
            raw = self._broker.resolve_secret(grant.id, scope=scope)
        finally:
            self._broker.revoke(grant.id)
        try:
            parsed = json.loads(raw)
            if (not isinstance(parsed, dict) or type(parsed.get("id")) is not int
                    or parsed["id"] <= 0 or not isinstance(parsed.get("pem"), str)
                    or not isinstance(parsed.get("slug"), str)
                    or not _SLUG.fullmatch(parsed["slug"])):
                raise ValueError("Malformed brokered App credential")
            return parsed
        except (TypeError, ValueError) as exc:
            raise ValueError("Brokered GitHub App credential is invalid") from exc

    def _jwt(self, secret: dict[str, object]) -> str:
        try:
            private = serialization.load_pem_private_key(
                str(secret["pem"]).encode("ascii"), password=None)
            if not isinstance(private, rsa.RSAPrivateKey) or private.key_size < 2048:
                raise ValueError("GitHub App key is not RSA-2048 or stronger")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("Brokered GitHub App signing key is invalid") from exc
        now = int(self._clock().timestamp())
        header = _b64url(b'{"alg":"RS256","typ":"JWT"}')
        claims = _b64url(json.dumps({"iat": now - 60, "exp": now + 480,
                                     "iss": str(secret["id"])},
                                    sort_keys=True, separators=(",", ":")).encode("ascii"))
        message = f"{header}.{claims}".encode("ascii")
        signature = private.sign(message, padding.PKCS1v15(), hashes.SHA256())
        return f"{header}.{claims}.{_b64url(signature)}"

    def _request(self, method: str, path: str, token: str, *,
                 body: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
        if not path.startswith("/") or "//" in path:
            raise ValueError("Invalid GitHub API path")
        encoded = (json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
                   if body is not None else None)
        try:
            response = self._transport.request(
                method, _API + path,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2026-03-10",
                         "Content-Type": "application/json"},
                body=encoded, timeout_seconds=10,
            )
        except TransportTimeout as exc:
            raise OSError("GitHub request timed out") from exc
        if len(response.body) > _MAX_RESPONSE:
            raise ValueError("GitHub response is oversized")
        if response.status_code == 404:
            return 404, {}
        if response.status_code not in {200, 201}:
            raise OSError(f"GitHub request failed with HTTP {response.status_code}")
        try:
            value = json.loads(response.body)
            if not isinstance(value, dict):
                raise ValueError("GitHub response is not an object")
        except (UnicodeError, ValueError) as exc:
            raise ValueError("GitHub response is malformed") from exc
        return response.status_code, value

    def installation(self, *, owner: str, repository: str, actor_id: UUID,
                     change_id: UUID) -> InstallationResult:
        repo_owner, repo_name = self._repository(repository)
        if repo_owner.casefold() != owner.casefold():
            raise ValueError("App owner differs from repository owner")
        secret = self._app_secret(owner=owner, actor_id=actor_id, change_id=change_id)
        jwt = self._jwt(secret)
        status, value = self._request(
            "GET", f"/repos/{repo_owner}/{repo_name}/installation", jwt)
        if status == 404:
            return InstallationResult(
                "GITHUB_APP_NOT_INSTALLED",
                installation_url=f"https://github.com/apps/{secret['slug']}/installations/new",
            )
        identifier = value.get("id")
        if type(identifier) is not int or identifier <= 0:
            raise ValueError("GitHub installation identifier is invalid")
        return InstallationResult("INSTALLED", installation_id=identifier)

    def installation_token(self, *, owner: str, repository: str, actor_id: UUID,
                           change_id: UUID) -> tuple[InstallationResult, str | None]:
        """Mint a new short-lived token on each invocation; never cache it."""
        repo_owner, repo_name = self._repository(repository)
        if repo_owner.casefold() != owner.casefold():
            raise ValueError("App owner differs from repository owner")
        secret = self._app_secret(owner=owner, actor_id=actor_id, change_id=change_id)
        jwt = self._jwt(secret)
        status, value = self._request(
            "GET", f"/repos/{repo_owner}/{repo_name}/installation", jwt)
        if status == 404:
            return InstallationResult(
                "GITHUB_APP_NOT_INSTALLED",
                installation_url=f"https://github.com/apps/{secret['slug']}/installations/new",
            ), None
        identifier = value.get("id")
        if type(identifier) is not int or identifier <= 0:
            raise ValueError("GitHub installation identifier is invalid")
        _, token_response = self._request(
            "POST", f"/app/installations/{identifier}/access_tokens", jwt,
            body={"repositories": [repo_name], "permissions": {"checks": "write",
                                                               "pull_requests": "read"}},
        )
        token = token_response.get("token")
        expires = token_response.get("expires_at")
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise ValueError("GitHub installation token is missing")
        try:
            expiry = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("GitHub installation token expiry is malformed") from exc
        if (expiry.tzinfo is None or expiry <= self._clock()
                or expiry > self._clock() + timedelta(hours=1, minutes=5)):
            raise ValueError("GitHub installation token expiry is invalid")
        return InstallationResult("INSTALLED", installation_id=identifier), token
