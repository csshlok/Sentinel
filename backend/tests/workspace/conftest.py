"""Fixtures for real-AppContainer workspace tests.

Every profile created here uses the ``sentinel.test.`` prefix and is deleted by
the fixture teardown; a session finalizer also removes any leftover
``sentinel.test.*`` profile (and only those: spike profiles ``sentinel.a0.*``
and real workspaces are never touched).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import pytest


# GitHub-hosted windows-latest (a Server SKU) denies an AppContainer process the NUL
# device and spawning System32 executables: boxed Git fails on /dev/null and child
# processes get EPERM (Actions runs 36619252644, 36620065765). That is a host
# compatibility gap to investigate (Phase 2/3), not something these tests can fix,
# so the affected real-boundary tests skip there unless explicitly opted in.
HOSTED_RUNNER_APPCONTAINER_GAP = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("SENTINEL_CI_REAL_APPCONTAINER") != "1",
    reason="hosted runner denies NUL and System32 spawns inside an AppContainer; "
           "set SENTINEL_CI_REAL_APPCONTAINER=1 to run",
)

from backend.app.core.database import Database
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.support_kb import git, make_repo

TEST_PROFILE_PREFIX = "sentinel.test."

_SE_FILE_OBJECT = 1
_DACL_SECURITY_INFORMATION = 0x00000004
_LABEL_SECURITY_INFORMATION = 0x00000010
_SDDL_REVISION_1 = 1


def security_sddl(path: str | Path) -> str:
    """The DACL and mandatory-label SDDL of ``path``."""

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.ULONG),
    ]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID
    information = _DACL_SECURITY_INFORMATION | _LABEL_SECURITY_INFORMATION
    descriptor = wintypes.LPVOID()
    status = advapi32.GetNamedSecurityInfoW(
        str(path), _SE_FILE_OBJECT, information, None, None, None, None,
        ctypes.byref(descriptor),
    )
    assert status == 0, f"GetNamedSecurityInfoW failed with {status}"
    try:
        text = wintypes.LPWSTR()
        assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, _SDDL_REVISION_1, information, ctypes.byref(text), None
        ), ctypes.get_last_error()
        try:
            return text.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(text, wintypes.LPVOID))
    finally:
        kernel32.LocalFree(descriptor)


def repo_fingerprint(repo: Path) -> dict[str, str]:
    """Security descriptors, config digest, HEAD and refs (excluding refs/sentinel/)."""

    refs = [line for line in git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
            .splitlines() if not line.startswith("refs/sentinel/")]
    return {
        "sddl_root": security_sddl(repo),
        "sddl_git": security_sddl(repo / ".git"),
        "config_sha256": hashlib.sha256((repo / ".git" / "config").read_bytes()).hexdigest(),
        "head": git(repo, "rev-parse", "HEAD").strip(),
        "head_ref": (repo / ".git" / "HEAD").read_text(encoding="utf-8"),
        "refs": "\n".join(refs),
        "status": git(repo, "status", "--porcelain"),
    }


def _test_profiles() -> list[str]:
    import winreg

    from backend.app.execution.appcontainer import MAPPINGS_KEY

    monikers: list[str] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, MAPPINGS_KEY)
    except FileNotFoundError:
        return monikers
    with root:
        index = 0
        while True:
            try:
                sid = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, sid) as key:
                    moniker, _ = winreg.QueryValueEx(key, "Moniker")
            except OSError:
                continue
            if isinstance(moniker, str) and moniker.startswith(TEST_PROFILE_PREFIX):
                monikers.append(moniker)
    return monikers


def delete_test_profiles() -> list[str]:
    """Delete every ``sentinel.test.*`` profile and its Packages folder."""

    from backend.app.execution.appcontainer import (
        delete_profile,
        local_appdata_known_folder,
        profile_exists,
        remove_tree_no_follow,
    )

    removed = []
    packages = local_appdata_known_folder() / "Packages"
    for moniker in _test_profiles():
        assert moniker.startswith(TEST_PROFILE_PREFIX)
        folder = packages / moniker
        try:
            remove_tree_no_follow(folder / "AC")
        except OSError:
            pass
        delete_profile(moniker)
        remove_tree_no_follow(folder)
        removed.append(moniker)
    # Folders whose profile mapping is already gone (e.g. a child still held files
    # when an earlier teardown ran) are removed too -- still only sentinel.test.*.
    for folder in packages.glob(TEST_PROFILE_PREFIX + "*"):
        if folder.name.startswith(TEST_PROFILE_PREFIX) and not profile_exists(folder.name):
            remove_tree_no_follow(folder)
            removed.append(folder.name)
    return removed


@pytest.fixture(scope="session", autouse=True)
def _sweep_test_profiles():
    yield
    if IS_WINDOWS:
        delete_test_profiles()


@pytest.fixture
def node_exe() -> str:
    found = shutil.which("node")
    if not found:
        pytest.skip("node is not installed")
    resolved = Path(found).resolve()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve()
    if program_files not in resolved.parents:
        pytest.skip("node must be installed under Program Files to be readable by an AppContainer")
    return str(resolved)


@pytest.fixture
def user_repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "user-repo", {
        "calc.py": "def add(a, b):\n    return a + b\n",
        "rename_me.txt": "rename me\n",
        "delete_me.txt": "delete me\n",
        "README.md": "hello\n",
    })


@pytest.fixture
def workspace_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "workspace.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def workspace_manager(workspace_database: Database):
    from backend.app.workspace.manager import WorkspaceManager

    manager = WorkspaceManager(workspace_database, profile_prefix=TEST_PROFILE_PREFIX)
    yield manager
    teardown_workspaces(manager)


FAKE_NODE_ADAPTER = "fake-node"
DUMMY_CREDENTIAL_KIND = "claude-oauth-file"
DUMMY_ACCESS_TOKEN = "sk-ant-oat01-DUMMYcanaryLEAKtoken-0123456789abcdef"
DUMMY_REFRESH_TOKEN = "sk-ant-ort01-DUMMYcanaryREFRESH-9876543210"


@dataclass(frozen=True)
class FakeNodeLauncher:
    """An ``AgentLauncher`` whose "fake-node" adapter runs node in the workspace AppContainer.

    The profile mirrors ``claude`` (internetClient, staged home, the
    claude-oauth-file credential) without the tool snapshot. The broker stages
    ``credential_path`` -- a dummy file under ``tmp_path``, never ``~/.claude``.
    """

    launcher: object
    broker: object
    credential_path: Path
    access_token: str

    def launch(self, change_id, repository: Path, script: str, *, timeout: int = 60,
               output_limit: int = 65_536):
        from backend.app.contracts.models import AgentLaunchRequest

        return self.launcher.launch(change_id, str(repository), AgentLaunchRequest(
            adapter=FAKE_NODE_ADAPTER, executable="node", args=["-e", script],
            timeout_seconds=timeout), output_limit)


def dummy_credential_bytes() -> bytes:
    return json.dumps({"claudeAiOauth": {
        "accessToken": DUMMY_ACCESS_TOKEN, "refreshToken": DUMMY_REFRESH_TOKEN,
        "expiresAt": 1893456000000, "scopes": ["user:inference"],
    }}).encode("utf-8")


@pytest.fixture
def fake_node_launcher(workspace_manager, tmp_path: Path, node_exe: str) -> FakeNodeLauncher:
    from backend.app.credentials.broker import CredentialBroker
    from backend.app.credentials.memory_store import InMemoryCredentialStore
    from backend.app.execution.agent_profiles import BoundaryKind, RuntimeProfile
    from backend.app.execution.launcher import AgentAdapter, AgentLauncher

    credential = tmp_path / "fake-node-home" / ".claude" / ".credentials.json"
    credential.parent.mkdir(parents=True)
    credential.write_bytes(dummy_credential_bytes())
    broker = CredentialBroker(InMemoryCredentialStore(),
                              agent_credential_sources={DUMMY_CREDENTIAL_KIND: credential})
    launcher = AgentLauncher(
        adapters={FAKE_NODE_ADAPTER: AgentAdapter(FAKE_NODE_ADAPTER, frozenset({"node"}))},
        profiles={FAKE_NODE_ADAPTER: RuntimeProfile(
            FAKE_NODE_ADAPTER, BoundaryKind.APPCONTAINER, capabilities=("internetClient",),
            staged_home=True, credential_kind=DUMMY_CREDENTIAL_KIND, tool_snapshot=False,
        )},
        workspaces=workspace_manager, credentials=broker,
    )
    return FakeNodeLauncher(launcher, broker, credential, DUMMY_ACCESS_TOKEN)


BOXED_PYTHON_ADAPTER = "boxed-python"


@pytest.fixture(scope="session")
def boxed_python_runtime(tmp_path_factory):
    """A stdlib-only snapshot of this interpreter in a throwaway check-runtime cache."""

    import sys

    from backend.app.execution.check_runtime import python_runtime

    cache = tmp_path_factory.mktemp("boxed-python") / "check-runtimes"
    try:
        yield cache, python_runtime(sys.executable, root=cache).interpreter
    finally:
        shutil.rmtree(cache, ignore_errors=True)


@dataclass(frozen=True)
class BoxedPythonLauncher:
    """An ``AgentLauncher`` whose box is the ``claude`` profile running snapshot Python.

    The profile is ``BUILTIN_PROFILES["claude"]`` with only the tool snapshot and
    the native-executable requirement dropped (the interpreter is not a single
    self-contained exe), so any capability, drive or environment the claude box
    gains, this box gains too. The snapshot is readable only by a workspace's
    package SID granted through :meth:`grant` (03-01 harness).
    """

    launcher: object
    workspaces: object
    cache: Path
    interpreter: Path

    def prepare_workspace(self, change_id, repository: Path):
        """Create the Change's workspace without a run; returns its record."""

        from uuid import uuid4

        from backend.app.contracts.models import AgentRunStatus

        run_id = uuid4()
        lease = self.workspaces.ensure(change_id, str(repository), run_id=run_id)
        self.workspaces.finish_run(lease.id, run_id, facts=None,
                                   status=AgentRunStatus.PASSED.value)
        return self.workspaces.live_for_change(change_id)

    def grant(self, package_sid: str) -> None:
        from backend.app.execution.acl import grant_package_read

        grant_package_read(self.interpreter, package_sid, allowed_root=self.cache)

    def revoke(self, package_sid: str) -> None:
        from backend.app.execution.acl import revoke_package_read

        revoke_package_read(self.interpreter, package_sid, allowed_root=self.cache)

    def launch(self, change_id, repository: Path, args: list[str], *, timeout: int = 120,
               output_limit: int = 262_144):
        from backend.app.contracts.models import AgentLaunchRequest

        return self.launcher.launch(change_id, str(repository), AgentLaunchRequest(
            adapter=BOXED_PYTHON_ADAPTER, executable="python.exe", args=args,
            timeout_seconds=timeout), output_limit)


