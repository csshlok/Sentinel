"""Executable resolution outside the selected repository.

Repository-owned directories never contribute executables, batch wrappers are
never run through a shell, and the Node package-manager shims are translated to
``node <cli.js>`` so Windows installations work without ``cmd.exe``.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

from backend.app.core.errors import AppError

_NODE_CLI = {"npm": "npm-cli.js", "npx": "npx-cli.js"}
_BATCH = {".cmd", ".bat"}


def safe_path_entries(env: Mapping[str, str], root: Path) -> list[Path]:
    """Absolute PATH directories that are not inside ``root``."""

    entries: list[Path] = []
    for value in env.get("PATH", "").split(os.pathsep):
        if not value:
            continue
        candidate = Path(value)
        if not candidate.is_absolute():
            continue
        candidate = candidate.resolve()
        if candidate == root or root in candidate.parents:
            continue
        entries.append(candidate)
    return entries


def _which(name: str, env: Mapping[str, str], root: Path) -> Path | None:
    for directory in safe_path_entries(env, root):
        found = shutil.which(str(directory / name))
        if not found:
            continue
        resolved = Path(found).resolve()
        if resolved == root or root in resolved.parents:
            continue
        return resolved
    return None


def find_executable(name: str, env: Mapping[str, str], root: Path) -> Path | None:
    """Locate ``name`` (no shell, no repository directories); ``None`` if absent."""

    if name in {"python", "python3"}:
        return Path(sys.executable)
    return _which(name, env, root)


def resolve_argv(
    name: str, env: Mapping[str, str], root: Path
) -> list[str]:
    """Return an argv prefix for ``name`` or raise a safe ``AppError``."""

    if name in {"python", "python3"}:
        return [sys.executable]
    found = _which(name, env, root)
    if found is None:
        raise AppError(
            "EXECUTABLE_NOT_FOUND", "The executable could not be located.",
            status_code=404,
        )
    if found.suffix.lower() in _BATCH:
        base = name.lower().removesuffix(".cmd").removesuffix(".bat")
        node = _which("node", env, root)
        script = _NODE_CLI.get(base)
        if node is not None and script is not None:
            cli = node.parent / "node_modules" / "npm" / "bin" / script
            if cli.is_file():
                return [str(node), str(cli)]
        raise AppError(
            "EXECUTABLE_NOT_ALLOWED",
            "Batch wrappers require a reviewed native executable adapter.",
        )
    return [str(found)]


def native_command(
    executable: str, args: list[str], env: Mapping[str, str], root: Path
) -> tuple[str, list[str]]:
    """Rewrite Windows ``npm``/``npx`` batch shims to ``node <cli.js>``.

    Other commands are returned unchanged. The result is still subject to the
    executing runner's own allowlist.
    """

    base = executable.lower().removesuffix(".cmd")
    if base not in _NODE_CLI:
        return executable, args
    found = _which(executable, env, root)
    if found is None or found.suffix.lower() not in _BATCH:
        return executable, args
    node = _which("node", env, root)
    if node is None:
        return executable, args
    cli = node.parent / "node_modules" / "npm" / "bin" / _NODE_CLI[base]
    if not cli.is_file():
        return executable, args
    return "node", [str(cli), *args]
