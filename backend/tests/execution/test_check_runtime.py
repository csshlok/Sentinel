"""Manifest-addressed check runtime snapshots (execution/check_runtime.py)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.execution import check_runtime
from backend.app.execution._process import CapturedProcess
from backend.app.execution.acl import grant_package_read, revoke_package_read
from backend.app.execution.check_runtime import (
    RuntimeSnapshot,
    check_runtime_root,
    manifest_digest,
    node_modules_snapshot,
    node_runtime,
    python_runtime,
    snapshot_tree,
)


def _tree(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def cache(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return _tree(tmp_path / "src", {"a.txt": "alpha\n", "pkg/b.py": "x = 1\n", "pkg/sub/c.bin": "c"})


def _files(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


# --------------------------------------------------------------------- root


def test_root_is_under_localappdata_sentinel(tmp_path: Path) -> None:
    root = check_runtime_root({"LOCALAPPDATA": str(tmp_path)}, create=False)
    assert root == tmp_path / "Sentinel" / "check-runtimes"
    assert not root.exists()


def test_root_is_created_and_restricted(tmp_path: Path, monkeypatch) -> None:
    restricted: list[tuple[Path, bool]] = []
    monkeypatch.setattr(check_runtime, "restrict_to_current_user",
                        lambda path, *, directory=False: restricted.append((path, directory)) or True)
    root = check_runtime_root({"LOCALAPPDATA": str(tmp_path)})
    assert root.is_dir()
    assert restricted == [(root, True)]


# --------------------------------------------------------------------- snapshot_tree


def test_snapshot_copies_exactly_the_source_under_its_digest(source: Path, cache: Path) -> None:
    snapshot = snapshot_tree(source, kind="python-deps", root=cache)
    assert isinstance(snapshot, RuntimeSnapshot)
    assert snapshot.path == cache / "python-deps" / snapshot.manifest_digest
    assert _files(snapshot.path) == _files(source)
    assert snapshot.bytes == sum(len(v) for v in _files(source).values())
    # No partial directories remain.
    assert [p.name for p in (cache / "python-deps").iterdir()] == [snapshot.manifest_digest]


def test_identical_source_reuses_the_entry(source: Path, cache: Path, tmp_path: Path) -> None:
    first = snapshot_tree(source, kind="node-modules", root=cache)
    marker = first.path.stat().st_mtime_ns
    copy = tmp_path / "copy"
    for relative, data in _files(source).items():
        (copy / relative).parent.mkdir(parents=True, exist_ok=True)
        (copy / relative).write_bytes(data)
    second = snapshot_tree(copy, kind="node-modules", root=cache)
    assert second == first
    assert first.path.stat().st_mtime_ns == marker


def test_changed_file_produces_a_new_entry_and_keeps_the_old_one(source: Path, cache: Path) -> None:
    first = snapshot_tree(source, kind="node-modules", root=cache)
    (source / "pkg" / "b.py").write_text("x = 2\n", encoding="utf-8")
    second = snapshot_tree(source, kind="node-modules", root=cache)
    assert second.manifest_digest != first.manifest_digest
    assert (first.path / "pkg" / "b.py").read_text(encoding="utf-8") == "x = 1\n"
    assert (second.path / "pkg" / "b.py").read_text(encoding="utf-8") == "x = 2\n"


def test_digest_covers_path_size_and_content(source: Path, cache: Path, tmp_path: Path) -> None:
    base = snapshot_tree(source, kind="node", root=cache).manifest_digest
    renamed = _tree(tmp_path / "renamed", {"a2.txt": "alpha\n", "pkg/b.py": "x = 1\n", "pkg/sub/c.bin": "c"})
    assert snapshot_tree(renamed, kind="node", root=cache).manifest_digest != base
    assert manifest_digest([]) != base


@pytest.mark.parametrize("tamper", ["modify", "add", "remove"])
def test_tampered_entry_fails_closed_and_is_left_untouched(
    source: Path, cache: Path, tamper: str,
) -> None:
    snapshot = snapshot_tree(source, kind="python", root=cache)
    if tamper == "modify":
        (snapshot.path / "a.txt").write_text("evil\n", encoding="utf-8")
    elif tamper == "add":
        (snapshot.path / "pkg" / "planted.pth").write_text("import evil\n", encoding="utf-8")
    else:
        (snapshot.path / "pkg" / "b.py").unlink()
    before = _files(snapshot.path)
    with pytest.raises(AppError) as raised:
        snapshot_tree(source, kind="python", root=cache)
    assert raised.value.code == "CHECK_RUNTIME_TAMPERED"
    assert raised.value.status_code == 409
    assert raised.value.details["manifest_digest"] == snapshot.manifest_digest
    assert _files(snapshot.path) == before


def test_positive_control_untampered_entry_is_reused(source: Path, cache: Path) -> None:
    snapshot = snapshot_tree(source, kind="python", root=cache)
    assert snapshot_tree(source, kind="python", root=cache) == snapshot


def test_ignored_directory_names_are_left_out_at_any_depth(tmp_path: Path, cache: Path) -> None:
    src = _tree(tmp_path / "base", {
        "python.exe": "exe", "Lib/os.py": "os", "Lib/site-packages/evil.py": "no",
        "Lib/test/test_x.py": "no", "Lib/json/__pycache__/x.pyc": "no", "Lib/json/__init__.py": "j",
        "Tools/x.py": "no",
    })
    snapshot = snapshot_tree(src, kind="python", root=cache,
                             ignore=check_runtime.PYTHON_BASE_IGNORE)
    assert sorted(_files(snapshot.path)) == ["Lib/json/__init__.py", "Lib/os.py", "python.exe"]


def test_size_limit_refuses_before_copying(source: Path, cache: Path) -> None:
    with pytest.raises(AppError) as raised:
        snapshot_tree(source, kind="node-modules", root=cache, size_limit=5)
    assert raised.value.code == "CHECK_RUNTIME_TOO_LARGE"
    assert raised.value.status_code == 409
    assert not (cache / "node-modules").exists() or not any((cache / "node-modules").iterdir())


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_junction_in_source_is_refused(source: Path, cache: Path, tmp_path: Path) -> None:
    import _winapi

    outside = _tree(tmp_path / "outside", {"secret.txt": "secret"})
    _winapi.CreateJunction(str(outside), str(source / "pkg" / "link"))
    with pytest.raises(AppError) as raised:
        snapshot_tree(source, kind="node-modules", root=cache)
    assert raised.value.code == "CHECK_RUNTIME_UNSAFE_SOURCE"
    assert "pkg/link" in raised.value.details["reason"]
    assert not (cache / "node-modules").exists() or not any((cache / "node-modules").iterdir())


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
@pytest.mark.parametrize("where", ["base_prefix", "purelib"])
def test_python_runtime_refuses_an_install_with_a_reparse_point(
    monkeypatch, cache: Path, tmp_path: Path, where: str,
) -> None:
    """Intended behaviour behind the hosted-runner skip of the real snapshot test.

    A Python install containing a junction (as the GitHub-hosted toolcache
    install does) is refused, not followed: the link could point the box's
    read grant at anything. Nothing is written into the cache.
    """

    import _winapi

    base = _tree(tmp_path / "install", {"python.exe": "exe", "Lib/os.py": "x = 1\n"})
    purelib = _tree(tmp_path / "site-packages", {"pytest/__init__.py": "x = 1\n"})
    outside = _tree(tmp_path / "outside", {"secret.txt": "secret"})
    linked = (base / "Lib") if where == "base_prefix" else purelib
    _winapi.CreateJunction(str(outside), str(linked / "linked"))
    monkeypatch.setattr(check_runtime, "_interpreter_facts", lambda interpreter: (base, purelib))
    with pytest.raises(AppError) as raised:
        python_runtime(base / "python.exe", root=cache)
    assert raised.value.code == "CHECK_RUNTIME_UNSAFE_SOURCE"
    assert "linked" in raised.value.details["reason"]
    refused = cache / ("python" if where == "base_prefix" else "python-deps")
    leftovers = [path for path in refused.rglob("*") if path.is_file()] if refused.exists() else []
    assert leftovers == []
    assert not any("secret" in path.name for path in cache.rglob("*")) if cache.exists() else True


def test_symlink_in_source_is_refused(source: Path, cache: Path) -> None:
    try:
        os.symlink(source / "a.txt", source / "pkg" / "alias.txt")
    except OSError:
        pytest.skip("creating a symlink needs Developer Mode or the privilege")
    with pytest.raises(AppError) as raised:
        snapshot_tree(source, kind="node-modules", root=cache)
    assert raised.value.code == "CHECK_RUNTIME_UNSAFE_SOURCE"


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_source_that_is_itself_a_junction_is_refused(source: Path, cache: Path, tmp_path: Path) -> None:
    import _winapi

    link = tmp_path / "link"
    _winapi.CreateJunction(str(source), str(link))
    with pytest.raises(AppError) as raised:
        snapshot_tree(link, kind="node", root=cache)
    assert raised.value.code == "CHECK_RUNTIME_UNSAFE_SOURCE"


def test_invalid_kind_is_rejected(source: Path, cache: Path) -> None:
    with pytest.raises(ValueError):
        snapshot_tree(source, kind="../escape", root=cache)


# --------------------------------------------------------------------- python_runtime


@pytest.fixture
def fake_python(tmp_path: Path, monkeypatch):
    base = _tree(tmp_path / "Python314", {
        "python.exe": "exe", "python314.dll": "dll", "Lib/os.py": "os",
        "Lib/site-packages/README.txt": "base site", "Lib/idlelib/x.py": "no",
        "Lib/tkinter/x.py": "no", "include/Python.h": "no", "libs/python314.lib": "no",
    })
    purelib = _tree(tmp_path / "venv" / "Lib" / "site-packages", {
        "pytest/__init__.py": "pytest", "pkg/__pycache__/x.pyc": "no",
        "inside.pth": "pkg\n# comment\nimport os\n",
        "outside.pth": str(tmp_path / "elsewhere") + "\n",
        "__editable__.project-0.1.pth": "import __editable___finder\n",
        "legacy.egg-link": str(tmp_path / "proj") + "\n.\n",
    })
    interpreter = tmp_path / "venv" / "Scripts" / "python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("venv python", encoding="utf-8")
    calls: list[dict] = []

    def fake_capture(argv, *, cwd, env, timeout, limit, **kwargs):
        calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env),
                      "cwd_existed": Path(cwd).is_dir()})
        payload = json.dumps({"base_prefix": str(base), "purelib": str(purelib)}).encode()
        return CapturedProcess(0, payload, b"", False, False, False, "")

    monkeypatch.setattr(check_runtime, "capture", fake_capture)
    return interpreter, base, purelib, calls


def test_python_runtime_snapshots_stdlib_and_deps(fake_python, cache: Path) -> None:
    interpreter, _, _, _ = fake_python
    runtime = python_runtime(interpreter, root=cache)
    base_snapshot, deps, limitations = runtime
    assert base_snapshot.path.parent == cache / "python"
    assert sorted(_files(base_snapshot.path)) == ["Lib/os.py", "python.exe", "python314.dll"]
    assert deps.path.parent == cache / "python-deps"
    assert "pytest/__init__.py" in _files(deps.path)
    assert not any("__pycache__" in name for name in _files(deps.path))
    assert limitations == (
        "__editable__.project-0.1.pth: editable install whose source is outside the dependency snapshot",
        "legacy.egg-link: egg-link to a source tree outside the dependency snapshot",
        "outside.pth: path entry outside the dependency snapshot",
    )


def test_interpreter_facts_probe_runs_isolated_outside_the_repository(
    fake_python, cache: Path,
) -> None:
    interpreter, _, _, calls = fake_python
    python_runtime(interpreter, root=cache)
    assert len(calls) == 1
    call = calls[0]
    assert call["argv"][:4] == [str(interpreter), "-I", "-S", "-c"]
    assert call["cwd_existed"]
    repository = Path(__file__).resolve().parents[3]
    assert repository not in call["cwd"].resolve().parents
    assert call["cwd"].resolve() != repository
    assert not call["cwd"].exists()  # the fresh probe directory is removed afterwards
    assert not any(key.startswith("PYTHON") for key in call["env"])


def test_failed_probe_fails_closed(fake_python, cache: Path, monkeypatch) -> None:
    interpreter, _, _, _ = fake_python
    monkeypatch.setattr(check_runtime, "capture", lambda *a, **k: CapturedProcess(
        1, b"", b"boom", False, False, False, ""))
    with pytest.raises(AppError) as raised:
        python_runtime(interpreter, root=cache)
    assert raised.value.code == "CHECK_RUNTIME_FAILED"


def test_relative_interpreter_is_refused(cache: Path) -> None:
    with pytest.raises(AppError) as raised:
        python_runtime("python.exe", root=cache)
    assert raised.value.code == "CHECK_RUNTIME_FAILED"


# --------------------------------------------------------------------- node


def test_node_runtime_holds_node_and_npm_only(tmp_path: Path, cache: Path) -> None:
    nodejs = _tree(tmp_path / "nodejs", {
        "node.exe": "node", "npm.cmd": "no", "node_modules/npm/bin/npm-cli.js": "npm",
        "node_modules/corepack/x.js": "no",
    })
    snapshot = node_runtime(nodejs / "node.exe", root=cache)
    assert snapshot.path.parent == cache / "node"
    assert sorted(_files(snapshot.path)) == ["node.exe", "node_modules/npm/bin/npm-cli.js"]
    assert node_runtime(nodejs / "node.exe", root=cache) == snapshot


def test_node_modules_snapshot(tmp_path: Path, cache: Path) -> None:
    repo = tmp_path / "repo"
    assert node_modules_snapshot(repo, root=cache) is None
    (repo / "node_modules").mkdir(parents=True)
    assert node_modules_snapshot(repo, root=cache) is None
    _tree(repo / "node_modules", {"left-pad/index.js": "module.exports = 1;"})
    snapshot = node_modules_snapshot(repo, root=cache)
    assert snapshot is not None
    assert _files(snapshot.path) == {"left-pad/index.js": b"module.exports = 1;"}


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_node_modules_junction_is_refused(tmp_path: Path, cache: Path) -> None:
    import _winapi

    repo = tmp_path / "repo"
    repo.mkdir()
    target = _tree(tmp_path / "store", {"x/index.js": "1"})
    _winapi.CreateJunction(str(target), str(repo / "node_modules"))
    with pytest.raises(AppError) as raised:
        node_modules_snapshot(repo, root=cache)
    assert raised.value.code == "CHECK_RUNTIME_UNSAFE_SOURCE"


# --------------------------------------------------------------------- package-SID grants

PACKAGE_SID = "S-1-15-2-1111111111-2222222222-333333333-444444444-555555555-666666666-777777777"
FAKE_ICACLS = Path(r"C:\Windows\System32\icacls.exe")


class _Recorder:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.returncode = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, self.returncode, b"", b"")


@pytest.fixture
def icacls_recorder(monkeypatch) -> _Recorder:
    fake = _Recorder()
    monkeypatch.setattr("backend.app.execution.acl.subprocess.run", fake)
    monkeypatch.setattr("backend.app.execution.acl.icacls_executable", lambda: FAKE_ICACLS)
    monkeypatch.setattr("backend.app.execution.acl.os.name", "nt")
    return fake


@pytest.fixture
def entry(cache: Path) -> Path:
    path = cache / "python" / ("a" * 64)
    path.mkdir(parents=True)
    (path / "python.exe").write_text("exe", encoding="utf-8")
    return path


def test_grant_adds_exactly_one_inheritable_rx_ace(icacls_recorder, entry: Path, cache: Path) -> None:
    grant_package_read(entry, PACKAGE_SID, allowed_root=cache)
    assert len(icacls_recorder.calls) == 1
    argv, kwargs = icacls_recorder.calls[0]
    assert argv == [str(FAKE_ICACLS), str(entry), "/grant", f"*{PACKAGE_SID}:(OI)(CI)(RX)"]
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == FAKE_ICACLS.parent


def test_revoke_removes_only_that_sid(icacls_recorder, entry: Path, cache: Path) -> None:
    revoke_package_read(entry, PACKAGE_SID, allowed_root=cache)
    argv, _ = icacls_recorder.calls[0]
    assert argv == [str(FAKE_ICACLS), str(entry), "/remove:g", f"*{PACKAGE_SID}"]


@pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")
def test_concurrent_grants_and_revokes_on_one_entry_are_serialized(
    monkeypatch, entry: Path, cache: Path,
) -> None:
    """WR-03: icacls rewrites the whole DACL, so two changes on one entry may never overlap."""

    import threading
    import time

    in_flight: list[int] = [0]
    peak: list[int] = [0]
    guard = threading.Lock()

    def slow_icacls(argv, **_kwargs):
        with guard:
            in_flight[0] += 1
            peak[0] = max(peak[0], in_flight[0])
        time.sleep(0.05)
        with guard:
            in_flight[0] -= 1
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("backend.app.execution.acl.subprocess.run", slow_icacls)
    monkeypatch.setattr("backend.app.execution.acl.icacls_executable", lambda: FAKE_ICACLS)
    sids = [PACKAGE_SID[:-1] + str(digit) for digit in range(6)]
    errors: list[BaseException] = []

    def cycle(sid: str) -> None:
        try:
            grant_package_read(entry, sid, allowed_root=cache)
            revoke_package_read(entry, sid, allowed_root=cache)
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=cycle, args=(sid,)) for sid in sids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    assert peak[0] == 1


@pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")
def test_a_revoke_that_leaves_the_ace_in_place_is_a_failure(
    icacls_recorder, monkeypatch, entry: Path, cache: Path,
) -> None:
    """WR-03: the DACL is re-read after the revoke; a surviving ACE is never reported clean."""

    monkeypatch.setattr("backend.app.execution.acl.dacl_sddl",
                        lambda path: f"D:(A;OICI;0x1200a9;;;{PACKAGE_SID})")
    with pytest.raises(AppError) as raised:
        revoke_package_read(entry, PACKAGE_SID, allowed_root=cache)
    assert raised.value.code == "CHECK_RUNTIME_GRANT_FAILED"
    # A different SID that merely starts with the same digits is not a match.
    monkeypatch.setattr("backend.app.execution.acl.dacl_sddl",
                        lambda path: f"D:(A;OICI;0x1200a9;;;{PACKAGE_SID}1)")
    revoke_package_read(entry, PACKAGE_SID, allowed_root=cache)


@pytest.mark.parametrize("sid", [
    "S-1-5-18",                                          # SYSTEM
    "S-1-15-2-1",                                        # ALL APPLICATION PACKAGES
    "S-1-15-3-1",                                        # a capability SID
    "S-1-5-21-1-2-3-1001",                               # a user
    PACKAGE_SID + ":(F)",                                # injection into the icacls ACE text
    "*" + PACKAGE_SID,
])
@pytest.mark.parametrize("operation", [grant_package_read, revoke_package_read])
def test_non_package_sids_are_refused(icacls_recorder, entry, cache, sid, operation) -> None:
    with pytest.raises(AppError) as raised:
        operation(entry, sid, allowed_root=cache)
    assert raised.value.code == "CHECK_RUNTIME_GRANT_REFUSED"
    assert icacls_recorder.calls == []


@pytest.mark.parametrize("operation", [grant_package_read, revoke_package_read])
def test_paths_outside_the_allowed_root_are_refused(
    icacls_recorder, cache: Path, tmp_path: Path, operation,
) -> None:
    cache.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    for path in (outside, cache, cache / ".." / "outside", tmp_path):
        with pytest.raises(AppError) as raised:
            operation(path, PACKAGE_SID, allowed_root=cache)
        assert raised.value.code == "CHECK_RUNTIME_GRANT_REFUSED"
    assert icacls_recorder.calls == []


def test_missing_and_file_targets_are_refused(icacls_recorder, entry: Path, cache: Path) -> None:
    for path in (cache / "python" / "missing", entry / "python.exe"):
        with pytest.raises(AppError) as raised:
            grant_package_read(path, PACKAGE_SID, allowed_root=cache)
        assert raised.value.code == "CHECK_RUNTIME_GRANT_REFUSED"
    assert icacls_recorder.calls == []


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
@pytest.mark.parametrize("where", ["target", "parent"])
def test_reparse_points_are_refused(icacls_recorder, cache: Path, tmp_path: Path, where) -> None:
    import _winapi

    outside = tmp_path / "outside"
    (outside / "inner").mkdir(parents=True)
    cache.mkdir()
    if where == "target":
        _winapi.CreateJunction(str(outside), str(cache / "link"))
        path = cache / "link"
    else:
        _winapi.CreateJunction(str(outside), str(cache / "python"))
        path = cache / "python" / "inner"
    with pytest.raises(AppError) as raised:
        grant_package_read(path, PACKAGE_SID, allowed_root=cache)
    assert raised.value.code == "CHECK_RUNTIME_GRANT_REFUSED"
    assert icacls_recorder.calls == []


def test_default_allowed_root_is_the_check_runtime_cache(
    icacls_recorder, tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = check_runtime_root(create=False)
    target = root / "node" / ("b" * 64)
    target.mkdir(parents=True)
    grant_package_read(target, PACKAGE_SID)
    assert len(icacls_recorder.calls) == 1
    with pytest.raises(AppError):
        grant_package_read(tmp_path, PACKAGE_SID)


def test_icacls_failure_is_loud(monkeypatch, entry: Path, cache: Path) -> None:
    monkeypatch.setattr("backend.app.execution.acl.subprocess.run", _Recorder(returncode=5))
    monkeypatch.setattr("backend.app.execution.acl.icacls_executable", lambda: FAKE_ICACLS)
    with pytest.raises(AppError) as raised:
        grant_package_read(entry, PACKAGE_SID, allowed_root=cache)
    assert raised.value.code == "CHECK_RUNTIME_GRANT_FAILED"


_ACE = re.compile(r"\([^()]*\)")


def _dacl_aces(path: Path) -> list[str]:
    from backend.tests.workspace.conftest import security_sddl

    sddl = security_sddl(path)
    dacl = sddl.split("D:", 1)[1].split("S:", 1)[0]
    return _ACE.findall(dacl)


def _explicit(aces: list[str]) -> list[str]:
    """ACEs set on the object itself (no ``ID`` flag), as opposed to inherited ones."""

    return [ace for ace in aces if "ID" not in ace.split(";")[1]]


@pytest.mark.skipif(os.name != "nt", reason="icacls only runs on Windows")
def test_real_grant_and_revoke_are_exact_inverses(entry: Path, cache: Path) -> None:
    """The grant adds exactly one ACE for the package SID and the revoke removes exactly it.

    The comparison is per ACE, not a raw count. When icacls rewrites a DACL,
    Windows re-propagates the parent's inheritable ACEs in canonical form; on
    hosted runners that re-propagation shows up as SY/BA/OW ``OICIID`` ACEs that
    were not textually present before (CI run 36831151656). Those are the
    parent's ACEs, not something the grant added, so they are compared as
    inherited ACEs: none of them may name the package SID, and the explicit
    ACEs must be exactly the original ones plus (then minus) the single grant.
    """

    from backend.app.execution.appcontainer import derive_package_sid

    sid = derive_package_sid("sentinel.test." + uuid4().hex)  # derivation only; no profile
    child = entry / "python.exe"
    before_dir, before_child = _dacl_aces(entry), _dacl_aces(child)
    assert not any(sid in ace for ace in before_dir + before_child)
    expected_grant = f"(A;OICI;0x1200a9;;;{sid})"

    grant_package_read(entry, sid, allowed_root=cache)
    granted = _dacl_aces(entry)
    context = f"before={before_dir} granted={granted}"
    # Exactly one ACE names the package SID: explicit, inheritable, read+execute only.
    assert [ace for ace in granted if sid in ace] == [expected_grant], context
    assert sorted(_explicit(granted)) == sorted(_explicit(before_dir) + [expected_grant]), context
    # Child files inherit exactly that ACE and nothing else for the SID.
    granted_child = _dacl_aces(child)
    assert [ace for ace in granted_child if sid in ace] == [f"(A;ID;0x1200a9;;;{sid})"], granted_child
    assert _explicit(granted_child) == _explicit(before_child), granted_child

    revoke_package_read(entry, sid, allowed_root=cache)
    revoked, revoked_child = _dacl_aces(entry), _dacl_aces(child)
    context = f"before={before_dir} granted={granted} revoked={revoked}"
    # The revoke removes exactly the granted ACE and nothing else ...
    assert revoked == [ace for ace in granted if ace != expected_grant], context
    assert not any(sid in ace for ace in revoked + revoked_child), context
    # ... so the explicit ACL is the original one, and every inherited ACE is the parent's.
    assert sorted(_explicit(revoked)) == sorted(_explicit(before_dir)), context
    assert _explicit(revoked_child) == _explicit(before_child), revoked_child
    # Where Windows did not need to re-canonicalize inheritance (e.g. this
    # developer machine), the original DACL comes back byte-for-byte.
    if sorted(before_dir) == sorted(ace for ace in granted if ace != expected_grant):
        assert revoked == before_dir and revoked_child == before_child

    # A second cycle on the now-canonical DACL is an exact inverse everywhere.
    grant_package_read(entry, sid, allowed_root=cache)
    revoke_package_read(entry, sid, allowed_root=cache)
    assert _dacl_aces(entry) == revoked
    assert _dacl_aces(child) == revoked_child
