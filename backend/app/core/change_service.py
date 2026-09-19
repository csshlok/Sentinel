"""Change use cases over frozen ports and transactional persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    CapabilitiesResponse,
    ChangeCancelRequest,
    ChangeContractUpdateRequest,
    ChangeCreateRequest,
    ChangeLifecycleState,
    ChangeListResponse,
    ChangeTransitionRequest,
    ChangeView,
    LifecycleFacts,
    RepositoryInfo,
    VerificationRequest,
    utc_now,
)
from backend.app.contracts.ports import (
    GitInspectionPort,
    LifecycleFactsPort,
    PolicyPort,
    VerificationPort,
)
from backend.app.core.capabilities import build_capabilities
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.config import Settings
from backend.app.core.errors import change_not_found, policy_denied
from backend.app.core.lifecycle import validate_transition
from backend.app.core.review_service import determine_review_state


Clock = Callable[[], datetime]


class ChangeService:
    def __init__(
        self,
        repository: ChangeRepository,
        git_inspection: GitInspectionPort,
        verification: VerificationPort,
        lifecycle_facts: LifecycleFactsPort,
        settings: Settings,
        *,
        policy: PolicyPort | None = None,
        configured_capabilities: set[str] | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.repository = repository
        self.git_inspection = git_inspection
        self.verification = verification
        self.lifecycle_facts = lifecycle_facts
        self.settings = settings
        self.policy = policy
        self.configured_capabilities = configured_capabilities or {
            "change_lifecycle",
            "git_inspection",
            "legacy_verification",
        }
        self.clock = clock

    def capabilities(self) -> CapabilitiesResponse:
        return build_capabilities(self.configured_capabilities)

    def validate_repository(self, path: str) -> RepositoryInfo:
        return self.git_inspection.validate_repository(path)

    def create(
        self, request: ChangeCreateRequest, *, idempotency_key: str | None = None
    ) -> ChangeView:
        request_hash = self._request_hash(request)
        replay = self.repository.replay(
            "changes:create", idempotency_key, request_hash
        )
        if isinstance(replay, StoredChange):
            return self._to_view(replay)
        repository_info = self.git_inspection.validate_repository(request.repository_path)
        now = self.clock()
        stored = self.repository.create(
            StoredChange(
                id=uuid4(),
                title=request.title,
                intent=request.intent,
                repository_path=repository_info.root,
                created_at=now,
                updated_at=now,
                last_refreshed_at=None,
                git_summary=None,
                verification=None,
                contract=request.contract,
            ),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        return self._to_view(stored)

    def list(self, *, limit: int, offset: int) -> ChangeListResponse:
        changes = [
            self._to_view(item)
            for item in self.repository.list(limit=limit, offset=offset)
        ]
        return ChangeListResponse(items=changes, count=len(changes))

    def get(self, change_id: UUID) -> ChangeView:
        return self._to_view(self._get_stored(change_id))

    def update_contract(
        self,
        change_id: UUID,
        request: ChangeContractUpdateRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ChangeView:
        updated = self.repository.update_contract(
            change_id,
            request.contract,
            request.expected_revision,
            self.clock(),
            idempotency_key=idempotency_key,
            request_hash=self._request_hash(request),
        )
        if updated is None:
            raise change_not_found(str(change_id))
        return self._to_view(updated)

    def transition(
        self,
        change_id: UUID,
        request: ChangeTransitionRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ChangeView:
        request_hash = self._request_hash(request)
        scope = f"change:{change_id}:transition"
        replay = self.repository.replay(scope, idempotency_key, request_hash)
        if isinstance(replay, StoredChange):
            return self._to_view(replay)

        stored = self._get_stored(change_id)
        if request.target_state in {
            stored.lifecycle_state,
            ChangeLifecycleState.CANCELLED,
            ChangeLifecycleState.PAUSED,
            ChangeLifecycleState.BLOCKED,
            ChangeLifecycleState.FAILED,
            ChangeLifecycleState.RECOVERY_PENDING,
        }:
            facts = LifecycleFacts()
        else:
            facts = self.lifecycle_facts.get_facts(
                self._to_view(stored), request.target_state.value
            )
        validate_transition(stored.lifecycle_state, request.target_state, facts)
        updated = self.repository.transition(
            change_id,
            request.target_state,
            request.expected_revision,
            self.clock(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            reason=request.reason,
        )
        if updated is None:
            raise change_not_found(str(change_id))
        return self._to_view(updated)

    def cancel(
        self,
        change_id: UUID,
        request: ChangeCancelRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ChangeView:
        return self.transition(
            change_id,
            ChangeTransitionRequest(
                target_state=ChangeLifecycleState.CANCELLED,
                expected_revision=request.expected_revision,
                reason=request.reason,
            ),
            idempotency_key=idempotency_key,
        )

    def refresh(
        self, change_id: UUID, *, idempotency_key: str | None = None
    ) -> ChangeView:
        request_hash = self._request_hash({"change_id": str(change_id)})
        scope = f"change:{change_id}:legacy-git-refresh"
        replay = self.repository.replay(scope, idempotency_key, request_hash)
        if isinstance(replay, StoredChange):
            return self._to_view(replay)
        stored = self._get_stored(change_id)
        summary = self.git_inspection.inspect(
            stored.repository_path, self.settings.patch_limit_bytes
        )
        updated = self.repository.update_git_summary(
            change_id,
            summary,
            self.clock(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if updated is None:
            raise change_not_found(str(change_id))
        return self._to_view(updated)

    def verify(
        self,
        change_id: UUID,
        actor_id: UUID,
        request: VerificationRequest,
        *,
        idempotency_key: str | None = None,
    ) -> ChangeView:
        request_hash = self._request_hash(request)
        scope = f"change:{change_id}:legacy-verification"
        replay = self.repository.replay(scope, idempotency_key, request_hash)
        if isinstance(replay, StoredChange):
            # An exact replay of an already-completed request returns the
            # stored result without re-authorizing, matching the fix for the
            # same double-consumption class of bug in
            # EvidenceAdminService._once: this early return already runs
            # before any authorization check, so it inherits that property
            # rather than needing its own copy of it.
            return self._to_view(replay)
        stored = self._get_stored(change_id)
        change_view = self._to_view(stored)
        if self.policy is None:
            # Fail closed rather than silently skip authorization: this
            # executes an arbitrary allowlisted command against the
            # repository, exactly like the delegation-gated agent-launch
            # and assurance-run routes, and must never run unauthorized.
            raise policy_denied(
                "POLICY_UNAVAILABLE",
                "Legacy verification is unavailable because no policy engine is configured.",
            )
        decision = self.policy.evaluate(actor_id, change_view, "change.legacy_verify", {})
        if not decision.allowed:
            raise policy_denied(decision.reason_code, decision.explanation)
        result = self.verification.run(
            stored.repository_path,
            request,
            self.settings.verification_output_limit_bytes,
        )
        updated = self.repository.update_verification(
            change_id,
            result,
            self.clock(),
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if updated is None:
            raise change_not_found(str(change_id))
        return self._to_view(updated)

    def delete(
        self, change_id: UUID, *, idempotency_key: str | None = None
    ) -> None:
        request_hash = self._request_hash({"change_id": str(change_id)})
        if not self.repository.delete(
            change_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        ):
            raise change_not_found(str(change_id))

    def _get_stored(self, change_id: UUID) -> StoredChange:
        stored = self.repository.get(change_id)
        if stored is None:
            raise change_not_found(str(change_id))
        return stored

    @staticmethod
    def _request_hash(value: object) -> str:
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="json")  # type: ignore[attr-defined]
        else:
            payload = value
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _to_view(stored: StoredChange) -> ChangeView:
        return ChangeView(
            id=stored.id,
            title=stored.title,
            intent=stored.intent,
            repository_path=stored.repository_path,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
            last_refreshed_at=stored.last_refreshed_at,
            git_summary=stored.git_summary,
            verification=stored.verification,
            review_state=determine_review_state(
                stored.git_summary, stored.verification
            ),
            lifecycle_state=stored.lifecycle_state,
            revision=stored.revision,
            contract=stored.contract,
            risk_level=stored.risk_level,
            evidence_revision=stored.evidence_revision,
            verification_evidence_revision=stored.verification_evidence_revision,
            last_transition_at=stored.last_transition_at,
        )
