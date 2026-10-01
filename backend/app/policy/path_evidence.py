"""Fail-closed documentation path inventory from bound Git checkpoints."""

from __future__ import annotations

from backend.app.contracts.models import GitCheckpoint
from backend.app.core.errors import AppError
from backend.app.git.safe_exec import run_git


def documentation_paths(baseline: GitCheckpoint, tested: GitCheckpoint) -> tuple[
    tuple[str, ...], tuple[str, ...], str | None,
]:
    """Return every changed path, mode-changed paths, or a named inspection error."""
    if (baseline.change_id != tested.change_id or
            baseline.repository_root != tested.repository_root):
        return (), (), "checkpoint repository mismatch"
    root = tested.repository_root
    try:
        status = run_git(root, ["diff", "--name-status", "-z", "--no-renames",
                                baseline.head_sha, "--"])
        raw = run_git(root, ["diff", "--raw", "-z", "--no-renames",
                             baseline.head_sha, "--"])
        other = run_git(root, ["ls-files", "--others", "-z", "--"])
        for result in (status, raw, other):
            if (result.returncode != 0 or result.truncated or result.incomplete or
                    result.timed_out):
                return (), (), "Git path enumeration failed or was truncated"
        entries = status.stdout.split(b"\0")
        if entries[-1] != b"":
            return (), (), "malformed name-status diff"
        paths: set[str] = set()
        for index in range(0, len(entries) - 1, 2):
            code = entries[index].decode("ascii")
            if code not in {"A", "D", "M", "T", "U"}:
                return (), (), "unsupported name-status entry"
            path = entries[index + 1].decode("utf-8")
            if not path or "\0" in path:
                return (), (), "invalid diff path"
            paths.add(path)
        if (len(entries) - 1) % 2:
            return (), (), "malformed name-status diff"
        raw_entries = raw.stdout.split(b"\0")
        if raw_entries[-1] != b"" or (len(raw_entries) - 1) % 2:
            return (), (), "malformed raw diff"
        modes: set[str] = set()
        for index in range(0, len(raw_entries) - 1, 2):
            header = raw_entries[index].decode("ascii").split()
            path = raw_entries[index + 1].decode("utf-8")
            if len(header) != 5 or not header[0].startswith(":"):
                return (), (), "malformed raw diff"
            if header[0][1:] != "000000" and header[1] != "000000" and header[0][1:] != header[1]:
                modes.add(path)
        untracked = {entry.decode("utf-8") for entry in other.stdout.split(b"\0") if entry}
        bound = {entry.path for entry in tested.summary.files
                 if entry.status.value == "UNTRACKED"}
        if untracked - bound:
            return (), (), "untracked paths outside tested checkpoint"
        paths.update(untracked)
        return tuple(sorted(paths)), tuple(sorted(modes)), None
    except (AppError, OSError, RuntimeError, ValueError, UnicodeError) as exc:
        return (), (), f"Git path enumeration unavailable ({type(exc).__name__})"
