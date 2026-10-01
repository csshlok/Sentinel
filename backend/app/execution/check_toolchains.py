"""Which confined runtime an allowlisted check executable runs under (Phase 5).

This is the single source of the verification allowlist. Every allowlisted name
maps either to a confined runtime (a cached snapshot granted to one check box)
or to a refusal:

- ``python``, ``python3`` and ``pytest`` run the snapshot of the requested
  (already trusted) interpreter: its stdlib plus its ``site-packages``.
  ``pytest`` becomes ``<snapshot python> -m pytest``.
- ``node`` runs the ``node.exe`` snapshot. ``npm`` is always
  ``<node snapshot> <npm-cli.js inside the node snapshot>``; ``pnpm`` and
  ``yarn`` are the JS entry inside the project's ``node_modules`` snapshot.
  A ``.cmd`` shim is never run (it needs ``cmd.exe``). A missing entry is
  ``CHECK_RUNTIME_UNAVAILABLE``; Sentinel never falls back to the host.
- ``uv``, ``cargo``, ``go``, ``dotnet`` and anything else have no confined
  runtime: ``CHECK_TOOLCHAIN_UNCONFINED`` (409). They run only on the existing
  restricted path, and only for an actor holding the ``checks.unconfined``
  delegation for that Change; such a run is recorded with boundary
  ``UNCONFINED``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.errors import AppError
from backend.app.execution._process import minimal_environment
from backend.app.execution.check_box import BoxRuntime, python_box_runtime
from backend.app.execution.check_runtime import (
    PythonRuntime,
    RuntimeSnapshot,
    node_modules_snapshot,
    node_runtime,
    python_runtime,
)
from backend.app.execution.resolve import find_executable

CHECKS_UNCONFINED_SCOPE = "checks.unconfined"
BOUNDARY_APPCONTAINER = "APPCONTAINER"
BOUNDARY_UNCONFINED = "UNCONFINED"

PYTHON_TOOLCHAIN = "python"
NODE_TOOLCHAIN = "node"

# Allowlisted name -> confined toolchain.
CONFINED_TOOLCHAINS: dict[str, str] = {
    "python": PYTHON_TOOLCHAIN,
    "python3": PYTHON_TOOLCHAIN,
    "pytest": PYTHON_TOOLCHAIN,
    "node": NODE_TOOLCHAIN,
    "npm": NODE_TOOLCHAIN,
    "npm.cmd": NODE_TOOLCHAIN,
    "pnpm": NODE_TOOLCHAIN,
    "pnpm.cmd": NODE_TOOLCHAIN,
    "yarn": NODE_TOOLCHAIN,
    "yarn.cmd": NODE_TOOLCHAIN,
}
# Allowlisted, but with no confined runtime (opt-in only).
UNCONFINED_TOOLCHAINS = frozenset({"uv", "cargo", "go", "dotnet"})
ALLOWED_EXECUTABLES = frozenset(CONFINED_TOOLCHAINS) | UNCONFINED_TOOLCHAINS

# JS entry points, relative to the snapshot that holds them.
_NPM_ENTRY = ("node_modules", "npm", "bin", "npm-cli.js")
_PACKAGE_MANAGER_ENTRIES: dict[str, tuple[tuple[str, ...], ...]] = {
    "pnpm": (("pnpm", "bin", "pnpm.cjs"), ("pnpm", "bin", "pnpm.js")),
    "yarn": (("yarn", "bin", "yarn.js"),),
}


def check_toolchain_unconfined(executable: str) -> AppError:
    return AppError(
        "CHECK_TOOLCHAIN_UNCONFINED",
        "This toolchain has no confined check runtime. It runs only on the restricted "
        "unconfined path, and only with a delegated checks.unconfined authority for the Change.",
        status_code=409,
        details={"executable": executable, "required_scope": CHECKS_UNCONFINED_SCOPE},
    )


def check_runtime_unavailable(executable: str, reason: str) -> AppError:
    return AppError(
        "CHECK_RUNTIME_UNAVAILABLE",
        "The confined check runtime for this toolchain is unavailable; Sentinel does not "
        "fall back to the host.",
        status_code=409,
        details={"executable": executable, "reason": reason},
    )


def toolchain_of(executable: str) -> str | None:
    """The confined toolchain of an allowlisted name; None when it has none."""

    return CONFINED_TOOLCHAINS.get(executable)


def is_unconfined_toolchain(executable: str) -> bool:
    """True for a name that is allowlisted but has no confined runtime."""

    return executable in UNCONFINED_TOOLCHAINS


@dataclass(frozen=True, slots=True)
class ResolvedCheckRuntime:
    """A confined runtime plus the absolute argv prefix that starts the tool in the box."""

    toolchain: str
    runtime: BoxRuntime
    argv_prefix: tuple[str, ...]


def _find_host_node(source_root: Path | None) -> Path | None:
    # Without a repository there is nothing to exclude; a file is never a PATH parent.
    root = (Path(source_root).resolve() if source_root is not None
            else Path(sys.executable).resolve())
    return find_executable("node", minimal_environment(), root)


@dataclass(frozen=True, slots=True)
class RuntimeBuilders:
    """The snapshot builders; unit tests substitute fakes (real ones hash and copy)."""

    python: Callable[[Path], PythonRuntime] = python_runtime
    node: Callable[[Path], RuntimeSnapshot] = node_runtime
    node_modules: Callable[[Path], RuntimeSnapshot | None] = node_modules_snapshot
    find_node: Callable[[Path | None], Path | None] = _find_host_node

    @classmethod
    def for_root(cls, root: str | Path | None) -> RuntimeBuilders:
        """Builders that write snapshots under ``root`` (None: the default cache)."""

        if root is None:
            return cls()
        cache = Path(root)
        return cls(
            python=lambda interpreter: python_runtime(interpreter, root=cache),
            node=lambda node: node_runtime(node, root=cache),
            node_modules=lambda repo: node_modules_snapshot(repo, root=cache),
        )


def _node_entry(base: Path, parts: tuple[str, ...]) -> Path | None:
    candidate = base.joinpath(*parts)
    return candidate if candidate.is_file() else None


def resolve_check_runtime(
    executable: str, *, interpreter: str | Path | None = None,
    source_root: str | Path | None = None, builders: RuntimeBuilders | None = None,
) -> ResolvedCheckRuntime:
    """The confined runtime and argv prefix for ``executable``, or a named refusal.

    ``interpreter`` is the requested Python (default: this process's own
    interpreter); the caller must already have accepted it as trusted.
    ``source_root`` is the user repository, read only for its ``node_modules``.
    """

    builders = builders or RuntimeBuilders()
    toolchain = CONFINED_TOOLCHAINS.get(executable)
    if toolchain is None:
        raise check_toolchain_unconfined(executable)
    if toolchain == PYTHON_TOOLCHAIN:
        requested = Path(interpreter) if interpreter is not None else Path(sys.executable)
        runtime = python_box_runtime(builders.python(requested))
        python = str(runtime.executable)
        prefix = (python, "-m", "pytest") if executable == "pytest" else (python,)
        return ResolvedCheckRuntime(toolchain, runtime, prefix)

    source = Path(source_root) if source_root is not None else None
    host_node = builders.find_node(source)
    if host_node is None:
        raise check_runtime_unavailable(executable, "node was not found outside the repository")
    node = builders.node(Path(host_node))
    modules = builders.node_modules(source) if source is not None else None
    node_exe = node.path / Path(host_node).name
    snapshots = (node,) if modules is None else (node, modules)
    path_entries = (node.path,) if modules is None else (node.path, modules.path / ".bin")
    env = {} if modules is None else {"NODE_PATH": str(modules.path)}
    limitations = (() if modules is None else (
        "node_modules is a snapshot outside the check tree; it is reachable through "
        "NODE_PATH (CommonJS) only, not ES module resolution",))
    runtime = BoxRuntime(snapshots=snapshots, env=env, path_entries=path_entries,
                         executable=node_exe, limitations=limitations)
    base = executable.lower().removesuffix(".cmd")
    if base == "node":
        return ResolvedCheckRuntime(toolchain, runtime, (str(node_exe),))
    if base == "npm":
        entry = _node_entry(node.path, _NPM_ENTRY)
        if entry is None:
            raise check_runtime_unavailable(executable, "the node snapshot has no npm-cli.js")
        return ResolvedCheckRuntime(toolchain, runtime, (str(node_exe), str(entry)))
    if modules is None:
        raise check_runtime_unavailable(executable, "the project has no node_modules snapshot")
    for parts in _PACKAGE_MANAGER_ENTRIES[base]:
        entry = _node_entry(modules.path, parts)
        if entry is not None:
            return ResolvedCheckRuntime(toolchain, runtime, (str(node_exe), str(entry)))
    raise check_runtime_unavailable(
        executable, f"node_modules has no {base} JS entry point")
