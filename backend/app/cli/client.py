"""Thin JSON client for the local Change Assurance API.

Reuses the generic `HttpTransport` seam from `backend.app.providers` so
no new HTTP dependency is introduced. Every CLI command goes through
this client and the real API only; nothing here imports persistence or
services directly, so authentication, policy, and lifecycle guards can
never be bypassed.
"""

from __future__ import annotations

import json
import os
from typing import Any
from uuid import UUID

from backend.app.providers.http_transport import (
    HttpTransport,
    TransportTimeout,
    UrllibHttpTransport,
)


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ApiConnectionError(Exception):
    """The API could not be reached at all (network/timeout)."""


class ApiClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 10.0,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or UrllibHttpTransport()
        self.timeout_seconds = timeout_seconds
        # Every non-health route requires a bearer token (plan section 17).
        # Falls back to the environment variable so existing `ApiClient(url)`
        # call sites in `cli/main.py` keep working unchanged once the token
        # is exported into the CLI's environment.
        self.token = token if token is not None else os.environ.get(
            "CHANGE_ASSURANCE_API_TOKEN"
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = self.transport.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds or self.timeout_seconds,
            )
        except TransportTimeout as error:
            raise ApiConnectionError(str(error)) from error

        if response.status_code == 204:
            return None
        payload = json.loads(response.body) if response.body else None
        if response.status_code >= 400:
            error = (payload or {}).get("error", {})
            raise ApiError(
                error.get("code", "UNKNOWN_ERROR"),
                error.get("message", "Request failed"),
                status_code=response.status_code,
                details=error.get("details", {}),
            )
        return payload

    # -- system --
    def capabilities(self) -> Any:
        return self._request("GET", "/api/v1/capabilities")

    def validate_repository(self, path: str) -> Any:
        return self._request("POST", "/api/v1/repositories/validate", json_body={"path": path})

    # -- changes --
    def create_change(
        self, title: str, intent: str, repository_path: str, *, idempotency_key: str | None = None
    ) -> Any:
        return self._request(
            "POST",
            "/api/v1/changes",
            json_body={"title": title, "intent": intent, "repository_path": repository_path},
            idempotency_key=idempotency_key,
        )

    def list_changes(self, *, limit: int = 100, offset: int = 0) -> Any:
        return self._request("GET", f"/api/v1/changes?limit={limit}&offset={offset}")

    def get_change(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}")

    def update_change_contract(
        self,
        change_id: UUID,
        *,
        expected_revision: int,
        allowed_paths: list[str] | None = None,
        forbidden_paths: list[str] | None = None,
        expected_outcomes: list[str] | None = None,
        required_checks: list[str] | None = None,
        authority_ceiling: list[str] | None = None,
        allowed_provider_operations: list[str] | None = None,
        max_risk: str = "MEDIUM",
        recovery_allowed: bool = True,
    ) -> Any:
        contract: dict[str, Any] = {
            "allowed_paths": allowed_paths if allowed_paths is not None else ["**"],
            "forbidden_paths": forbidden_paths or [],
            "expected_outcomes": expected_outcomes or [],
            "required_checks": required_checks or [],
            "authority_ceiling": authority_ceiling or [],
            "allowed_provider_operations": allowed_provider_operations or [],
            "max_risk": max_risk,
            "recovery_allowed": recovery_allowed,
        }
        return self._request(
            "PUT",
            f"/api/v1/changes/{change_id}/contract",
            json_body={"contract": contract, "expected_revision": expected_revision},
        )

    # -- identity --
    def create_actor(self, kind: str, display_name: str) -> Any:
        return self._request(
            "POST", "/api/v1/actors", json_body={"kind": kind, "display_name": display_name}
        )

    def get_actor(self, actor_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/actors/{actor_id}")

    def create_delegation(
        self,
        *,
        grantor_id: UUID,
        grantee_id: UUID,
        change_id: UUID,
        scopes: list[str],
        ttl_seconds: int,
    ) -> Any:
        return self._request(
            "POST",
            "/api/v1/delegations",
            json_body={
                "grantor_id": str(grantor_id),
                "grantee_id": str(grantee_id),
                "change_id": str(change_id),
                "scopes": scopes,
                "ttl_seconds": ttl_seconds,
            },
        )

    def revoke_delegation(self, delegation_id: UUID) -> Any:
        return self._request("POST", f"/api/v1/delegations/{delegation_id}/revoke")

    def list_delegations(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/delegations")

    # -- evidence (git checkpoints, environment, dependencies, assurance) --
    def list_git_checkpoints(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/git/checkpoints")

    def get_environment(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/environment")

    def get_dependencies(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/dependencies")

    def get_latest_assurance_plan(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/assurance/plan")

    def get_assurance_facts(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/assurance/facts")

    # -- providers/github --
    def github_connect(self, token: str) -> Any:
        return self._request("POST", "/api/v1/providers/github/connect", json_body={"token": token})

    def github_disconnect(self) -> Any:
        return self._request("POST", "/api/v1/providers/github/disconnect")

    def github_status(self) -> Any:
        return self._request("GET", "/api/v1/providers/github/status")

    def issue_github_grant(
        self, change_id: UUID, *, actor_id: UUID, scopes: list[str], ttl_seconds: int = 900
    ) -> Any:
        return self._request(
            "POST",
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json_body={"actor_id": str(actor_id), "scopes": scopes, "ttl_seconds": ttl_seconds},
        )

    def create_pull_request(
        self,
        change_id: UUID,
        *,
        actor_id: UUID,
        grant_id: UUID,
        base_branch: str,
        head_branch: str,
        title: str,
        idempotency_key: str,
    ) -> Any:
        return self._request(
            "POST",
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json_body={
                "actor_id": str(actor_id),
                "grant_id": str(grant_id),
                "base_branch": base_branch,
                "head_branch": head_branch,
                "title": title,
                "idempotency_key": idempotency_key,
            },
        )

    # -- outcomes --
    def refresh_outcomes(
        self, change_id: UUID, *, grant_id: UUID, required_check_names: list[str] | None = None
    ) -> Any:
        return self._request(
            "POST",
            f"/api/v1/changes/{change_id}/outcomes/refresh",
            json_body={
                "grant_id": str(grant_id),
                "required_check_names": required_check_names or [],
            },
        )

    def list_outcomes(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/outcomes")

    # -- recovery --
    def preview_recovery(self, change_id: UUID) -> Any:
        return self._request("POST", f"/api/v1/changes/{change_id}/recovery/preview")

    def execute_recovery(
        self, change_id: UUID, plan_id: UUID, *, actor_id: UUID, approval_token: str
    ) -> Any:
        return self._request(
            "POST",
            f"/api/v1/changes/{change_id}/recovery/{plan_id}/execute",
            json_body={"actor_id": str(actor_id), "approval_token": approval_token},
        )

    def get_latest_recovery(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/recovery")

    # -- passport --
    def build_passport(self, change_id: UUID) -> Any:
        return self._request("POST", f"/api/v1/changes/{change_id}/passport")

    def get_latest_passport(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/passport")

    # -- evidence, agents, assurance (Person 2 stream) --
    def get_evidence(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/evidence")

    def capture_baseline(self, change_id: UUID, *, idempotency_key: str | None = None) -> Any:
        return self._request("POST", f"/api/v1/changes/{change_id}/evidence/baseline",
                             idempotency_key=idempotency_key, timeout_seconds=120)

    def capture_current_evidence(
        self, change_id: UUID, *, idempotency_key: str | None = None
    ) -> Any:
        return self._request("POST", f"/api/v1/changes/{change_id}/evidence/current",
                             idempotency_key=idempotency_key, timeout_seconds=120)

    def list_checkpoints(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/git/checkpoints")

    def compare_checkpoints(self, change_id: UUID, baseline_id: UUID, current_id: UUID) -> Any:
        return self._request(
            "GET", f"/api/v1/changes/{change_id}/git/compare"
                   f"?baseline_id={baseline_id}&current_id={current_id}")

    def get_environment(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/environment")

    def get_dependencies(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/dependencies")

    def list_agent_adapters(self) -> Any:
        return self._request("GET", "/api/v1/agents/adapters")

    def list_agent_runs(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/agents")

    def launch_agent(
        self,
        change_id: UUID,
        *,
        actor_id: UUID,
        executable: str,
        args: list[str],
        adapter: str = "generic",
        environment_keys: list[str] | None = None,
        timeout_seconds: int = 900,
        output_limit_bytes: int = 200_000,
        idempotency_key: str | None = None,
    ) -> Any:
        # The API call blocks for as long as the agent runs, so the HTTP wait
        # must outlast the agent's own timeout.
        return self._request(
            "POST",
            f"/api/v1/changes/{change_id}/agents/launch",
            json_body={
                "actor_id": str(actor_id),
                "launch": {
                    "adapter": adapter,
                    "executable": executable,
                    "args": args,
                    "environment_keys": environment_keys or [],
                    "timeout_seconds": timeout_seconds,
                },
                "output_limit_bytes": output_limit_bytes,
            },
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds + 60,
        )

    def attach_agent(
        self, change_id: UUID, *, actor_id: UUID, adapter: str, external_run_id: str,
        idempotency_key: str | None = None,
    ) -> Any:
        return self._request(
            "POST",
            f"/api/v1/changes/{change_id}/agents/attach",
            json_body={"actor_id": str(actor_id),
                       "attach": {"adapter": adapter, "external_run_id": external_run_id}},
            idempotency_key=idempotency_key,
        )

    def stop_agent(self, change_id: UUID, run_id: UUID, *, actor_id: UUID) -> Any:
        return self._request(
            "POST", f"/api/v1/changes/{change_id}/agents/{run_id}/stop",
            json_body={"actor_id": str(actor_id)}, timeout_seconds=30)

    def plan_assurance(self, change_id: UUID, *, idempotency_key: str | None = None) -> Any:
        return self._request("POST", f"/api/v1/changes/{change_id}/assurance/plan",
                             idempotency_key=idempotency_key, timeout_seconds=120)

    def get_assurance_plan(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/assurance/plan")

    def run_assurance(
        self, change_id: UUID, plan_id: UUID, *, actor_id: UUID,
        output_limit_bytes: int = 200_000, wait_seconds: int = 900,
        idempotency_key: str | None = None,
    ) -> Any:
        return self._request(
            "POST", f"/api/v1/changes/{change_id}/assurance/{plan_id}/run",
            json_body={"actor_id": str(actor_id), "output_limit_bytes": output_limit_bytes},
            idempotency_key=idempotency_key, timeout_seconds=wait_seconds)

    def evaluate_assurance(self, change_id: UUID, plan_id: UUID) -> Any:
        return self._request(
            "GET", f"/api/v1/changes/{change_id}/assurance/{plan_id}/evaluation",
            timeout_seconds=120)

    def assurance_facts(self, change_id: UUID) -> Any:
        return self._request("GET", f"/api/v1/changes/{change_id}/assurance/facts",
                             timeout_seconds=120)
