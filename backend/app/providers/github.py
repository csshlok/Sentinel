"""GitHub provider adapter: brokered calls only.

This module never reads a credential store or logs a token. Callers
pass an already-resolved bearer token (from
`backend.app.credentials.broker.CredentialBroker.resolve_secret`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from backend.app.providers.errors import (
    provider_auth_failed,
    provider_conflict,
    provider_not_found,
    provider_rate_limited,
    provider_timeout,
    provider_unavailable,
    provider_validation_failed,
)
from backend.app.providers.http_transport import (
    HttpResponse,
    HttpTransport,
    TransportTimeout,
)
from backend.app.providers.models import (
    CheckConclusion,
    CheckRunOutcome,
    PullRequestOutcome,
    PullRequestState,
)

_CONCLUSION_MAP: dict[str, CheckConclusion] = {
    "success": CheckConclusion.SUCCESS,
    "failure": CheckConclusion.FAILURE,
    "neutral": CheckConclusion.NEUTRAL,
    "cancelled": CheckConclusion.CANCELLED,
    "timed_out": CheckConclusion.TIMED_OUT,
    "action_required": CheckConclusion.ACTION_REQUIRED,
    "stale": CheckConclusion.STALE,
}


def _map_conclusion(status: str | None, conclusion: str | None) -> CheckConclusion:
    if status != "completed":
        return CheckConclusion.PENDING
    return _CONCLUSION_MAP.get(conclusion or "", CheckConclusion.PENDING)


def _backoff_seconds(attempt: int) -> float:
    return min(2.0 ** (attempt - 1), 30.0)


def _default_clock() -> datetime:
    return datetime.now(UTC)


class GitHubProvider:
    def __init__(
        self,
        transport: HttpTransport,
        *,
        base_url: str = "https://api.github.com",
        max_retries: int = 3,
        retry_sleep: Callable[[float], None] = lambda _seconds: None,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._retry_sleep = retry_sleep
        self._clock = clock
        self._pr_cache: dict[str, PullRequestOutcome] = {}

    def create_or_refresh_pull_request(
        self,
        *,
        token: str,
        repository: str,
        base_branch: str,
        head_branch: str,
        title: str,
        idempotency_key: str,
    ) -> PullRequestOutcome:
        cached = self._pr_cache.get(idempotency_key)
        if cached is not None:
            return cached

        body = json.dumps(
            {"title": title, "head": head_branch, "base": base_branch, "draft": True}
        ).encode("utf-8")
        response = self._request(
            "POST", f"/repos/{repository}/pulls", token=token, body=body
        )
        payload = json.loads(response.body)
        outcome = PullRequestOutcome(
            repository=repository,
            branch=head_branch,
            number=payload["number"],
            url=payload["html_url"],
            head_sha=payload["head"]["sha"],
            state=PullRequestState.DRAFT
            if payload.get("draft")
            else PullRequestState.OPEN,
            observed_at=self._clock(),
        )
        self._pr_cache[idempotency_key] = outcome
        return outcome

    def close_pull_request(
        self, *, token: str, repository: str, number: int
    ) -> PullRequestOutcome:
        """Compensating action for a Change-created PR: close it, never delete

        or force-push the branch. Idempotent at the GitHub API level -- PATCHing
        an already-closed PR to "closed" again just returns its current state.
        """

        body = json.dumps({"state": "closed"}).encode("utf-8")
        response = self._request(
            "PATCH", f"/repos/{repository}/pulls/{number}", token=token, body=body
        )
        payload = json.loads(response.body)
        return PullRequestOutcome(
            repository=repository,
            branch=payload.get("head", {}).get("ref", ""),
            number=payload["number"],
            url=payload["html_url"],
            head_sha=payload["head"]["sha"],
            state=PullRequestState.CLOSED,
            observed_at=self._clock(),
        )

    def list_check_runs_for_sha(
        self, *, token: str, repository: str, head_sha: str
    ) -> list[CheckRunOutcome]:
        results: list[CheckRunOutcome] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                f"/repos/{repository}/commits/{head_sha}/check-runs"
                f"?per_page=50&page={page}",
                token=token,
                body=None,
            )
            payload = json.loads(response.body)
            page_runs = payload.get("check_runs", [])
            for item in page_runs:
                results.append(
                    CheckRunOutcome(
                        name=item["name"],
                        conclusion=_map_conclusion(
                            item.get("status"), item.get("conclusion")
                        ),
                        head_sha=item["head_sha"],
                        observed_at=self._clock(),
                    )
                )
            if len(page_runs) < 50:
                break
            page += 1
        return results

    def _request(
        self, method: str, path: str, *, token: str, body: bytes | None
    ) -> HttpResponse:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.transport.request(
                    method, url, headers=headers, body=body, timeout_seconds=10.0
                )
            except TransportTimeout:
                if attempt > self.max_retries:
                    raise provider_timeout() from None
                self._retry_sleep(_backoff_seconds(attempt))
                continue

            if response.status_code in (200, 201):
                return response
            if response.status_code in (401, 403):
                raise provider_auth_failed(response.status_code)
            if response.status_code == 404:
                raise provider_not_found()
            if response.status_code == 409:
                raise provider_conflict()
            if response.status_code == 422:
                raise provider_validation_failed(_safe_message(response))
            if response.status_code == 429:
                retry_after = _retry_after(response)
                if attempt > self.max_retries:
                    raise provider_rate_limited(retry_after)
                self._retry_sleep(
                    retry_after if retry_after is not None else _backoff_seconds(attempt)
                )
                continue
            if response.status_code >= 500:
                if attempt > self.max_retries:
                    raise provider_unavailable(response.status_code)
                self._retry_sleep(_backoff_seconds(attempt))
                continue
            raise provider_unavailable(response.status_code)


def _safe_message(response: HttpResponse) -> str | None:
    try:
        payload = json.loads(response.body)
    except (ValueError, UnicodeDecodeError):
        return None
    message = payload.get("message") if isinstance(payload, dict) else None
    return message if isinstance(message, str) else None


def _retry_after(response: HttpResponse) -> float | None:
    value = response.headers.get("Retry-After") or response.headers.get(
        "retry-after"
    )
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
