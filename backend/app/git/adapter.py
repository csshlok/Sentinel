"""Read-only, contract-conforming Git repository inspection.

Git is reached only through the hardened harness ``backend.app.git.safe_exec``
(trusted executable, minimal environment, hooks path that is a regular file, neutralized
filters/drivers/execution-bearing config, bounded capture). ``state.py`` and
``reader.py`` reach Git only through ``GitRepositoryInspector._capture_git`` and
therefore inherit the same hardening.

One ``inspect()`` shares a single ``SafeGitSession`` so configuration is
discovered once per inspection instead of once per Git command; the session
never outlives that call, so every new inspection rediscovers configuration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.contracts.models import (
    ChangedPath, ChangedPathStatus, GitSummary, RepositoryInfo, utc_now,
)
from backend.app.git.classifier import classify_path
from backend.app.git.errors import GitCommandError, RepositoryValidationError
from backend.app.git.safe_exec import SafeGitSession
from backend.app.execution._process import CapturedProcess


METADATA_LIMIT = 8 * 1_048_576
PATCH_LIMIT = 1_048_576
STATUS_ARGS = ["status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none"]
DIFF_ARGS = ["diff", "--no-ext-diff", "--no-textconv", "--no-color", "--ignore-submodules=none"]


@dataclass(frozen=True, slots=True)
class _DiffStat:
    additions: int | None
    deletions: int | None
    binary: bool


class GitRepositoryInspector:
    """Concrete implementation of the frozen ``GitInspectionPort``."""

    def validate_repository(self, path: str) -> RepositoryInfo:
        return self._validate(path, SafeGitSession())

    def _validate(self, path: str, session: SafeGitSession) -> RepositoryInfo:
        root = self._canonical_root(path, session)
        try:
            head_sha = self._run_git(root, ["rev-parse", "--verify", "HEAD"], session).strip()
        except GitCommandError as exc:
            if "exit_code" not in exc.details:
                raise
            raise RepositoryValidationError(
                "REPOSITORY_HAS_NO_COMMITS",
                "The repository must contain at least one commit.",
            ) from exc
        branch = self._run_git(root, ["branch", "--show-current"], session).strip() or None
        if not re.fullmatch(r"[0-9a-f]{40}", head_sha) or (branch and len(branch) > 1024):
            raise GitCommandError("The repository identity is unsupported by the current contract.")
        return RepositoryInfo(root=root, branch=branch, head_sha=head_sha)

    def inspect(self, path: str, patch_limit_bytes: int) -> GitSummary:
        if type(patch_limit_bytes) is not int or not 0 <= patch_limit_bytes <= PATCH_LIMIT:
            raise GitCommandError("The patch limit must be between zero and one MiB.")
        # One discovery per inspection; never reused by a later inspection.
        session = SafeGitSession()
        repository = self._validate(path, session)
        status_output = self._run_git(repository.root, STATUS_ARGS, session)
        status_entries = self._parse_status(status_output)
        stats_args = [*DIFF_ARGS, "--numstat", "-z", repository.head_sha, "--"]
        stats_output = self._run_git(repository.root, stats_args, session)
        stats = self._parse_numstat(stats_output)

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
        patch_args = [*DIFF_ARGS, repository.head_sha, "--"]
        captured = self._capture_git(repository.root, patch_args, patch_limit_bytes,
                                     session=session)
        raw_patch = captured.stdout.decode("utf-8", errors="replace")
        patch, patch_truncated = self._bound_utf8(raw_patch, patch_limit_bytes)
        patch_truncated |= captured.truncated or raw_patch.encode("utf-8") != captured.stdout
        # This detects observed movement, not an atomic filesystem snapshot.
        # Hash all diff bytes, including bytes beyond the displayed prefix.
        repeated = self._capture_git(repository.root, patch_args, 0, session=session)
        if (self._validate(repository.root, session) != repository
                or self._run_git(repository.root, STATUS_ARGS, session) != status_output
                or self._run_git(repository.root, stats_args, session) != stats_output
                or repeated.stdout_digest != captured.stdout_digest):
            raise GitCommandError("The repository changed during inspection; refresh again.")
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

    def _canonical_root(self, path: str, session: SafeGitSession) -> str:
        try:
            candidate = Path(path).expanduser().resolve(strict=True)
            valid = candidate.is_dir()
        except (OSError, ValueError, RuntimeError):
            valid = False
        if not valid:
            raise RepositoryValidationError(
                "INVALID_REPOSITORY_PATH",
                "The repository path does not exist or is not a directory.",
            )
        try:
            root = self._run_git(
                str(candidate.resolve()), ["rev-parse", "--show-toplevel"], session
            ).strip()
        except GitCommandError as exc:
            if "exit_code" not in exc.details:
                raise
            raise RepositoryValidationError(
                "NOT_A_GIT_REPOSITORY",
                "The selected path is not inside a Git work tree.",
            ) from exc
        root_path = Path(root).resolve()
        if root_path != candidate and root_path not in candidate.parents:
            # `core.worktree` in the (agent-writable) repository config can point
            # Git at any directory, for example a clean clone, so inspection would
            # describe that decoy instead of the tree the agent edited.
            raise RepositoryValidationError(
                "REPOSITORY_WORKTREE_REDIRECTED",
                "The repository's configuration points its work tree outside the "
                "selected path (core.worktree); Sentinel refuses to inspect it.",
                details={"work_tree": str(root_path)},
            )
        return str(root_path)

    @classmethod
    def _run_git(cls, root: str, args: list[str], session: SafeGitSession | None = None) -> str:
        result = cls._capture_git(root, args, METADATA_LIMIT, session=session)
        if result.truncated:
            raise GitCommandError("Git metadata exceeded the inspection limit.")
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitCommandError("Git metadata contains unsupported text encoding.") from exc

    @staticmethod
    def _capture_git(
        root: str, args: list[str], limit: int, *, session: SafeGitSession | None = None,
    ) -> CapturedProcess:
        # The harness resolves a trusted Git, builds the hardened environment
        # and overrides every configured filter/driver. Without a caller-owned
        # session (reader/state one-off reads) discovery is fresh for this call.
        git = (session or SafeGitSession()).git(root)
        if args[0] in {"status", "diff"}:
            # Turning a clean filter off may change the meaning of a diff
            # (for example LFS). Reject files using filters rather than
            # returning plausible but incorrect raw-byte evidence.
            tracked = git.run(["ls-files", "--stage", "-z"])
            if (tracked.returncode != 0 or tracked.truncated
                    or tracked.timed_out or tracked.incomplete):
                raise GitCommandError("Git tracked paths could not be inspected.")
            batch: list[str] = []
            batch_size = 0
            paths = []
            try:
                raw_paths = tracked.stdout.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise GitCommandError("Git returned invalid tracked paths.") from exc
            if raw_paths and not raw_paths.endswith("\0"):
                raise GitCommandError("Git returned truncated tracked paths.")
            for record in raw_paths.split("\0")[:-1]:
                match = re.fullmatch(r"([0-7]{6}) [a-f0-9]{40} [0-3]\t(.+)", record, re.DOTALL)
                if match is None:
                    raise GitCommandError("Git returned invalid tracked paths.")
                if match[1] == "160000":
                    # Submodule status may invoke commands from the nested
                    # repository's independent configuration. The old port
                    # cannot express incomplete nested worktree evidence.
                    raise GitCommandError("Submodule inspection requires a dedicated supported adapter.")
                paths.append(GitRepositoryInspector._normalize_path(match[2]))
            paths = list(dict.fromkeys(paths))
            for path in [*paths, ""]:
                if batch and (not path or batch_size + len(path) > 12_000):
                    attributes = git.run(["check-attr", "-z", "filter", "--", *batch])
                    if (attributes.returncode != 0 or attributes.truncated
                            or attributes.timed_out or attributes.incomplete):
                        raise GitCommandError("Git attributes could not be inspected.")
                    fields = attributes.stdout.split(b"\0")
                    if fields[-1] or (len(fields) - 1) % 3:
                        raise GitCommandError("Git returned invalid attributes.")
                    if any(value not in {b"unspecified", b"unset"} for value in fields[2:-1:3]):
                        raise GitCommandError("Files using Git content filters are unsupported for inspection.")
                    batch, batch_size = [], 0
                if path:
                    batch.append(path)
                    batch_size += len(path) + 3
        completed = git.run(args, limit=limit, timeout=30, stderr_limit=4096)
        if completed.timed_out or completed.incomplete:
            raise GitCommandError("Git repository inspection timed out.")
        if completed.returncode != 0:
            raise GitCommandError(details={"exit_code": completed.returncode})
        return completed

    @staticmethod
    def _parse_status(status_output: str) -> list[ChangedPath]:
        if status_output and not status_output.endswith("\0"):
            raise GitCommandError("Git returned a truncated status record.")
        records = status_output.split("\0")[:-1] if status_output else []
        files: list[ChangedPath] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                raise GitCommandError("Git returned an empty status record.")
            if record.startswith("! "):
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
                if len(fields) != 9 or fields[0] != "1":
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
                if len(fields) != 10 or fields[0] != "2" or index >= len(records) or not records[index]:
                    raise GitCommandError("Git returned an invalid rename record.")
                xy = fields[1]
                score = fields[8]
                if not re.fullmatch(r"[RC](100|[0-9]{1,2})", score):
                    raise GitCommandError("Git returned an invalid rename score.")
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
                if len(fields) != 11 or fields[0] != "u":
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
        if len({entry.path for entry in files}) != len(files):
            raise GitCommandError("Git returned duplicate status paths.")
        return files

    @staticmethod
    def _changed_path(
        *, path: str, old_path: str | None, xy: str, status: ChangedPathStatus
    ) -> ChangedPath:
        if len(xy) != 2 or any(char not in ".MADRCUT" for char in xy):
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
        if output and not output.endswith("\0"):
            raise GitCommandError("Git returned truncated diff statistics.")
        records = output.split("\0")[:-1] if output else []
        stats: dict[str, _DiffStat] = {}
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                raise GitCommandError("Git returned empty diff statistics.")
            fields = record.split("\t", 2)
            if len(fields) != 3:
                raise GitCommandError("Git returned invalid diff statistics.")
            additions_raw, deletions_raw, path_raw = fields
            if path_raw:
                path = GitRepositoryInspector._normalize_path(path_raw)
            else:
                if index + 1 >= len(records) or not records[index] or not records[index + 1]:
                    raise GitCommandError("Git returned invalid rename statistics.")
                GitRepositoryInspector._normalize_path(records[index])
                index += 1  # skip old path
                path = GitRepositoryInspector._normalize_path(records[index])
                index += 1
            binary = additions_raw == deletions_raw == "-"
            if not binary and not all(re.fullmatch(r"[0-9]{1,18}", value)
                                      for value in (additions_raw, deletions_raw)):
                raise GitCommandError("Git returned invalid diff statistics.")
            if path in stats:
                raise GitCommandError("Git returned duplicate diff statistics.")
            stats[path] = _DiffStat(
                additions=None if binary else int(additions_raw),
                deletions=None if binary else int(deletions_raw),
                binary=binary,
            )
        return stats

    @staticmethod
    def _normalize_path(path: str) -> str:
        # Git's -z output already uses forward slashes. A backslash on POSIX is
        # a literal filename character and must not alias another file.
        if (not path or len(path) > 32767 or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or "\0" in path):
            raise GitCommandError("Git returned an invalid repository-relative path.")
        return path

    @staticmethod
    def _bound_utf8(value: str, limit_bytes: int) -> tuple[str, bool]:
        limit = max(0, limit_bytes)
        encoded = value.encode("utf-8")
        if len(encoded) <= limit:
            return value, False
        return encoded[:limit].decode("utf-8", errors="ignore"), True
