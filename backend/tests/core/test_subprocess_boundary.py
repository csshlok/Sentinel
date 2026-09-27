"""Architecture test: only ``execution/`` and ``git/safe_exec.py`` start processes.

Rule (phase 04 decision 4). Every process Sentinel starts is created by a module
under ``backend/app/execution/`` (bounded capture, minimal environment, tool
probes, verification commands, the supervised agent launcher) or by
``backend/app/git/safe_exec.py`` (the hardened Git harness). Any other module
under ``backend/app/`` that wants a process must go through one of those.

Allowlist: every file under ``backend/app/execution/`` and exactly
``backend/app/git/safe_exec.py``. ``test_allowlist_entries_exist`` fails if
either is renamed, so a rename cannot silently widen or neutralize the rule.

Why a static AST scan: it inspects every module without importing it, runs in
milliseconds, and reports the exact file, line and form. Flagged forms are:
importing ``subprocess`` or ``pty``; importing ``capture`` (or ``*``) or the
module object from ``execution._process``; calling ``_process.capture``;
``os.system``/``os.popen``/``os.startfile``/``os.spawn*``/``os.exec*``/
``os.posix_spawn*`` (called or imported from ``os``);
``asyncio.create_subprocess_exec``/``_shell``; ``pty.spawn``; and
``importlib.import_module("subprocess")``/``__import__("subprocess")`` with a
string literal. ``minimal_environment``/``CapturedProcess`` imports and
unrelated ``.capture()`` method calls (``self._git.capture``) are allowed.

Limit: non-literal dynamic imports (``importlib.import_module(name)`` with a
computed name, ``getattr(os, "sys" + "tem")``) are out of reach of static
analysis and are left to code review.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
EXECUTION_DIR = APP_ROOT / "execution"
SAFE_EXEC = APP_ROOT / "git" / "safe_exec.py"

_BANNED_MODULES = frozenset({"subprocess", "pty"})
_OS_EXACT = frozenset({"system", "popen", "startfile"})
_OS_PREFIXES = ("spawn", "exec", "posix_spawn")
_ASYNCIO_SPAWNS = frozenset({"create_subprocess_exec", "create_subprocess_shell"})
_PROCESS_MODULE = "backend.app.execution._process"


def _is_os_spawn(name: str) -> bool:
    return name in _OS_EXACT or name.startswith(_OS_PREFIXES)


def _is_process_module(module: str | None, level: int) -> bool:
    if not module:
        return False
    if level == 0:
        return module == _PROCESS_MODULE
    return module == "_process" or module.endswith("._process")


def _is_execution_package(module: str | None, level: int) -> bool:
    if level == 0:
        return module == "backend.app.execution"
    return module is not None and (module == "execution" or module.endswith(".execution"))


def _call_target(func: ast.expr) -> tuple[str | None, str | None]:
    """``(base_name, attribute)`` for ``base.attr(...)``; ``(None, name)`` for ``name(...)``."""

    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    if isinstance(func, ast.Name):
        return None, func.id
    return None, None


def find_process_spawn_violations(source: str, *, filename: str) -> list[str]:
    """Every direct process-creation form in ``source`` as ``file:line: form``."""

    tree = ast.parse(source, filename=filename)
    found: list[str] = []

    def flag(node: ast.AST, form: str) -> None:
        found.append(f"{filename}:{getattr(node, 'lineno', '?')}: {form}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _BANNED_MODULES:
                    flag(node, f"import {alias.name}")
                elif alias.name == _PROCESS_MODULE:
                    flag(node, f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = {alias.name for alias in node.names}
            if node.level == 0 and module.split(".")[0] in _BANNED_MODULES:
                flag(node, f"from {module} import {', '.join(sorted(names))}")
            elif _is_process_module(node.module, node.level) and names & {"capture", "*"}:
                flag(node, f"from {'.' * node.level}{module} import capture")
            elif _is_execution_package(node.module, node.level) and "_process" in names:
                flag(node, f"from {'.' * node.level}{module} import _process")
            elif node.level == 0 and module == "os":
                for name in sorted(n for n in names if _is_os_spawn(n) or n == "*"):
                    flag(node, f"from os import {name}")
            elif node.level == 0 and module == "asyncio" and names & (_ASYNCIO_SPAWNS | {"*"}):
                flag(node, "from asyncio import create_subprocess_*")
        elif isinstance(node, ast.Call):
            base, attribute = _call_target(node.func)
            if base == "_process" and attribute == "capture":
                flag(node, "_process.capture(...)")
            elif base == "os" and attribute and _is_os_spawn(attribute):
                flag(node, f"os.{attribute}(...)")
            elif base == "asyncio" and attribute in _ASYNCIO_SPAWNS:
                flag(node, f"asyncio.{attribute}(...)")
            elif base == "pty" and attribute == "spawn":
                flag(node, "pty.spawn(...)")
            elif ((base == "importlib" and attribute == "import_module")
                  or (base is None and attribute == "__import__")):
                first = node.args[0] if node.args else None
                if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                        and first.value.split(".")[0] in _BANNED_MODULES):
                    flag(node, f"dynamic import of {first.value!r}")
    return found


def _is_allowlisted(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == SAFE_EXEC.resolve() or EXECUTION_DIR.resolve() in resolved.parents


def _scanned_files() -> list[Path]:
    return sorted(path for path in APP_ROOT.rglob("*.py") if not _is_allowlisted(path))


def test_no_module_outside_execution_spawns_processes_directly() -> None:
    files = _scanned_files()
    violations: list[str] = []
    for path in files:
        relative = path.relative_to(APP_ROOT.parents[1]).as_posix()
        violations.extend(
            find_process_spawn_violations(path.read_text(encoding="utf-8"), filename=relative))
    assert len(files) >= 50, f"scan covered only {len(files)} files"
    assert not violations, (
        "Process creation outside backend/app/execution/ and backend/app/git/safe_exec.py:\n"
        + "\n".join(violations))


VIOLATING_SOURCES = {
    "import subprocess": "import subprocess\n",
    "import subprocess as sp": "import subprocess as sp\n",
    "from subprocess import run": "from subprocess import run\n",
    "absolute capture import": "from backend.app.execution._process import capture\n",
    "relative capture import": "from ..execution._process import capture\n",
    "star import from _process": "from backend.app.execution._process import *\n",
    "import _process module object": "from backend.app.execution import _process\n",
    "import _process module path": "import backend.app.execution._process\n",
    "_process.capture call": "_process.capture(['x'], cwd='.', env={}, timeout=1, limit=1)\n",
    "os.system": "import os\nos.system('x')\n",
    "os.popen": "import os\nos.popen('x')\n",
    "os.spawnv": "import os\nos.spawnv(0, 'x', ['x'])\n",
    "os.execv": "import os\nos.execv('x', ['x'])\n",
    "os.posix_spawn": "import os\nos.posix_spawn('x', ['x'], {})\n",
    "os.startfile": "import os\nos.startfile('x')\n",
    "from os import system": "from os import system\n",
    "asyncio.create_subprocess_exec": "import asyncio\nasyncio.create_subprocess_exec('x')\n",
    "asyncio.create_subprocess_shell": "import asyncio\nasyncio.create_subprocess_shell('x')\n",
    "import pty": "import pty\n",
    "pty.spawn": "pty.spawn('x')\n",
    "importlib.import_module subprocess": "import importlib\nimportlib.import_module('subprocess')\n",
    "__import__ subprocess": "__import__('subprocess')\n",
}


@pytest.mark.parametrize("form", sorted(VIOLATING_SOURCES))
def test_scanner_detects_each_violation_form(form: str) -> None:
    violations = find_process_spawn_violations(VIOLATING_SOURCES[form], filename="synthetic.py")
    assert violations, f"scanner missed: {form}"
    assert all(item.startswith("synthetic.py:") for item in violations)


BENIGN_SOURCES = {
    "minimal_environment import": (
        "from backend.app.execution._process import minimal_environment, CapturedProcess\n"),
    "relative minimal_environment import": (
        "from ..execution._process import minimal_environment\n"),
    "method named capture": "self._git.capture(x)\nself._environment.capture(a, b)\n",
    "string literal os.system": "KEY = 'os.system'\nfacts = [plain('os.system', 'x')]\n",
    "os.path.join": "import os\nos.path.join('a', 'b')\nos.environ.get('X')\n",
    "execution package other module": "from backend.app.execution.tool_probe import run_tool_probe\n",
    "importlib with other literal": "import importlib\nimportlib.import_module('json')\n",
}


@pytest.mark.parametrize("form", sorted(BENIGN_SOURCES))
def test_scanner_allows_benign_forms(form: str) -> None:
    assert find_process_spawn_violations(BENIGN_SOURCES[form], filename="benign.py") == []


def test_allowlist_entries_exist() -> None:
    assert EXECUTION_DIR.is_dir()
    assert (EXECUTION_DIR / "_process.py").is_file()
    assert SAFE_EXEC.is_file()
