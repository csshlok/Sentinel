"""Execution-bearing changes: files that make code run later, outside Sentinel (plan 02-06).

A Change that edits a CI workflow, an npm script, a ``conftest.py`` or a build
hook changes what runs when a human later opens the project in an IDE, runs
its tests or builds it, or when CI picks it up. None of that happens inside
Sentinel's boundary, so the Passport lists these paths instead of implying
they were supervised (integrated plan section 4.3).

Pure module: callers supply each changed path with its baseline and current
bytes (``None`` when absent). ``package.json`` and ``pyproject.toml`` are
flagged only when their script or build sections changed, or when either side
cannot be parsed (fail closed).
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from pathlib import PurePosixPath

NPM = "npm-scripts"
CI = "ci"
TEST_BOOTSTRAP = "test-bootstrap"
BUILD_HOOK = "build-hook"
HOOK = "git-or-ide-hook"

_NAMES = {
    ".npmrc": NPM, ".yarnrc": NPM, ".yarnrc.yml": NPM, ".pnpmfile.cjs": NPM,
    ".gitlab-ci.yml": CI, "azure-pipelines.yml": CI, "jenkinsfile": CI,
    "conftest.py": TEST_BOOTSTRAP, "pytest.ini": TEST_BOOTSTRAP, "tox.ini": TEST_BOOTSTRAP,
    "setup.cfg": TEST_BOOTSTRAP, "noxfile.py": TEST_BOOTSTRAP,
    "sitecustomize.py": TEST_BOOTSTRAP, "usercustomize.py": TEST_BOOTSTRAP,
    "setup.py": BUILD_HOOK, "makefile": BUILD_HOOK, "gnumakefile": BUILD_HOOK,
    "cmakelists.txt": BUILD_HOOK, "build.rs": BUILD_HOOK, "meson.build": BUILD_HOOK,
    ".pre-commit-config.yaml": HOOK, ".envrc": HOOK,
}
_DIRECTORIES = {
    (".github", "workflows"): CI, (".circleci",): CI,
    (".husky",): HOOK, (".githooks",): HOOK, (".devcontainer",): HOOK,
}
_VSCODE = {"tasks.json", "launch.json"}
# package.json keys whose change alters what npm/yarn/pnpm execute.
_NPM_KEYS = ("scripts", "bin", "gypfile", "workspaces", "packageManager", "config")


def _parts(path: str) -> tuple[str, ...] | None:
    if not path or "\0" in path or "\\" in path or path.startswith("/") or ":" in path:
        return None
    parts = PurePosixPath(path).parts
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return tuple(part.casefold() for part in parts)


def _json_section(data: bytes | None) -> object:
    if data is None:
        return None
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("package.json is not an object")
    return {key: value.get(key) for key in _NPM_KEYS}


def _toml_section(data: bytes | None) -> object:
    if data is None:
        return None
    value = tomllib.loads(data.decode("utf-8-sig"))
    return {"build-system": value.get("build-system"), "tool": value.get("tool"),
            "scripts": value.get("project", {}).get("scripts")
            if isinstance(value.get("project"), dict) else None}


def _sections_differ(reader, before: bytes | None, after: bytes | None) -> bool:
    try:
        return reader(before) != reader(after)
    except (ValueError, UnicodeError, tomllib.TOMLDecodeError, RecursionError):
        return True  # unparseable: what it executes cannot be ruled out


def classify(path: str, before: bytes | None, after: bytes | None) -> str | None:
    """The category of one changed path, or None when it does not run code later."""

    parts = _parts(path)
    if parts is None:
        return HOOK  # an unrepresentable path is never assumed harmless
    name = parts[-1]
    for prefix, category in _DIRECTORIES.items():
        if parts[:len(prefix)] == prefix and len(parts) > len(prefix):
            return category
    if len(parts) == 2 and parts[0] == ".vscode" and name in _VSCODE:
        return HOOK
    if name.endswith(".pth"):
        return TEST_BOOTSTRAP
    if name == "package.json":
        return NPM if _sections_differ(_json_section, before, after) else None
    if name == "pyproject.toml":
        return BUILD_HOOK if _sections_differ(_toml_section, before, after) else None
    return _NAMES.get(name)


def execution_bearing(changes: Iterable[tuple[str, bytes | None, bytes | None]],
                      ) -> list[tuple[str, str]]:
    """``(path, category)`` for every execution-bearing change, sorted by path."""

    found = []
    for path, before, after in changes:
        category = classify(path, before, after)
        if category is not None:
            found.append((path, category))
    return sorted(found)
