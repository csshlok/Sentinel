"""Read-only, contract-conforming Git repository inspection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.app.contracts.models import (
    ChangedPath, ChangedPathStatus, GitSummary, RepositoryInfo, utc_now,
)
from backend.app.git.classifier import classify_path
from backend.app.git.errors import GitCommandError, RepositoryValidationError


@dataclass(frozen=True, slots=True)
class _DiffStat:
    additions: int | None
    deletions: int | None
    binary: bool


class GitRepositoryInspector:
    """Concrete implementation of the frozen ``GitInspectionPort``."""

    def validate_repository(self, path: str) -> RepositoryInfo:
        root = self._canonical_root(path)
        try:
            head_sha = self._run_git(root, ["rev-parse", "--verify", "HEAD"]).strip()
        except GitCommandError as exc:
            raise RepositoryValidationError(
                "REPOSITORY_HAS_NO_COMMITS",
                "The repository must contain at least one commit.",
            ) from exc
        branch = self._run_git(root, ["branch", "--show-current"]).strip() or None
        return RepositoryInfo(root=root, branch=branch, head_sha=head_sha)

    def inspect(self, path: str, patch_limit_bytes: int) -> GitSummary:
        repository = self.validate_repository(path)
        status_output = self._run_git(
            repository.root,
            ["status", "--porcelain=v2", "-z", "--untracked-files=all"],
        )
        status_entries = self._parse_status(status_output)
        stats = self._parse_numstat(
            self._run_git(
                repository.root, ["diff", "--numstat", "-z", "HEAD", "--"]
            )
        )

        files: list[ChangedPath] = []
        for entry in status_entries:
            stat = stats.get(entry.path)
            files.append(
                entry.model_copy(
                    update={
                        "additions": stat.additions if stat else None,
                        "deletions": stat.deletions if stat else None,
                        "binary": stat.binary if stat else False,
                    }
                )
            )

        total_additions = sum(
            stat.additions or 0 for stat in stats.values() if not stat.binary
        )
        total_deletions = sum(
            stat.deletions or 0 for stat in stats.values() if not stat.binary
        )
        raw_patch = self._run_git(
            repository.root,
            ["diff", "--no-ext-diff", "--no-color", "HEAD", "--"],
        )
        patch, patch_truncated = self._bound_utf8(raw_patch, patch_limit_bytes)
        untracked_patch_omitted = any(
            item.status is ChangedPathStatus.UNTRACKED for item in files
        )
        return GitSummary(
            repository_root=repository.root,
            branch=repository.branch,
            head_sha=repository.head_sha,
            is_clean=not files,
            files=files,
            total_additions=total_additions,
            total_deletions=total_deletions,
            patch=patch,
            patch_truncated=patch_truncated,
            untracked_patch_omitted=untracked_patch_omitted,
            refreshed_at=utc_now(),
        )

    def _canonical_root(self, path: str) -> str:
        candidate = Path(path).expanduser()
        if not candidate.exists() or not candidate.is_dir():
            raise RepositoryValidationError(
                "INVALID_REPOSITORY_PATH",
                "The repository path does not exist or is not a directory.",
            )
        try:
            root = self._run_git(
                str(candidate.resolve()), ["rev-parse", "--show-toplevel"]
            ).strip()
        except GitCommandError as exc:
            raise RepositoryValidationError(
                "NOT_A_GIT_REPOSITORY",
                "The selected path is not inside a Git work tree.",
            ) from exc
        return str(Path(root).resolve())

    @staticmethod
    def _run_git(root: str, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", root, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise GitCommandError("The Git executable could not be located.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError("Git repository inspection timed out.") from exc
        except OSError as exc:
            raise GitCommandError("Git repository inspection could not start.") from exc
        if completed.returncode != 0:
            raise GitCommandError(details={"exit_code": completed.returncode})
        return completed.stdout

    @staticmethod
    def _parse_status(status_output: str) -> list[ChangedPath]:
        records = status_output.split("\0")
        files: list[ChangedPath] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record or record.startswith("! "):
                continue
            if record.startswith("? "):
                path = GitRepositoryInspector._normalize_path(record[2:])
                files.append(
                    ChangedPath(
                        path=path,
                        status=ChangedPathStatus.UNTRACKED,
                        staged=False,
                        unstaged=True,
                        category=classify_path(path),
                    )
                )
                continue
            record_type = record[0]
            if record_type == "1":
                fields = record.split(" ", 8)
                if len(fields) != 9:
                    raise GitCommandError("Git returned an invalid status record.")
                xy = fields[1]
                path = GitRepositoryInspector._normalize_path(fields[8])
                files.append(
                    GitRepositoryInspector._changed_path(
                        path=path,
                        old_path=None,
                        xy=xy,
                        status=GitRepositoryInspector._ordinary_status(xy),
                    )
                )
                continue
            if record_type == "2":
                fields = record.split(" ", 9)
                if len(fields) != 10 or index >= len(records):
                    raise GitCommandError("Git returned an invalid rename record.")
                xy = fields[1]
                score = fields[8]
                path = GitRepositoryInspector._normalize_path(fields[9])
                old_path = GitRepositoryInspector._normalize_path(records[index])
                index += 1
                status = (
                    ChangedPathStatus.COPIED
                    if score.startswith("C")
                    else ChangedPathStatus.RENAMED
                )
                files.append(
                    GitRepositoryInspector._changed_path(
                        path=path,
                        old_path=old_path,
                        xy=xy,
                        status=status,
                    )
                )
                continue
            if record_type == "u":
                fields = record.split(" ", 10)
                if len(fields) != 11:
                    raise GitCommandError("Git returned an invalid conflict record.")
                xy = fields[1]
                path = GitRepositoryInspector._normalize_path(fields[10])
                files.append(
                    GitRepositoryInspector._changed_path(
                        path=path,
                        old_path=None,
                        xy=xy,
                        status=ChangedPathStatus.CONFLICTED,
                    )
                )
                continue
            raise GitCommandError("Git returned an unsupported status record.")
        return files

    @staticmethod
    def _changed_path(
        *, path: str, old_path: str | None, xy: str, status: ChangedPathStatus
    ) -> ChangedPath:
        if len(xy) != 2:
            raise GitCommandError("Git returned an invalid status code.")
        return ChangedPath(
            path=path,
            old_path=old_path,
            status=status,
            staged=xy[0] != ".",
            unstaged=xy[1] != ".",
            category=classify_path(path),
        )

    @staticmethod
    def _ordinary_status(xy: str) -> ChangedPathStatus:
        if "U" in xy:
            return ChangedPathStatus.CONFLICTED
        if "A" in xy:
            return ChangedPathStatus.ADDED
        if "D" in xy:
            return ChangedPathStatus.DELETED
        return ChangedPathStatus.MODIFIED

    @staticmethod
    def _parse_numstat(output: str) -> dict[str, _DiffStat]:
        records = output.split("\0")
        stats: dict[str, _DiffStat] = {}
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            fields = record.split("\t", 2)
            if len(fields) != 3:
                raise GitCommandError("Git returned invalid diff statistics.")
            additions_raw, deletions_raw, path_raw = fields
            if path_raw:
                path = GitRepositoryInspector._normalize_path(path_raw)
            else:
                if index + 1 >= len(records):
                    raise GitCommandError("Git returned invalid rename statistics.")
                index += 1  # skip old path
                path = GitRepositoryInspector._normalize_path(records[index])
                index += 1
            binary = additions_raw == "-" or deletions_raw == "-"
            stats[path] = _DiffStat(
                additions=None if binary else int(additions_raw),
                deletions=None if binary else int(deletions_raw),
                binary=binary,
            )
        return stats

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.replace("\\", "/")

    @staticmethod
    def _bound_utf8(value: str, limit_bytes: int) -> tuple[str, bool]:
        limit = max(0, limit_bytes)
        encoded = value.encode("utf-8")
        if len(encoded) <= limit:
            return value, False
        return encoded[:limit].decode("utf-8", errors="ignore"), True
