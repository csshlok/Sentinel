"""Map the changed lines of a checkpoint-bound Python diff."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.contracts.models import GitCheckpoint
from backend.app.core.errors import AppError
from backend.app.git.safe_exec import run_git

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_GENERATED = ("/generated/", "/vendor/", "/dist/", "/build/")


@dataclass(slots=True)
class DiffMap:
    lines: dict[str, set[int]] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _classification(path: str) -> str | None:
    lower = "/" + path.lower().replace("\\", "/")
    if any(part in lower for part in _GENERATED) or lower.endswith(("_pb2.py", ".g.py")):
        return "generated"
    if lower.endswith((".toml", ".yaml", ".yml", ".json", ".ini", ".cfg")):
        return "configuration"
    if not lower.endswith(".py"):
        return "unsupported language or non-source file"
    return None


def map_diff(*, baseline: GitCheckpoint, tested: GitCheckpoint, limit: int = 8_388_608) -> DiffMap:
    """Use the baseline commit and current worktree; refuse un-reconstructable baselines."""

    result = DiffMap()
    if baseline.repository_root != tested.repository_root or baseline.change_id != tested.change_id:
        result.error = "Checkpoints belong to different repositories or Changes."
        return result
    if baseline.summary.files or baseline.summary.patch_truncated or tested.summary.patch_truncated:
        result.error = "Baseline is not clean or checkpoint patch was truncated."
        return result
    try:
        captured = run_git(
            tested.repository_root,
            ["diff", "--no-ext-diff", "--no-textconv", "--find-renames", "--no-prefix",
             "--unified=0", baseline.head_sha, "--"],
            limit=limit,
        )
    except (AppError, OSError, RuntimeError, ValueError) as exc:
        result.error = f"Diff collection failed: {type(exc).__name__}."
        return result
    if captured.truncated or captured.incomplete or captured.timed_out or captured.returncode != 0:
        result.error = "Diff was truncated or failed."
        return result
    try:
        patch = captured.stdout.decode("utf-8")
    except UnicodeError:
        result.error = "Diff path or content is not UTF-8."
        return result
    path: str | None = None
    for line in patch.splitlines():
        if line.startswith(("Binary files ", "GIT binary patch")):
            result.error = "Binary diff cannot be mapped to executable lines."
            return result
        if line.startswith("+++ "):
            path = line[4:]
            if path == "/dev/null":
                path = None
            elif path.startswith('"') or "\t" in path:
                result.error = "Diff contains a path that cannot be mapped safely."
                return result
        elif line.startswith("@@"):
            match = _HUNK.match(line)
            if match is None:
                result.error = "Malformed zero-context diff hunk."
                return result
            if path is None:
                continue  # deletion-only hunk has no coverable new-file lines
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            classification = _classification(path)
            if classification:
                result.excluded[path] = classification
            else:
                result.lines.setdefault(path, set()).update(range(start, start + count))
    for entry in tested.summary.files:
        if entry.status.value != "UNTRACKED":
            continue
        path = entry.path.replace("\\", "/")
        classification = _classification(path)
        if classification:
            result.excluded[path] = classification
            continue
        target = Path(tested.repository_root) / path
        try:
            if target.is_symlink() or not target.is_file() or target.stat().st_size > limit:
                raise ValueError("untracked file is unavailable or oversized")
            content = target.read_bytes()
            content.decode("utf-8")
        except (OSError, UnicodeError, ValueError):
            result.error = f"Untracked source cannot be mapped: {path}."
            return result
        result.lines[path] = set(range(1, len(content.splitlines()) + 1))
    return result
