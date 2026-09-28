"""Internal records for Sentinel-owned AppContainer workspaces (not wire contracts)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.app.contracts.models import WorkspaceState


class ApplyRefusal(StrEnum):
    USER_BRANCH_MOVED = "USER_BRANCH_MOVED"
    USER_BRANCH_SWITCHED = "USER_BRANCH_SWITCHED"
    FAST_FORWARD_REFUSED = "FAST_FORWARD_REFUSED"
    SEALED_COMMIT_MISMATCH = "SEALED_COMMIT_MISMATCH"
    USER_HEAD_DETACHED = "USER_HEAD_DETACHED"
    WORKSPACE_HISTORY_DIVERGED = "WORKSPACE_HISTORY_DIVERGED"
    # The sealed diff carries the staged model credential (research Pitfall 8).
    CREDENTIAL_IN_DIFF = "CREDENTIAL_IN_DIFF"
    # A credential was staged and the diff is too large to scan completely (fail closed).
    DIFF_TOO_LARGE_TO_SCAN = "DIFF_TOO_LARGE_TO_SCAN"


# Preview bounds (threat T-01-25: excess is reported as truncated, never loaded).
PREVIEW_PATCH_LIMIT = 262_144
PREVIEW_COMMIT_LIMIT = 256
# Bound of the patch scanned for staged-credential material (threat T-01-38).
SECRET_SCAN_LIMIT = 8 * 1_048_576
# Path flag of a changed path that carries staged-credential material.
CREDENTIAL_FLAG = "credential"

SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"

# Path-risk rules (product plan section 4.3). Matching is case-insensitive
# because the user's checkout is on a case-insensitive Windows file system.
GIT_METADATA_NAMES = frozenset({".gitattributes", ".gitmodules"})
HOOKS_LIKE_PREFIXES = (".husky/", ".githooks/")
EXECUTION_BEARING_NAMES = frozenset({
    "package.json", "conftest.py", "setup.py", "setup.cfg", "pyproject.toml",
    "makefile", "gnumakefile",
})
EXECUTION_BEARING_PATHS = frozenset({".vscode/tasks.json"})
EXECUTION_BEARING_PREFIXES = (".github/workflows/",)
EXECUTION_BEARING_SUFFIXES = (".ps1", ".bat", ".cmd")


def path_flags(path: str, old_mode: str, new_mode: str) -> tuple[str, ...]:
    """Risk classes of one changed path (empty when it is an ordinary file)."""

    lowered = path.replace("\\", "/").lower()
    name = lowered.rsplit("/", 1)[-1]
    flags: list[str] = []
    if SYMLINK_MODE in (old_mode, new_mode):
        flags.append("symlink")
    if GITLINK_MODE in (old_mode, new_mode):
        flags.append("gitlink")
    if name in GIT_METADATA_NAMES:
        flags.append("git-metadata")
    if lowered.startswith(HOOKS_LIKE_PREFIXES):
        flags.append("hooks-like")
    if (name in EXECUTION_BEARING_NAMES or lowered in EXECUTION_BEARING_PATHS
            or lowered.startswith(EXECUTION_BEARING_PREFIXES)
            or lowered.endswith(EXECUTION_BEARING_SUFFIXES)):
        flags.append("execution-bearing")
    return tuple(flags)


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    """One workspace clone and its AppContainer profile, as persisted.

    ``approval_digest`` is the sha256 hex digest of the apply-back approval
    token; the raw token is only ever returned in :class:`ApplyPreview`.
    """

    id: UUID
    change_id: UUID
    state: WorkspaceState
    profile_name: str
    created_at: datetime
    updated_at: datetime
    package_sid: str | None = None
    container_path: Path | None = None
    workspace_path: Path | None = None
    source_repository: Path | None = None
    base_branch: str | None = None
    base_sha: str | None = None
    sealed_sha: str | None = None
    applied_sha: str | None = None
    refusal_reason: str | None = None
    approval_digest: str | None = None
    approved_base_sha: str | None = None
    approved_sealed_sha: str | None = None
    active_run_id: str | None = None
    runs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    cleaned_at: datetime | None = None
    # Digest-only fingerprints of credentials staged for runs (never the secret).
    credential_fingerprints: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "change_id": str(self.change_id),
            "state": self.state.value,
            "profile_name": self.profile_name,
            "package_sid": self.package_sid,
            "container_path": str(self.container_path) if self.container_path else None,
            "workspace_path": str(self.workspace_path) if self.workspace_path else None,
            "source_repository": str(self.source_repository) if self.source_repository else None,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "sealed_sha": self.sealed_sha,
            "applied_sha": self.applied_sha,
            "refusal_reason": self.refusal_reason,
            "approval_digest": self.approval_digest,
            "approved_base_sha": self.approved_base_sha,
            "approved_sealed_sha": self.approved_sealed_sha,
            "active_run_id": self.active_run_id,
            "runs": [dict(run) for run in self.runs],
            "limitations": list(self.limitations),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "cleaned_at": self.cleaned_at.isoformat() if self.cleaned_at else None,
            "credential_fingerprints": [dict(item) for item in self.credential_fingerprints],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> WorkspaceRecord:
        return cls(
            id=UUID(payload["id"]),
            change_id=UUID(payload["change_id"]),
            state=WorkspaceState(payload["state"]),
            profile_name=payload["profile_name"],
            package_sid=payload.get("package_sid"),
            container_path=_path(payload.get("container_path")),
            workspace_path=_path(payload.get("workspace_path")),
            source_repository=_path(payload.get("source_repository")),
            base_branch=payload.get("base_branch"),
            base_sha=payload.get("base_sha"),
            sealed_sha=payload.get("sealed_sha"),
            applied_sha=payload.get("applied_sha"),
            refusal_reason=payload.get("refusal_reason"),
            approval_digest=payload.get("approval_digest"),
            approved_base_sha=payload.get("approved_base_sha"),
            approved_sealed_sha=payload.get("approved_sealed_sha"),
            active_run_id=payload.get("active_run_id"),
            runs=tuple(dict(run) for run in payload.get("runs") or ()),
            limitations=tuple(payload.get("limitations") or ()),
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            cleaned_at=_time(payload.get("cleaned_at")),
            credential_fingerprints=tuple(
                dict(item) for item in payload.get("credential_fingerprints") or ()),
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> WorkspaceRecord:
        payload = json.loads(row["payload_json"])
        # The indexed columns are authoritative for state and the active run.
        payload["state"] = row["state"]
        payload["active_run_id"] = row["active_run_id"]
        return cls.from_payload(payload)


@dataclass(frozen=True, slots=True)
class SweepReport:
    """Outcome of one DB-driven sweep: cleaned rows, preserved (unapplied) rows, failures."""

    cleaned: tuple[UUID, ...] = ()
    preserved: tuple[UUID, ...] = ()
    failed: tuple[tuple[UUID, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ApplyPreview:
    """What apply-back would land; ``approval_token`` is returned only here.

    ``commits`` holds ``(sha, author, subject)``; ``changed_paths`` holds
    ``(status, path, old_mode, new_mode, flags)``. ``approval_token`` is None
    whenever apply could not succeed (``refusal_reason`` says why).
    """

    change_id: UUID
    workspace_id: UUID
    base_sha: str
    sealed_sha: str
    commits: tuple[tuple[str, str, str], ...]
    changed_paths: tuple[tuple[str, str, str, str, tuple[str, ...]], ...]
    approval_token: str | None
    refusal_reason: str | None = None
    user_branch: str | None = None
    user_head: str | None = None
    fast_forward_possible: bool = False
    patch: str = ""
    patch_truncated: bool = False
    commits_truncated: bool = False
    limitations: tuple[str, ...] = ()
