"""Map the changed lines of a checkpoint-bound Python diff."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.app.contracts.models import GitCheckpoint
from backend.app.core.errors import AppError
from backend.app.git.safe_exec import run_git

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")
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


def _parse_patch(patch: str, result: DiffMap) -> None:
    """Consume Git's patch grammar; source lines are never trusted as headers."""

    path: str | None = None
    in_file = saw_old = saw_new = False
    old_left = new_left = 0
    old_no = new_no = 0
    records = patch.split("\n")
    for index, raw in enumerate(records):
        line = raw[:-1] if raw.endswith("\r") else raw
        if not line and index == len(records) - 1:
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if old_left or new_left:
            marker = line[:1]
            if marker == "+" and new_left:
                if path is not None:
                    classification = _classification(path)
                    if classification:
                        result.excluded[path] = classification
                    else:
                        result.lines.setdefault(path, set()).add(new_no)
                new_no += 1
                new_left -= 1
            elif marker == "-" and old_left:
                old_no += 1
                old_left -= 1
            elif marker == " " and old_left and new_left:
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
            else:
                result.error = "Diff hunk body did not reconcile with its header."
                return
            continue
        if line.startswith("diff --git "):
            in_file, saw_old, saw_new = True, False, False
            path = None
        elif line.startswith("--- ") and in_file and not saw_old:
            saw_old = True
        elif line.startswith("+++ ") and in_file and saw_old and not saw_new:
            saw_new = True
            path = line[4:]
            if path == "/dev/null":
                path = None
            elif path.startswith("b/"):
                path = path[2:]
            elif path.startswith('"') or "\t" in path:
                result.error = "Diff contains a path that cannot be mapped safely."
                return
            else:
                result.error = "Diff has an unexpected destination prefix."
                return
        elif line.startswith("@@"):
            match = _HUNK.match(line)
            if match is None or not saw_new:
                result.error = "Malformed zero-context diff hunk."
                return
            old_no = int(match.group(1))
            old_left = int(match.group(2) or "1")
            new_no = int(match.group(3))
            new_left = int(match.group(4) or "1")
            if path is None and new_left:
                result.error = "Deletion hunk unexpectedly adds lines."
                return
        elif line.startswith(("Binary files ", "GIT binary patch")):
            result.error = "Binary diff cannot be mapped to executable lines."
            return
        elif line and not line.startswith(("index ", "new file mode ", "deleted file mode ",
                                           "old mode ", "new mode ", "similarity index ",
                                           "dissimilarity index ", "rename from ", "rename to ",
                                           "copy from ", "copy to ", "a/", "b/")):
            result.error = "Unexpected diff record."
            return
    if old_left or new_left:
        result.error = "Diff ended before its hunk body was complete."


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
            ["-c", "color.diff=false", "-c", "diff.interHunkContext=0", "diff",
             "--no-color", "--no-ext-diff", "--no-textconv", "--find-renames",
             "--inter-hunk-context=0", "--no-relative", "--src-prefix=a/",
             "--dst-prefix=b/", "--unified=0", baseline.head_sha, "--"],
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
    _parse_patch(patch, result)
    if result.error:
        return result
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
