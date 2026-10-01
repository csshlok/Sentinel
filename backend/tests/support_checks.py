"""Test harness: check boxes whose 'box' is a plain host child (NO containment).

Phase 5 routes every verification, assurance and diff-coverage command through
``CheckBoxes``. Logic tests (status mapping, output bounds, report parsing,
tree copy, journaling) use this harness so they run in milliseconds instead of
building a real AppContainer profile and runtime snapshot per check. It runs
the real ``CheckBoxes``/``CheckBox`` code (row, tree copy from ``git ls-files``,
scratch, journal, cleanup) with a fake Windows layer: the profile is a folder,
grants are recorded, and ``spawn`` starts the command on the host with the
box environment. Containment itself is proven only by the real-boundary tests
(``test_check_box_real.py``, ``test_confined_runner.py``,
``test_diff_coverage_confined.py``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.database import Database
from backend.app.core.journal import JournalWriter
from backend.app.execution.appcontainer import (
    AppContainerFacts,
    AppContainerProfile,
    remove_tree_no_follow,
)
from backend.app.execution.check_box import BoxPlatform, BoxRuntime, CheckBoxes
from backend.app.execution._process import minimal_environment
from backend.app.execution.check_toolchains import (
    ResolvedCheckRuntime,
    check_runtime_unavailable,
    check_toolchain_unconfined,
    toolchain_of,
)
from backend.app.execution.resolve import find_executable

HOST_SID = "S-1-15-2-1111111111-2222222222-3333333333-444444444-555555555-666666666-777777777"


class HostBoxWindows:
    """Fake profiles under ``root``; spawn is a host child with the box environment."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.profiles: set[str] = set()
        self.spawned: list[dict] = []
        self.granted: list[tuple[str, str]] = []

    def ensure_profile(self, name: str, *, display_name: str):
        self.profiles.add(name)
        container = self.root / "Packages" / name / "AC"
        container.mkdir(parents=True, exist_ok=True)
        return AppContainerProfile(name, HOST_SID, container), True

    def delete_profile(self, name: str) -> None:
        self.profiles.discard(name)
        remove_tree_no_follow(self.root / "Packages" / name)

    def base_environment(self, container, *, path_entries=()):
        temp = Path(container) / "Temp"
        temp.mkdir(parents=True, exist_ok=True)
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        return {
            "SystemRoot": system_root, "windir": system_root,
            "COMSPEC": os.path.join(system_root, "System32", "cmd.exe"),
            "PATH": os.pathsep.join([*(str(p) for p in path_entries),
                                     os.path.join(system_root, "System32")]),
            "LOCALAPPDATA": str(self.root), "TEMP": str(temp), "TMP": str(temp),
        }

    def spawn(self, argv, *, cwd, env, redact, profile_name, expected_package_sid,
              capabilities):
        self.spawned.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env),
                             "capabilities": tuple(capabilities)})
        process = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(env), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        )
        # Clearly fake facts: a host child is not an AppContainer process.
        process.appcontainer = AppContainerFacts(
            profile_name=profile_name, package_sid=expected_package_sid,
            is_appcontainer=False, integrity_rid=0x2000, capability_sids=(),
            job_verified=False, verified_at=datetime.now(UTC),
        )
        return process

    def platform(self) -> BoxPlatform:
        return BoxPlatform(
            derive_package_sid=lambda name: HOST_SID,
            ensure_profile=self.ensure_profile, delete_profile=self.delete_profile,
            profile_exists=lambda name: name in self.profiles,
            container_folder=lambda sid: self.root / "unused",
            local_appdata=lambda: self.root, base_environment=self.base_environment,
            spawn=self.spawn,
            grant=lambda path, sid, *, allowed_root=None: self.granted.append((str(path), sid)),
            revoke=lambda path, sid, *, allowed_root=None: None,
        )


def host_resolver(executable: str, *, interpreter=None, source_root=None) -> ResolvedCheckRuntime:
    """The HOST toolchain (no snapshot): this interpreter, or node/npm from PATH.

    The mapping and refusals are the production ones (``toolchain_of``); only
    the runtime is the host's, so a logic test needs no snapshot.
    """

    toolchain = toolchain_of(executable)
    if toolchain is None:
        raise check_toolchain_unconfined(executable)
    if toolchain == "python":
        python = str(interpreter or sys.executable)
        prefix = (python, "-m", "pytest") if executable == "pytest" else (python,)
        return ResolvedCheckRuntime("python", BoxRuntime(executable=Path(python)), prefix)
    root = Path(source_root).resolve() if source_root is not None else Path(sys.executable)
    node = find_executable("node", minimal_environment(), root)
    if node is None:
        raise check_runtime_unavailable(executable, "node was not found outside the repository")
    base = executable.lower().removesuffix(".cmd")
    if base == "node":
        prefix: tuple[str, ...] = (str(node),)
    elif base == "npm":
        cli = node.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        if not cli.is_file():
            raise check_runtime_unavailable(executable, "npm-cli.js was not found")
        prefix = (str(node), str(cli))
    else:
        raise check_runtime_unavailable(executable, "the host harness has no " + base)
    return ResolvedCheckRuntime("node", BoxRuntime(executable=node,
                                                   path_entries=(node.parent,)), prefix)


def host_check_boxes(directory: Path, database: Database | None = None, *,
                     journal: JournalWriter | None = None, evidence_guard=None,
                     ) -> tuple[CheckBoxes, HostBoxWindows]:
    """A ``CheckBoxes`` over a fresh database (unless given) and a host 'box' layer."""

    directory.mkdir(parents=True, exist_ok=True)
    if database is None:
        database = Database(directory / "checks.sqlite3")
        database.initialize()
    windows = HostBoxWindows(directory / "localappdata")
    windows.root.mkdir(parents=True, exist_ok=True)
    boxes = CheckBoxes(database, journal=journal or JournalWriter(database),
                       profile_prefix="sentinel.test.", runtime_root=directory / "cache",
                       platform=windows.platform(), resolver=host_resolver,
                       evidence_guard=evidence_guard)
    return boxes, windows


def host_assurance_engine(directory: Path, database: Database, **kwargs):
    """An ``AssuranceEngine`` whose checks (and diff coverage) use the host harness.

    Mirrors ``EvidenceService``'s own default engine (default patch limit).
    """

    from backend.app.assurance.engine import AssuranceEngine
    from backend.app.assurance.service import DEFAULT_PATCH_LIMIT

    boxes, _ = host_check_boxes(directory, database)
    kwargs.setdefault("patch_limit_bytes", DEFAULT_PATCH_LIMIT)
    return AssuranceEngine(checks=boxes, **kwargs)