@pytest.fixture
def boxed_python_launcher(workspace_manager, tmp_path: Path, boxed_python_runtime,
                          monkeypatch) -> BoxedPythonLauncher:
    from dataclasses import replace

    from backend.app.credentials.broker import CredentialBroker
    from backend.app.credentials.memory_store import InMemoryCredentialStore
    from backend.app.execution.agent_profiles import BUILTIN_PROFILES
    from backend.app.execution.launcher import AgentAdapter, AgentLauncher

    cache, interpreter = boxed_python_runtime
    # AgentLaunchRequest.executable is at most 128 characters, so the snapshot is
    # found by name: its directory goes first on PATH ("python.exe" is not the
    # bare "python" that resolve_argv maps to this test's own interpreter).
    monkeypatch.setenv("PATH", os.pathsep.join([str(interpreter.path), os.environ["PATH"]]))
    claude = BUILTIN_PROFILES["claude"]
    profile = replace(
        claude, adapter=BOXED_PYTHON_ADAPTER, tool_snapshot=False,
        requires_native_executable=False,
        static_env=(*claude.static_env,
                    ("PYTHONHOME", str(interpreter.path)), ("PYTHONNOUSERSITE", "1"),
                    ("PYTHONDONTWRITEBYTECODE", "1"), ("PYTHONUTF8", "1")),
    )
    credential = tmp_path / "boxed-python-home" / ".claude" / ".credentials.json"
    credential.parent.mkdir(parents=True)
    credential.write_bytes(dummy_credential_bytes())
    broker = CredentialBroker(InMemoryCredentialStore(),
                              agent_credential_sources={claude.credential_kind: credential})
    launcher = AgentLauncher(
        adapters={BOXED_PYTHON_ADAPTER: AgentAdapter(
            BOXED_PYTHON_ADAPTER, frozenset({"python"}))},
        profiles={BOXED_PYTHON_ADAPTER: profile},
        workspaces=workspace_manager, credentials=broker,
    )
    return BoxedPythonLauncher(launcher, workspace_manager, cache, interpreter.path)


def teardown_workspaces(manager) -> None:
    """Release any leftover run lease and clean every unclean workspace (best effort)."""

    from backend.app.contracts.models import utc_now

    for record in manager.repository.list_unclean():
        try:
            if record.active_run_id is not None:
                manager.repository.end_run(record.id, record.active_run_id, updated_at=utc_now())
            manager.cleanup(record.id)
        except Exception:
            pass


def registered_test_profiles() -> set[str]:
    """The ``sentinel.test.*`` AppContainer monikers currently registered for this user."""

    return set(_test_profiles())


def create_junction(target: Path, link: Path) -> None:
    """A directory junction ``link`` -> ``target`` (what an agent could plant)."""

    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def has_object(repo: Path, sha: str, *, kind: str = "commit") -> bool:
    """Whether ``repo``'s object store contains ``sha`` of ``kind`` (plain git, read-only)."""

    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{{kind}}}"],
        capture_output=True,
    ).returncode == 0
