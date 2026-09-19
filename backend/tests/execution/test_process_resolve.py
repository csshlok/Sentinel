from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

from backend.app.core.errors import AppError
from backend.app.execution import resolve
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.resolve import (
    find_executable, native_command, resolve_argv, safe_path_entries,
)

ENV = minimal_environment()


def run(code, **kw):
    return capture([sys.executable, "-c", code], cwd=os.getcwd(), env=ENV,
                   timeout=kw.pop("timeout", 10), limit=kw.pop("limit", 1000), **kw)


def test_stderr_has_its_own_budget_and_cannot_starve_stdout():
    code = "import sys\nsys.stderr.write('e'*5000)\nsys.stdout.write('o'*200)"
    shared = run(code, limit=100)
    split = run(code, limit=100, stderr_limit=50)
    assert len(split.stdout) == 100 and len(split.stderr) == 50
    assert len(shared.stdout) + len(shared.stderr) <= 100


@pytest.mark.parametrize("bad", [-1, 9 * 1_048_576, 1.5, True])
def test_bad_stderr_limit_rejected(bad):
    with pytest.raises(ValueError):
        run("pass", stderr_limit=bad)


def test_long_timeout_requires_explicit_max():
    with pytest.raises(ValueError):
        run("pass", timeout=301)
    assert run("pass", timeout=301, max_timeout=400).returncode == 0


def test_cancel_and_on_start():
    event, pids = threading.Event(), []
    threading.Timer(0.4, event.set).start()
    start = time.monotonic()
    result = run("import time; time.sleep(30)", timeout=60, max_timeout=60,
                 cancel=event, on_start=pids.append)
    assert result.cancelled and result.returncode is None and result.pid == pids[0]
    assert time.monotonic() - start < 8


def test_cancel_after_completion_is_ignored():
    event = threading.Event()
    event.set()
    result = run("print(1)", cancel=event)
    assert result.returncode in {0, None}


def test_safe_path_entries_skip_relative_and_repository(tmp_path):
    inside = tmp_path / "bin"
    inside.mkdir()
    outside = Path(sys.executable).parent
    env = {"PATH": os.pathsep.join(["relative", "", str(inside), str(outside)])}
    assert safe_path_entries(env, tmp_path.resolve()) == [outside.resolve()]


def test_find_and_resolve_python_and_missing(tmp_path):
    assert find_executable("python", ENV, tmp_path) == Path(sys.executable)
    assert resolve_argv("python3", ENV, tmp_path) == [sys.executable]
    assert find_executable("no-such-tool-zzz", ENV, tmp_path) is None
    with pytest.raises(AppError) as info:
        resolve_argv("no-such-tool-zzz", ENV, tmp_path)
    assert info.value.code == "EXECUTABLE_NOT_FOUND"


def test_repository_executable_never_wins(tmp_path):
    fake = tmp_path / "git.exe"
    fake.write_bytes(b"x")
    env = {"PATH": str(tmp_path)}
    assert find_executable("git", env, tmp_path.resolve()) is None


def _node_layout(tmp_path, with_cli=True):
    node_dir = tmp_path / "nodejs"
    (node_dir / "node_modules" / "npm" / "bin").mkdir(parents=True)
    (node_dir / "node.cmd").write_text("@echo")
    (node_dir / "npm.cmd").write_text("@echo")
    (node_dir / "node.exe").write_bytes(b"MZ")
    if with_cli:
        (node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js").write_text("")
    return node_dir


@pytest.mark.skipif(os.name != "nt", reason="batch shims are a Windows concern")
def test_npm_batch_shim_is_translated_to_node_cli(tmp_path):
    node_dir = _node_layout(tmp_path)
    env = {"PATH": str(node_dir)}
    root = (tmp_path / "repo")
    root.mkdir()
    argv = resolve_argv("npm", env, root)
    assert Path(argv[0]).name.lower().startswith("node") and argv[1].endswith("npm-cli.js")
    assert native_command("npm", ["test"], env, root) == ("node", [argv[1], "test"])
    assert native_command("python", ["-V"], env, root) == ("python", ["-V"])


@pytest.mark.skipif(os.name != "nt", reason="batch shims are a Windows concern")
def test_batch_shim_without_cli_is_rejected(tmp_path):
    node_dir = _node_layout(tmp_path, with_cli=False)
    env = {"PATH": str(node_dir)}
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(AppError) as info:
        resolve_argv("npm", env, root)
    assert info.value.code == "EXECUTABLE_NOT_ALLOWED"
    assert native_command("npm", ["x"], env, root) == ("npm", ["x"])
    other = node_dir / "yarn.cmd"
    other.write_text("@echo")
    with pytest.raises(AppError):
        resolve_argv("yarn", env, root)


def test_native_command_without_shim_or_node(tmp_path, monkeypatch):
    assert native_command("npm", ["a"], {"PATH": ""}, tmp_path) == ("npm", ["a"])
    monkeypatch.setattr(resolve, "_which", lambda name, env, root:
                        Path("C:/x/npm.cmd") if name == "npm" else None)
    assert native_command("npm", ["a"], {}, tmp_path) == ("npm", ["a"])
