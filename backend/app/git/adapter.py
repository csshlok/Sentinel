from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.git.classifier import classify_path as classify_repo_path
from backend.app.git.errors import GitCommandError, RepositoryValidationError


class GitRepositoryInspector:
    """Read-only Git inspection for the prototype."""

    def validate_repository(self, path: str) -> dict[str, Any]:
        root = self._canonical_root(path)
        try:
            branch = self._run_git(root, ["branch", "--show-current"]).strip() or None
            head_sha = self._run_git(root, ["rev-parse", "--verify", "HEAD"]).strip()
        except GitCommandError as exc:
            raise RepositoryValidationError(str(exc)) from exc

        return {
            "root": str(Path(root).resolve()),
            "branch": branch,
            "head_sha": head_sha,
        }

    def inspect(self, path: str, patch_limit_bytes: int = 1024 * 1024) -> dict[str, Any]:
        root = self._canonical_root(path)
        status_output = self._run_git(root, ["status", "--porcelain=v2", "-z", "--untracked-files=all"])
        files = self._parse_status(status_output)

        diff_head = self._run_git(root, ["diff", "--numstat", "HEAD"]).strip()
        cached_head = self._run_git(root, ["diff", "--numstat", "--cached", "HEAD"]).strip()
        additions, deletions = self._sum_numstat(cached_head + "\n" + diff_head)

        for item in files:
            if item.get("status") == "UNTRACKED":
                file_path = Path(root) / item["path"]
                if file_path.exists() and file_path.is_file():
                    additions += sum(1 for _ in file_path.read_text(encoding="utf-8", errors="replace").splitlines())

        tracked_patch = self._run_git(root, ["diff", "--no-ext-diff", "HEAD"]).strip() or ""
        untracked_patch_omitted = any(item.get("status") == "UNTRACKED" for item in files)
        patch = tracked_patch
        if untracked_patch_omitted:
            patch = (patch + "\n[untracked files omitted from patch; content not read]\n").strip()
        patch_truncated = untracked_patch_omitted or len(patch.encode("utf-8")) > patch_limit_bytes
        if patch_truncated:
            patch = patch[:patch_limit_bytes]

        branch = self._run_git(root, ["branch", "--show-current"]).strip() or None
        head_sha = self._run_git(root, ["rev-parse", "--verify", "HEAD"]).strip()

        return {
            "repository_root": str(Path(root).resolve()),
            "branch": branch,
            "head_sha": head_sha,
            "is_clean": not files,
            "files": files,
            "total_additions": additions,
            "total_deletions": deletions,
            "patch": patch,
            "patch_truncated": patch_truncated,
            "untracked_patch_omitted": untracked_patch_omitted,
            "refreshed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _canonical_root(self, path: str) -> str:
        repo_path = Path(path).expanduser().resolve()
        if not repo_path.exists() or not repo_path.is_dir():
            raise RepositoryValidationError(f"Path does not exist or is not a directory: {path}")
        try:
            root = self._run_git(str(repo_path), ["rev-parse", "--show-toplevel"]).strip()
        except GitCommandError as exc:
            raise RepositoryValidationError(f"Not a valid Git repository: {path}") from exc
        return root

    def _run_git(self, root: str, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", root, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
        except FileNotFoundError as exc:
            raise GitCommandError("Git executable not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(f"Git command timed out: {args}") from exc

        if completed.returncode != 0:
            raise GitCommandError(f"Git command failed: {' '.join(args)}")
        return completed.stdout

    def _parse_status(self, status_output: str) -> list[dict[str, Any]]:
        if not status_output:
            return []

        files: list[dict[str, Any]] = []
        for entry in status_output.split("\0"):
            if not entry:
                continue

            if entry.startswith("? "):
                path = entry[2:].replace("\\", "/")
                files.append(
                    {
                        "path": path,
                        "old_path": None,
                        "status": "UNTRACKED",
                        "staged": False,
                        "unstaged": True,
                        "additions": None,
                        "deletions": None,
                        "category": classify_repo_path(path),
                        "binary": False,
                    }
                )
                continue

            if not entry.startswith("1 "):
                continue

            fields = entry.split(" ", 8)
            if len(fields) < 9:
                continue

            xy = fields[1]
            path = fields[8].replace("\\", "/")
            staged = bool(xy[0] not in {"?", " ", "N"} and xy[0] != " ")
            unstaged = bool(xy[1] not in {"?", " ", "N"} and xy[1] != " ")

            if xy == "??":
                status = "UNTRACKED"
                staged = False
                unstaged = True
            elif xy[0] == "A":
                status = "ADDED"
            elif xy[1] == "D":
                status = "DELETED"
            elif xy[0] == "U" or xy[1] == "U":
                status = "CONFLICTED"
            else:
                status = "MODIFIED"

            files.append(
                {
                    "path": path,
                    "old_path": None,
                    "status": status,
                    "staged": staged,
                    "unstaged": unstaged,
                    "additions": None,
                    "deletions": None,
                    "category": classify_repo_path(path),
                    "binary": False,
                }
            )
        return files

    def _sum_numstat(self, numstat_output: str) -> tuple[int, int]:
        total_additions = 0
        total_deletions = 0
        for line in numstat_output.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                additions = int(parts[0])
                deletions = int(parts[1])
            except ValueError:
                continue
            total_additions += additions
            total_deletions += deletions
        return total_additions, total_deletions


def _normalise_repository_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def classify_path(path: str) -> str:
    return classify_repo_path(path)
