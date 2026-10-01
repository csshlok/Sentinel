"""A ``GitStatePort`` that refuses to describe a repository whose agent work is still unapplied.

Invariant: evidence collectors are read-only. Only a previewed, approved action
mutates a user repository: recovery execute or workspace apply-back. The
workspace is Sentinel-owned scratch space, not a user repository.

With an AppContainer workspace the agent edits a clone, so until apply-back the
user repository is untouched. A current, evaluation or diff-gate capture taken
then would describe the base commit -- the checks would run against code the
agent never changed and assurance could PASS on evidence that says nothing
about the agent's work (a vacuous PASS). This tracker refuses those captures
with ``WORKSPACE_NOT_APPLIED`` while the Change's workspace may hold unapplied
work; baseline capture is never blocked, and ``compare``/``is_current`` are
unchanged. It is injected through ``EvidenceService(git_state=...)``, so the
evidence collectors themselves are not modified.
"""

from __future__ import annotations

from uuid import UUID

from backend.app.contracts.models import GitCheckpoint
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.state import GitStateTracker
from backend.app.workspace.errors import workspace_not_applied
from backend.app.workspace.manager import WorkspaceManager

BASELINE_CAPTURE = "baseline"


class WorkspaceGuardedGitState(GitStateTracker):
    """``GitStateTracker`` whose non-baseline captures require applied (or no) workspace work."""

    def __init__(
        self, manager: WorkspaceManager, inspector: GitRepositoryInspector | None = None,
    ) -> None:
        super().__init__(inspector)
        self._manager = manager

    def capture(
        self, change_id: UUID, name: str, repository_path: str,
        evidence_revision: int, patch_limit_bytes: int,
    ) -> GitCheckpoint:
        if name != BASELINE_CAPTURE and self._manager.unapplied_work(change_id):
            raise workspace_not_applied()
        return super().capture(change_id, name, repository_path, evidence_revision,
                               patch_limit_bytes)
