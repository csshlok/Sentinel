"""Dependency Tracker (``DependencyPort``).

Compares supported manifests and lockfiles at the checkpoint's HEAD commit with
the working tree. Direct declarations and lockfile-resolved evidence are kept
separate, source files are named on every change, and anything unsupported or
unreadable is reported instead of guessed. Repository content is parsed as data
only; no package manager or repository script is executed. Risk notes are inputs
for a reviewer, not vulnerability findings, and never claim what caused a change.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    DependencyChange, DependencyReport, EvidenceStatus, GitCheckpoint, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.dependencies import parsers
from backend.app.dependencies.parsers import Entry, ParseError
from backend.app.git import reader
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.errors import GitCommandError

FILE_LIMIT = 4 * 1_048_576
MAX_FILES = 300
MAX_CHANGES = 10_000

_VERSION = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _numeric(version: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(version)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


class DependencyTracker:
    """Concrete ``DependencyPort``."""

    def __init__(self, file_limit: int = FILE_LIMIT) -> None:
        self._limit = file_limit

    def scan(
        self, change_id: UUID, checkpoint: GitCheckpoint, repository_path: str,
        *, baseline: GitCheckpoint | None = None,
    ) -> DependencyReport:
        root = GitRepositoryInspector().validate_repository(repository_path).root
        if root != checkpoint.repository_root:
            raise AppError("CHECKPOINT_REPOSITORY_MISMATCH",
                           "The checkpoint belongs to a different repository.", status_code=409)
        if baseline is not None and root != baseline.repository_root:
            raise AppError("CHECKPOINT_REPOSITORY_MISMATCH",
                           "The baseline checkpoint belongs to a different repository.",
                           status_code=409)
        if reader.head_sha(root) != checkpoint.head_sha.lower():
            raise AppError("DEPENDENCY_CHECKPOINT_STALE",
                           "The repository HEAD moved after the checkpoint; capture a new one.",
                           status_code=409)
        commit = checkpoint.head_sha.lower()
        # Old-side content comes from the baseline when one is given, so a
        # dependency edit the agent already committed by the time
        # `checkpoint` was captured is still visible as a change -- reading
        # old content from `checkpoint`'s own HEAD (the only option without
        # a baseline) makes any already-committed edit invisible, since it
        # is already folded into that same commit.
        old_commit = baseline.head_sha.lower() if baseline is not None else commit
        candidate_paths = set(reader.list_paths(root, commit))
        if baseline is not None and old_commit != commit:
            candidate_paths |= set(reader.list_paths(root, old_commit))
        candidates = [p for p in sorted(candidate_paths)
                      if parsers.is_supported(p) or parsers.unsupported_ecosystem(p)]
        unsupported: list[str] = []
        if len(candidates) > MAX_FILES:
            unsupported.append(f"scan: {len(candidates)} dependency files; only {MAX_FILES} examined")
            candidates = candidates[:MAX_FILES]

        old_files: dict[str, bytes | None] = {}
        new_files: dict[str, bytes | None] = {}
        for path in candidates:
            try:
                old_files[path] = reader.read_committed(root, old_commit, path, self._limit)
                new_files[path] = reader.read_working(root, path, self._limit)
            except GitCommandError:
                unsupported.append(f"{self._eco(path)}: {path} (unreadable or oversized)")
                old_files.pop(path, None)
                new_files.pop(path, None)

        changes: list[DependencyChange] = []
        parsed_old, parsed_new = self._parse_all(old_files), self._parse_all(new_files)
        for path in sorted(old_files):
            if old_files[path] == new_files[path]:
                continue
            eco = parsers.unsupported_ecosystem(path)
            if eco is not None:
                unsupported.append(f"{eco}: {path} (format not supported)")
                continue
            old, new = parsed_old[path], parsed_new[path]
            if isinstance(old, ParseError) or isinstance(new, ParseError):
                unsupported.append(f"{self._eco(path)}: {path} (malformed; not compared)")
                continue
            changes.extend(self._diff(path, old or [], new or [], parsed_new, new_files))
        changes.sort(key=lambda c: (c.ecosystem, c.package, c.source_path,
                                    c.old_version or "", c.new_version or ""))
        if len(changes) > MAX_CHANGES:
            unsupported.append(f"scan: {len(changes)} changes; only {MAX_CHANGES} reported")
            changes = changes[:MAX_CHANGES]
        return DependencyReport(
            id=uuid4(), change_id=change_id, checkpoint_id=checkpoint.id,
            changes=changes, unsupported_ecosystems=sorted(set(unsupported))[:64],
            captured_at=utc_now(),
        )

    # -- parsing ------------------------------------------------------------

    @staticmethod
    def _eco(path: str) -> str:
        known = parsers.unsupported_ecosystem(path)
        if known:
            return known
        name = PurePosixPath(path).name.lower()
        return "node" if name.startswith("package") else "python"

    def _parse_all(self, files: dict[str, bytes | None]) -> dict[str, list[Entry] | ParseError | None]:
        result: dict[str, list[Entry] | ParseError | None] = {}
        manifests: dict[str, set[str]] = {}
        # Manifests first, so locks can label direct dependencies.
        for path in sorted(files, key=lambda p: (not p.lower().endswith(("package.json", "pyproject.toml")), p)):
            data = files[path]
            if data is None or not parsers.is_supported(path):
                result[path] = None
                continue
            name = PurePosixPath(path).name.lower()
            directory = str(PurePosixPath(path).parent)
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                result[path] = ParseError("Not UTF-8.")
                continue
            try:
                if name == "package.json":
                    entries, _workspaces = parsers.parse_package_json(text)
                    manifests[f"node:{directory}"] = {e.name for e in entries}
                elif name == "pyproject.toml":
                    entries = parsers.parse_pyproject(text)
                    manifests[f"python:{directory}"] = {e.name for e in entries}
                elif name == "package-lock.json":
                    entries = parsers.parse_package_lock(text, manifests.get(f"node:{directory}"))
                elif name == "poetry.lock":
                    entries = parsers.parse_poetry_lock(text, manifests.get(f"python:{directory}"))
                else:
                    entries = parsers.parse_requirements(text)
                result[path] = entries
            except (ParseError, RecursionError, ValueError, TypeError, AttributeError) as exc:
                result[path] = exc if isinstance(exc, ParseError) else ParseError("Malformed content.")
        return result

    # -- comparison ---------------------------------------------------------

    def _diff(
        self, path: str, old: list[Entry], new: list[Entry],
        parsed_new: dict[str, list[Entry] | ParseError | None],
        new_files: dict[str, bytes | None],
    ) -> list[DependencyChange]:
        def keyed(entries: list[Entry]) -> dict[tuple[str, str, str], Entry]:
            table: dict[tuple[str, str, str], Entry] = {}
            for entry in entries:
                table.setdefault((entry.kind, entry.name, entry.scope), entry)
            return table

        before, after = keyed(old), keyed(new)
        result: list[DependencyChange] = []
        directory = PurePosixPath(path).parent
        name = PurePosixPath(path).name.lower()
        siblings = {
            n: PurePosixPath(directory, n).as_posix() if str(directory) != "." else n
            for n in ("package-lock.json", "package.json", "poetry.lock", "pyproject.toml")
        }
        for key in sorted(set(before) | set(after)):
            a, b = before.get(key), after.get(key)
            if a is not None and b is not None and (a.version, a.source) == (b.version, b.source):
                continue
            entry = b or a
            notes: list[str] = []
            for side in (a, b):
                if side is not None and side.source != "registry" and side.source != "workspace":
                    note = f"Non-registry source ({side.source}); provenance is not verified."
                    if note not in notes:
                        notes.append(note)
            if b is not None and b.kind == "declared" and not b.exact and b.source == "registry" \
                    and not b.name.startswith("<"):
                notes.append("Unpinned version range; the resolved version can vary.")
            if a is not None and b is not None:
                x, y = _numeric(a.version), _numeric(b.version)
                if x and y and a.exact and b.exact:
                    if y < x:
                        notes.append("Version decreased.")
                    elif y[0] > x[0]:
                        notes.append("Major version increased.")
            if entry.scope.startswith("nested:"):
                notes.append("Resolved through a transitive path, not a direct declaration.")
            if b is not None and name == "package.json":
                lock_path = siblings["package-lock.json"]
                lock_entries = parsed_new.get(lock_path)
                if new_files.get(lock_path) is None:
                    notes.append("No package-lock.json alongside this manifest.")
                elif isinstance(lock_entries, list) and b.exact:
                    resolved = [e for e in lock_entries if e.name == b.name and not e.scope]
                    if resolved and resolved[0].version != b.version.lstrip("v"):
                        notes.append(
                            f"Manifest pins {b.version} but the lockfile resolves {resolved[0].version}.")
            result.append(DependencyChange(
                ecosystem=entry.ecosystem, package=entry.name[:256],
                old_version=a.version if a else None, new_version=b.version if b else None,
                direct=entry.direct,
                source_path=path, evidence_status=EvidenceStatus.CURRENT,
                risk_notes=sorted(set(notes))[:32],
            ))
        return result
