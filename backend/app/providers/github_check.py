"""GitHub App installation auth and exact-head Check publication primitives."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.credentials.broker import CredentialBroker
from backend.app.contracts.models import PassportV2Payload
from backend.app.core.database import Database
from backend.app.core.runtime_repositories import ProviderOperationRepository
from backend.app.passport.bundle import BundleArtifact, BundleExporter
from backend.app.passport.jcs import parse_canonical
from backend.app.providers.github_app import app_provider_name
from backend.app.providers.http_transport import HttpTransport, TransportTimeout

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_API = "https://api.github.com"
_MAX_RESPONSE = 1_048_576
_DENIAL_CONTEXTS = 8


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


@dataclass(frozen=True, slots=True)
class CheckPublication:
    state: Literal["PUBLISHED", "GITHUB_APP_NOT_INSTALLED"]
    presentation: Literal["CHECK_RUN", "COMMIT_STATUS_LESSER"] = "CHECK_RUN"
    installation_url: str | None = None
    repository: str | None = None
    pr_number: int | None = None
    head_sha: str | None = None
    check_url: str | None = None
    payload_digest: str | None = None
    signer_fingerprint: str | None = None
    checks_passed: bool | None = None
    diff_exercised: str | None = None
    freshness: str | None = None
    signed_freshness: str | None = None
    execution_boundary: str | None = None


class GitHubCheckPublisher:
    """Publish one DB-owned Change's signed claims to its recorded PR head."""

    def __init__(self, database: Database, broker: CredentialBroker,
                 transport: HttpTransport, *,
                 bundle_export: Callable[[UUID], BundleArtifact] | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._database = database
        self._client = GitHubAppClient(broker, transport, clock=clock)
        self._export = bundle_export or BundleExporter(database).export

    def _live_pr_head(self, repository: str, number: int, token: str) -> str:
        _, pr = self._client._request(
            "GET", f"/repos/{repository}/pulls/{number}", token)
        head = pr.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise ValueError("GitHub pull request head is malformed")
        return sha

    def publish(self, change_id: UUID, *, decline_app: bool = False,
                fallback_token: str | None = None) -> CheckPublication:
        if not decline_app and fallback_token is not None:
            raise ValueError("A fallback token requires declined App presentation")
        with self._database.connection() as connection:
            change = connection.execute("SELECT id FROM changes WHERE id = ?",
                                        (str(change_id),)).fetchone()
        if change is None:
            raise ValueError("Change does not exist")
        operation = ProviderOperationRepository(self._database).get_succeeded_operation(
            change_id, "github.pr.create")
        if operation is None:
            raise ValueError("Change has no recorded GitHub pull request")
        repository = operation.request.parameters.get("repository")
        number = operation.safe_metadata.get("number")
        original_head = operation.safe_metadata.get("head_sha")
        if (not isinstance(repository, str) or type(number) is not int or number <= 0
                or not isinstance(original_head, str) or not _SHA.fullmatch(original_head)):
            raise ValueError("Recorded pull request is malformed")
        owner, _ = self._client._repository(repository)
        if decline_app:
            if (not isinstance(fallback_token, str) or not fallback_token
                    or len(fallback_token) > 4096):
                raise ValueError("An authorized GitHub fallback token is required")
            token = fallback_token
        else:
            installation, token = self._client.installation_token(
                owner=owner, repository=repository, actor_id=operation.request.actor_id,
                change_id=change_id)
            if token is None:
                return CheckPublication("GITHUB_APP_NOT_INSTALLED",
                                        installation_url=installation.installation_url,
                                        repository=repository, pr_number=number)
        first_sha = self._live_pr_head(repository, number, token)

        artifact = self._export(change_id)
        with zipfile.ZipFile(io.BytesIO(artifact.content), "r") as archive:
            passport = parse_canonical(archive.read("passport.json"))
        if not isinstance(passport, dict) or not isinstance(passport.get("claims"), dict):
            raise ValueError("Exported Passport is malformed")
        claims = PassportV2Payload.model_validate(passport["claims"])
        if claims.change_id != change_id:
            raise ValueError("Exported Passport belongs to another Change")
        signer = passport.get("signer")
        if (not isinstance(signer, dict) or
                signer.get("fingerprint") != artifact.signer_fingerprint):
            raise ValueError("Exported Passport signer differs from bundle")
        sha = self._live_pr_head(repository, number, token)
        with self._database.connection() as connection:
            latest = connection.execute(
                "SELECT revision, contract_json FROM changes WHERE id = ?",
                (str(change_id),)).fetchone()
        if latest is None:
            raise ValueError("Change no longer exists")
        contract_raw = latest["contract_json"]
        latest_digest = (hashlib.sha256(contract_raw.encode("utf-8")).hexdigest()
                         if isinstance(contract_raw, str) else None)
        signed_freshness = claims.diff_coverage.freshness
        freshness = ("STALE" if sha != first_sha or sha != original_head or
                     latest["revision"] != claims.change_revision or
                     latest_digest != claims.contract_digest or
                     claims.diff_coverage.head_sha not in {None, sha}
                     else signed_freshness)
        diff = claims.diff_coverage
        checks_text = "PASS" if diff.checks_passed is True else (
            "FAIL" if diff.checks_passed is False else "UNKNOWN")
        selected_preset = bool(claims.policy_preset_name and claims.policy_preset_version)
        policy_decision = claims.policy_decision if selected_preset else "UNSELECTED"
        conclusion = ("failure" if checks_text == "FAIL" or diff.diff_exercised == "FAIL"
                      else "neutral" if freshness != "CURRENT" or
                      checks_text != "PASS" or diff.diff_exercised != "PASS" or
                      claims.execution_boundary == "UNKNOWN" or policy_decision != "ALLOW"
                      else "success")
        verify_command = (f"Verify: export change-{change_id}.sentinel from Sentinel; use "
                          "a fingerprint you already trust.")
        summary = "\n".join([
            f"Checks passed: {checks_text}",
            f"Diff exercised: {diff.diff_exercised}",
            f"Freshness: {freshness}",
            f"Signed Passport freshness: {signed_freshness}",
            f"Execution boundary: {claims.execution_boundary}",
            f"Policy preset: {claims.policy_preset_name or 'no preset selected'}",
            f"Policy preset version: {claims.policy_preset_version or 'none'}",
            f"Policy decision: {policy_decision}",
            f"Policy denials: {', '.join(claims.policy_denials) or 'none'}",
            f"Payload SHA-256: {artifact.payload_sha256}",
            f"Signer fingerprint: {artifact.signer_fingerprint}",
            verify_command,
            "Execution of changed lines does not prove assertion quality.",
        ])
        body = {"name": "Sentinel Passport v2", "head_sha": sha,
                "status": "completed", "conclusion": conclusion,
                "output": {"title": f"Sentinel: {freshness}", "summary": summary}}
        if decline_app:
            status_state = ("failure" if conclusion == "failure" else
                            "success" if conclusion == "success" else "error")
            descriptions = {
                "claims": f"Commit status (lesser): checks {checks_text}; diff {diff.diff_exercised}; freshness {freshness}",
                "boundary": ("Commit status (lesser): boundary "
                             f"{claims.execution_boundary}; signed freshness {signed_freshness}"),
                "payload": f"Commit status (lesser): payload SHA-256 {artifact.payload_sha256}",
                "signer": f"Commit status (lesser): signer {artifact.signer_fingerprint}",
                "verify-lesser": verify_command,
                "policy": (f"Commit status (lesser): preset "
                           f"{claims.policy_preset_name or 'no preset selected'} "
                           f"v{claims.policy_preset_version or 'none'}; {policy_decision}"),
            }
            denial_text = "Policy denials: " + ("; ".join(claims.policy_denials) or "none")
            if len(denial_text) > 120 * _DENIAL_CONTEXTS:
                raise ValueError("Signed policy denials exceed GitHub commit status capacity")
            for slot in range(_DENIAL_CONTEXTS):
                descriptions[f"policy-denials-{slot + 1}"] = (
                    denial_text[slot * 120:(slot + 1) * 120] or "Policy denials: [end]")
            if any(len(value) > 140 for value in descriptions.values()):
                raise ValueError("Signed claims exceed GitHub commit status limit")
            for context, description in descriptions.items():
                _, status_result = self._client._request(
                    "POST", f"/repos/{repository}/statuses/{sha}", token,
                    body={"state": status_state, "context": f"sentinel/passport/{context}",
                          "description": description})
                if type(status_result.get("id")) is not int or status_result["id"] <= 0:
                    raise ValueError("GitHub commit status response is invalid")
            url = None
        else:
            _, check = self._client._request(
                "POST", f"/repos/{repository}/check-runs", token, body=body)
            check_id = check.get("id")
            check_sha = check.get("head_sha")
            if type(check_id) is not int or check_id <= 0 or check_sha != sha:
                raise ValueError("GitHub Check response differs from requested PR head")
            url = check.get("html_url")
            if not isinstance(url, str) or not url.startswith("https://github.com/"):
                url = None
        return CheckPublication(
            "PUBLISHED", presentation=("COMMIT_STATUS_LESSER" if decline_app else "CHECK_RUN"),
            repository=repository, pr_number=number,
            head_sha=sha, check_url=url, payload_digest=artifact.payload_sha256,
            signer_fingerprint=artifact.signer_fingerprint,
            checks_passed=diff.checks_passed, diff_exercised=diff.diff_exercised,
            freshness=freshness, signed_freshness=signed_freshness,
            execution_boundary=claims.execution_boundary,
        )
