"""Fixtures for real-AppContainer workspace tests.

Every profile created here uses the ``sentinel.test.`` prefix and is deleted by
the fixture teardown; a session finalizer also removes any leftover
``sentinel.test.*`` profile (and only those: spike profiles ``sentinel.a0.*``
and real workspaces are never touched).
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
from ctypes import wintypes
from pathlib import Path

import pytest

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


def has_object(repo: Path, sha: str) -> bool:
    """Whether ``repo``'s object store contains ``sha`` (plain git, read-only)."""

    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
    ).returncode == 0
