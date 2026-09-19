"""Check discovery from repository configuration.

Discovery only reads files and recognizes a fixed set of tools. It never runs a
discovered string: a ``package.json`` script becomes a candidate only when its
command starts with a recognized tool, and is then invoked by name through
``npm --ignore-scripts`` so pre/post hooks do not run. Anything unrecognized is
reported as a coverage gap instead of being guessed at or executed.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from backend.app.core.errors import AppError
from backend.app.git import reader

MAX_CONFIG_BYTES = 1_048_576

_TEST_TOOLS = (
    (re.compile(r"^(?:npx\s+)?jest(?:\s|$)"), "jest"),
    (re.compile(r"^(?:npx\s+)?vitest(?:\s|$)"), "vitest"),
    (re.compile(r"^node\s+--test(?:\s|$)"), "node-test"),
    (re.compile(r"^(?:npx\s+)?mocha(?:\s|$)"), "mocha"),
)
_LINT = re.compile(r"^(?:npx\s+)?(?:eslint|biome\s+(?:check|lint))(?:\s|$)")
_TYPECHECK = re.compile(r"^(?:npx\s+)?tsc(?:\s|$)")
_BUILD = re.compile(
    r"^(?:npx\s+)?(?:tsc|vite\s+build|webpack|esbuild|rollup|next\s+build|parcel\s+build)(?:\s|$)")
_KIND_ORDER = {"test": 0, "lint": 1, "typecheck": 2, "build": 3, "security": 4}


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    family: str          # python | node
    kind: str            # test | lint | typecheck | build | security
    executable: str
    args: tuple[str, ...]
    rationale: str

    @property
    def command(self) -> str:
        return " ".join((self.executable, *self.args))

    def aliases(self) -> set[str]:
        base = {self.id, self.name.lower(), self.kind, f"{self.family} {self.kind}",
                self.command.lower(), f"{self.kind}s"}
        if self.executable == "npm" and self.args[:1] == ("test",):
            base.add("npm test")
        return {item.lower() for item in base}


@dataclass
class Discovery:
    candidates: list[Candidate] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def _read(root: str, path: str) -> str | None:
    try:
        data = reader.read_working(root, path, MAX_CONFIG_BYTES)
    except Exception:
        return None
    if data is None:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _toml(text: str | None) -> dict:
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def discover(root: str, paths: list[str]) -> Discovery:
    """Discover candidate checks for the repository at ``root``.

    ``paths`` is the repository's known file list (tracked plus untracked and
    not ignored); directory scans never walk ignored trees such as node_modules.
    """

    found = Discovery()
    names = {PurePosixPath(p).name.lower() for p in paths}
    lowered = {p.lower() for p in paths}
    pyproject = _toml(_read(root, "pyproject.toml")) if "pyproject.toml" in lowered else {}
    tool = pyproject.get("tool", {}) if isinstance(pyproject.get("tool"), dict) else {}

    def has_python_tests() -> bool:
        return any(
            PurePosixPath(p).suffix == ".py" and (
                PurePosixPath(p).name.startswith("test_") or PurePosixPath(p).name.endswith("_test.py")
                or "tests" in PurePosixPath(p).parts[:-1] or "test" in PurePosixPath(p).parts[:-1])
            for p in paths)

    pytest_configured = (
        "pytest.ini" in names or "pytest" in tool
        or ("tox.ini" in names and "[pytest]" in (_read(root, "tox.ini") or ""))
        or ("setup.cfg" in names and re.search(r"^\[tool:pytest\]", _read(root, "setup.cfg") or "", re.M))
    )
    if pytest_configured or has_python_tests():
        found.candidates.append(Candidate(
            "pytest", "pytest", "python", "test", "python",
            ("-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"),
            "pytest configuration or Python test files were discovered."))
    if "ruff" in tool or "ruff.toml" in names or ".ruff.toml" in names:
        found.candidates.append(Candidate(
            "ruff", "ruff", "python", "lint", "python",
            ("-B", "-m", "ruff", "check", "--no-cache", "."),
            "Ruff configuration was discovered."))
    if "mypy" in tool or "mypy.ini" in names or ".mypy.ini" in names:
        found.candidates.append(Candidate(
            "mypy", "mypy", "python", "typecheck", "python",
            ("-B", "-m", "mypy", f"--cache-dir={os.devnull}", "."),
            "mypy configuration was discovered."))
    if names & {"requirements.txt", "pyproject.toml", "poetry.lock"} or any(
            n.startswith("requirements") and n.endswith(".txt") for n in names):
        found.candidates.append(Candidate(
            "pip-check", "pip check", "python", "security", "python",
            ("-B", "-m", "pip", "check"),
            "Python dependency manifests were discovered; verifies installed dependency consistency."))

    if "package.json" in lowered:
        _discover_node(root, found)
        if "package-lock.json" in lowered:
            found.candidates.append(Candidate(
                "npm-audit", "npm audit", "node", "security", "npm",
                ("audit", "--audit-level=high", "--ignore-scripts"),
                "package-lock.json was discovered; audits dependencies against the npm advisory "
                "service (requires network access)."))
    found.candidates.sort(key=lambda c: (_KIND_ORDER[c.kind], c.id))
    return found


def _discover_node(root: str, found: Discovery) -> None:
    text = _read(root, "package.json")
    try:
        scripts = json.loads(text or "{}").get("scripts", {})
    except (json.JSONDecodeError, AttributeError, RecursionError):
        found.gaps.append("package.json could not be parsed; Node checks were not discovered.")
        return
    if not isinstance(scripts, dict):
        found.gaps.append("package.json 'scripts' is not an object; Node checks were not discovered.")
        return
    interesting = {"test": "test", "lint": "lint", "typecheck": "typecheck",
                   "type-check": "typecheck", "build": "build"}
    for script, kind in interesting.items():
        command = scripts.get(script)
        if command is None:
            continue
        if not isinstance(command, str):
            found.gaps.append(f"package.json script '{script}' is not a string; not selected.")
            continue
        text_cmd = re.sub(r"^(?:cross-env\s+(?:[A-Z_]+=\S+\s+)+)", "", command.strip())
        tool_id = None
        if kind == "test":
            tool_id = next((name for pattern, name in _TEST_TOOLS if pattern.match(text_cmd)), None)
        elif kind == "lint" and _LINT.match(text_cmd):
            tool_id = "eslint"
        elif kind == "typecheck" and _TYPECHECK.match(text_cmd):
            tool_id = "tsc"
        elif kind == "build" and _BUILD.match(text_cmd):
            tool_id = "build"
        if tool_id is None:
            found.gaps.append(
                f"package.json script '{script}' runs an unrecognized command and was not selected.")
            continue
        args = ("test", "--ignore-scripts") if script == "test" else ("run", "--ignore-scripts", script)
        cid = f"{tool_id}" if kind != "build" else "npm-build"
        if script == "type-check":
            cid = "tsc-type-check"
        found.candidates.append(Candidate(
            cid, f"npm {script} ({tool_id})", "node", kind, "npm", args,
            f"package.json script '{script}' starts with a recognized {tool_id} command."))


def require_repository_path(path: str) -> str:
    try:
        return str(Path(path).resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise AppError("INVALID_REPOSITORY_PATH",
                       "The repository path does not exist or is not a directory.") from exc
