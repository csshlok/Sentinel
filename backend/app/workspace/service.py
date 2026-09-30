"""Request-scoped use cases for a Change's Sentinel-owned workspace (show/preview/apply/discard/sweep).

Apply-back is the only path by which workspace content reaches the user's
repository, so it is previewed (approval token bound to ``(base_sha,
sealed_sha)``), policy-gated (``workspace.apply``, risk MEDIUM) and idempotent:
a replay of an applied request returns the stored outcome before any policy
evaluation or Git call, so it never spends a second delegation use. Discarding
unapplied agent work needs ``workspace.discard``. Denials are journaled as
``policy.decision.denied``. Show, preview and sweep need only the API bearer
token, like the other read and evidence-capture routes; preview never touches
the user's repository beyond reading its branch and HEAD.
"""

from __future__ import annotations

from uuid import UUID

from backend.app.contracts.models import (
    ChangeView,
    ChangeWorkspace,
    JournalEventType,
    WorkspaceActionRequest,
    WorkspaceApplyPreview,
    WorkspaceApplyRequest,
    WorkspaceApplyResult,
    WorkspaceState,
    WorkspaceSweepReport,
)
from backend.app.contracts.ports import PolicyPort
from backend.app.core.change_service import ChangeService
from backend.app.core.errors import AppError, policy_denied
from backend.app.core.journal import JournalWriter
from backend.app.workspace.errors import workspace_approval_invalid, workspace_not_found
from backend.app.workspace.manager import WorkspaceManager
from backend.app.workspace.models import (
    WorkspaceRecord,
    preview_to_contract,
    record_to_contract,
    sweep_to_contract,
)

WORKSPACE_APPLY_SCOPE = "workspace.apply"
WORKSPACE_DISCARD_SCOPE = "workspace.discard"
WORKSPACE_APPLY_RISK = "MEDIUM"


class WorkspaceService:
    def __init__(
        self, manager: WorkspaceManager, policy: PolicyPort, change_service: ChangeService,
        *, journal: JournalWriter | None = None,
    ) -> None:
        self.manager = manager
        self.policy = policy
        self.change_service = change_service
        self._journal = journal

    def _authorize(self, actor_id: UUID, change: ChangeView, operation: str,
                   parameters: dict[str, object]) -> None:
        decision = self.policy.evaluate(actor_id, change, operation, parameters)
        if not decision.allowed:
            if self._journal is not None:
                self._journal.append(
                    change.id, JournalEventType.POLICY_DECISION_DENIED,
                    actor_id=actor_id, subject_type="policy_operation",
                    payload={"operation": operation, "denial_reason": decision.reason_code},
                )
            raise policy_denied(decision.reason_code, decision.explanation)

    def _latest(self, change_id: UUID) -> WorkspaceRecord:
        record = self.manager.latest_for_change(change_id)
        if record is None:
            raise workspace_not_found(str(change_id))
        return record

    def show(self, change_id: UUID) -> ChangeWorkspace:
        """The Change's live workspace, else its most recent one (kept after cleanup)."""

        self.change_service.get(change_id)
        return record_to_contract(self._latest(change_id))

    def preview(self, change_id: UUID) -> WorkspaceApplyPreview:
        self.change_service.get(change_id)
        return preview_to_contract(self.manager.preview(change_id))

    def apply(self, change_id: UUID, request: WorkspaceApplyRequest) -> WorkspaceApplyResult:
        change = self.change_service.get(change_id)
        record = self._latest(change_id)
        if record.applied_sha and record.state in (WorkspaceState.APPLIED,
                                                   WorkspaceState.CLEANED):
            # Replay of an applied request: the stored outcome, with no policy
            # evaluation (no delegation use is spent) and no Git call. The token
            # must still be the one that was approved.
            if not self.manager.approval_matches(record, request.approval_token):
                raise workspace_approval_invalid()
            if record.state == WorkspaceState.APPLIED:
                try:  # finish an interrupted cleanup; removal only, never Git
                    record = self.manager.cleanup(record.id, reason="applied")
                except AppError:
                    record = self.manager.get(record.id)
            return WorkspaceApplyResult(workspace=record_to_contract(record), applied=True)
        self._authorize(request.actor_id, change, WORKSPACE_APPLY_SCOPE, {
            "risk_level": WORKSPACE_APPLY_RISK, "sealed_sha": record.sealed_sha or ""})
        updated = self.manager.apply(change_id, request.approval_token)
        if updated.applied_sha and updated.state in (WorkspaceState.APPLIED,
                                                     WorkspaceState.CLEANED):
            return WorkspaceApplyResult(workspace=record_to_contract(updated), applied=True)
        preview: WorkspaceApplyPreview | None = None
        try:
            preview = preview_to_contract(self.manager.inspect(change_id))
        except AppError:
            preview = None  # the refusal itself is still reported on the workspace
        return WorkspaceApplyResult(
            workspace=record_to_contract(self.manager.get(updated.id)), applied=False,
            preview=preview,
        )

    def discard(self, change_id: UUID, request: WorkspaceActionRequest) -> ChangeWorkspace:
        change = self.change_service.get(change_id)
        self._latest(change_id)  # 404 before a delegation use is spent
        self._authorize(request.actor_id, change, WORKSPACE_DISCARD_SCOPE, {})
        return record_to_contract(self.manager.discard(change_id))

    def sweep(self) -> WorkspaceSweepReport:
        return sweep_to_contract(self.manager.sweep())
