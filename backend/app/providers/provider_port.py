"""Adapts `GitHubProvider` to the frozen `ProviderPort`."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backend.app.contracts.models import (
    CredentialGrant,
    ProviderOperation,
    ProviderOperationRequest,
    ProviderOperationStatus,
)
from backend.app.core.errors import AppError
from backend.app.credentials.broker import CredentialBroker
from backend.app.providers.github import GitHubProvider


class GitHubProviderAdapter:
    """Implements `backend.app.contracts.ports.ProviderPort`."""

    def __init__(self, github: GitHubProvider, broker: CredentialBroker) -> None:
        self.github = github
        self.broker = broker

    def execute(
        self, request: ProviderOperationRequest, grant: CredentialGrant
    ) -> ProviderOperation:
        started_at = datetime.now(UTC)
        try:
            token = self.broker.resolve_secret(grant.id, scope=request.operation)
        except AppError as error:
            return self._result(
                request,
                ProviderOperationStatus.DENIED,
                started_at,
                safe_metadata={"error_code": error.code},
            )

        if request.operation == "github.pr.create":
            return self._create_pull_request(request, token, started_at)
        if request.operation == "github.pr.close":
            return self._close_pull_request(request, token, started_at)

        return self._result(
            request,
            ProviderOperationStatus.DENIED,
            started_at,
            safe_metadata={"reason": f"unsupported operation '{request.operation}'"},
        )

    def _create_pull_request(
        self, request: ProviderOperationRequest, token: str, started_at: datetime
    ) -> ProviderOperation:
        try:
            outcome = self.github.create_or_refresh_pull_request(
                token=token,
                repository=request.parameters["repository"],
                base_branch=request.parameters["base_branch"],
                head_branch=request.parameters["head_branch"],
                title=request.parameters.get("title", "Change Assurance pull request"),
                idempotency_key=request.idempotency_key,
            )
        except AppError as error:
            return self._result(
                request,
                ProviderOperationStatus.FAILED,
                started_at,
                safe_metadata={"error_code": error.code},
            )
        except KeyError as error:
            return self._result(
                request,
                ProviderOperationStatus.FAILED,
                started_at,
                safe_metadata={
                    "error_code": "PROVIDER_VALIDATION_FAILED",
                    "missing_parameter": str(error),
                },
            )

        return self._result(
            request,
            ProviderOperationStatus.SUCCEEDED,
            started_at,
            provider_reference=outcome.url,
            safe_metadata={
                "number": outcome.number,
                "head_sha": outcome.head_sha,
                "state": outcome.state.value,
            },
        )

    def _close_pull_request(
        self, request: ProviderOperationRequest, token: str, started_at: datetime
    ) -> ProviderOperation:
        try:
            outcome = self.github.close_pull_request(
                token=token,
                repository=request.parameters["repository"],
                number=request.parameters["number"],
            )
        except AppError as error:
            return self._result(
                request, ProviderOperationStatus.FAILED, started_at,
                safe_metadata={"error_code": error.code},
            )
        except KeyError as error:
            return self._result(
                request, ProviderOperationStatus.FAILED, started_at,
                safe_metadata={"error_code": "PROVIDER_VALIDATION_FAILED",
                               "missing_parameter": str(error)},
            )
        return self._result(
            request, ProviderOperationStatus.SUCCEEDED, started_at,
            provider_reference=outcome.url,
            safe_metadata={"number": outcome.number, "state": outcome.state.value},
        )

    @staticmethod
    def _result(
        request: ProviderOperationRequest,
        status: ProviderOperationStatus,
        started_at: datetime,
        *,
        provider_reference: str | None = None,
        safe_metadata: dict | None = None,
    ) -> ProviderOperation:
        return ProviderOperation(
            id=uuid4(),
            request=request,
            status=status,
            provider_reference=provider_reference,
            safe_metadata=safe_metadata or {},
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
