"""Change use cases composed over frozen adapter ports."""

from __future__ import annotations

from uuid import UUID, uuid4

from backend.app.contracts.models import (
    ChangeCreateRequest,
    ChangeListResponse,
    ChangeView,
    RepositoryInfo,
    ReviewState,
    VerificationRequest,
    utc_now,
)
from backend.app.contracts.ports import GitInspectionPort, VerificationPort
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.config import Settings
from backend.app.core.errors import change_not_found
from backend.app.core.review_service import determine_review_state


class ChangeService:
    def __init__(
        self,
        repository: ChangeRepository,
        git_inspection: GitInspectionPort,
        verification: VerificationPort,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.git_inspection = git_inspection
        self.verification = verification
        self.settings = settings

    def validate_repository(self, path: str) -> RepositoryInfo:
        return self.git_inspection.validate_repository(path)

    def create(self, request: ChangeCreateRequest) -> ChangeView:
        repository_info = self.git_inspection.validate_repository(request.repository_path)
        now = utc_now()
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
            )
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

    def refresh(self, change_id: UUID) -> ChangeView:
        stored = self._get_stored(change_id)
        summary = self.git_inspection.inspect(
            stored.repository_path, self.settings.patch_limit_bytes
        )
        updated = self.repository.update_git_summary(change_id, summary, utc_now())
        if updated is None:
            raise change_not_found(str(change_id))
        return self._to_view(updated)

    def verify(
        self, change_id: UUID, request: VerificationRequest
    ) -> ChangeView:
        stored = self._get_stored(change_id)
        result = self.verification.run(
            stored.repository_path,
            request,
            self.settings.verification_output_limit_bytes,
        )
        updated = self.repository.update_verification(change_id, result, utc_now())
        if updated is None:
            raise change_not_found(str(change_id))
        return self._to_view(updated)

    def delete(self, change_id: UUID) -> None:
        if not self.repository.delete(change_id):
            raise change_not_found(str(change_id))

    def _get_stored(self, change_id: UUID) -> StoredChange:
        stored = self.repository.get(change_id)
        if stored is None:
            raise change_not_found(str(change_id))
        return stored

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
        )

