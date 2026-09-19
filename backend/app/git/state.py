"""Persistable Git checkpoints and comparison (``GitStatePort``).

Capture is read-only and reuses the hardened inspector. The digest covers the
repository identity, HEAD, branch, every changed-path record and the bounded
patch prefix, but never capture time, so identical repository states yield
identical digests. Repeated reads detect observed movement; they are not an
atomic filesystem snapshot.

Unborn repositories (no commit) are rejected with a stable error because the
frozen ``GitCheckpoint`` needs a HEAD identity; detached HEAD is represented by
``branch is None``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    ChangedPath, ChangedPathStatus, GitCheckpoint, GitCheckpointComparison, GitSummary, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.git.adapter import PATCH_LIMIT, GitRepositoryInspector


def _record(entry: ChangedPath) -> list[object]:
    return [entry.path, entry.old_path, entry.status.value, entry.staged,
            entry.unstaged, entry.additions, entry.deletions, entry.binary]


UNTRACKED_FILE_LIMIT = 8 * 1_048_576
UNTRACKED_FILE_COUNT = 2000


def _untracked_content(root: str, files: list[ChangedPath]) -> dict[str, str]:
    """Content digests for untracked files, which the patch omits.

    Read-only, bounded and symlink-safe: symlinks and non-regular files are
    recorded by kind, oversized files by size only.
    """

    result: dict[str, str] = {}
    base = Path(root)
    untracked = [f.path for f in files if f.status is ChangedPathStatus.UNTRACKED]
    for index, rel in enumerate(sorted(untracked)):
        if index >= UNTRACKED_FILE_COUNT:
            result["<more>"] = str(len(untracked))
            break
        target = base / rel
        try:
            if target.is_symlink():
                result[rel] = "symlink"
            elif not target.is_file():
                result[rel] = "special"
            else:
                size = target.stat().st_size
                if size > UNTRACKED_FILE_LIMIT:
                    result[rel] = f"oversize:{size}"
                else:
                    result[rel] = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            result[rel] = "unreadable"
    return result


def summary_digest(summary: GitSummary, *, untracked: dict[str, str] | None = None) -> str:
    """Deterministic SHA-256 over identity and content, excluding time.

    ``untracked`` maps untracked paths to content digests so edits to files
    that Git does not yet track change the digest.
    """

    body = {
        "root": summary.repository_root,
        "branch": summary.branch,
        "head": summary.head_sha.lower(),
        "files": sorted((_record(f) for f in summary.files), key=lambda r: r[0]),
        "additions": summary.total_additions,
        "deletions": summary.total_deletions,
        "untracked_patch_omitted": summary.untracked_patch_omitted,
        "untracked_content": sorted((untracked or {}).items()),
        "patch_sha256": hashlib.sha256(summary.patch.encode("utf-8")).hexdigest(),
        "patch_truncated": summary.patch_truncated,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class GitStateTracker:
    """Concrete ``GitStatePort``."""

    def __init__(self, inspector: GitRepositoryInspector | None = None) -> None:
        self._inspector = inspector or GitRepositoryInspector()

    def capture(
        self, change_id: UUID, name: str, repository_path: str,
        evidence_revision: int, patch_limit_bytes: int,
    ) -> GitCheckpoint:
        if type(evidence_revision) is not int or evidence_revision < 1:
            raise AppError("INVALID_EVIDENCE_REVISION",
                           "The evidence revision must be a positive integer.")
        if type(patch_limit_bytes) is not int or not 0 <= patch_limit_bytes <= PATCH_LIMIT:
            raise AppError("INVALID_PATCH_LIMIT",
                           "The patch limit must be between zero and one MiB.")
        summary = self._inspector.inspect(repository_path, patch_limit_bytes)
        return GitCheckpoint(
            id=uuid4(), change_id=change_id, name=name,
            repository_root=summary.repository_root, branch=summary.branch,
            head_sha=summary.head_sha, status_digest=summary_digest(
                summary, untracked=_untracked_content(summary.repository_root, summary.files)),
            summary=summary, evidence_revision=evidence_revision,
            captured_at=utc_now(),
        )

    def compare(
        self, baseline: GitCheckpoint, current: GitCheckpoint
    ) -> GitCheckpointComparison:
        if baseline.repository_root != current.repository_root:
            raise AppError("CHECKPOINT_REPOSITORY_MISMATCH",
                           "Checkpoints belong to different repositories.", status_code=409)
        before = {f.path: _record(f) for f in baseline.summary.files}
        after = {f.path: _record(f) for f in current.summary.files}
        return GitCheckpointComparison(
            baseline_id=baseline.id, current_id=current.id,
            branch_moved=baseline.branch != current.branch,
            head_changed=baseline.head_sha.lower() != current.head_sha.lower(),
            added_paths=sorted(set(after) - set(before)),
            removed_paths=sorted(set(before) - set(after)),
            changed_paths=sorted(p for p in set(before) & set(after) if before[p] != after[p]),
        )

    def is_current(
        self, checkpoint: GitCheckpoint, repository_path: str | None = None,
        patch_limit_bytes: int | None = None,
    ) -> bool:
        """True only if a fresh capture reproduces the checkpoint's digest.

        Freshness input for lifecycle gating: any repository movement, including
        edits to untracked files, makes earlier evidence stale. A truncated patch
        cannot be re-derived without its original limit, so without
        ``patch_limit_bytes`` such a checkpoint is conservatively reported stale.
        """

        path = repository_path or checkpoint.repository_root
        if patch_limit_bytes is None:
            if checkpoint.summary.patch_truncated:
                return False
            patch_limit_bytes = len(checkpoint.summary.patch.encode("utf-8"))
        fresh = self._inspector.inspect(path, patch_limit_bytes)
        digest = summary_digest(
            fresh, untracked=_untracked_content(fresh.repository_root, fresh.files))
        return digest == checkpoint.status_digest
