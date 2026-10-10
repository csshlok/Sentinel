r"""Spike 006: how can a confined `check` AppContainer run the project's Python tests?

A: base interpreter in place (C:\Python314) -> expected denied.
B: narrow package-SID RX grant on a nested dir under a dir the box cannot read (traversal).
C: interpreter snapshot (stdlib only) inside the container folder + venv site-packages snapshot:
   python runs, imports pytest/coverage, runs a real test under coverage, and cannot read the
   user repo or reach loopback; time/size measured.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a0_lib"))
import acbox  # noqa: E402

PROFILE = "sentinel.a0.spike006"
BASE = Path(sys.base_prefix)                     # C:\Python314
VENV_SITE = Path(sys.prefix) / "Lib" / "site-packages"
SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")
CMD = os.path.join(SYSTEM32, "cmd.exe")
results: dict[str, object] = {}


def env_for(ac: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    (ac / "Temp").mkdir(exist_ok=True)
    env = {"SystemRoot": os.environ["SystemRoot"], "windir": os.environ["windir"],
           "PATH": SYSTEM32, "TEMP": str(ac / "Temp"), "TMP": str(ac / "Temp"),
           "HOME": str(ac), "USERPROFILE": str(ac), "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    env.update(extra or {})
    return env


def box(cmdline: str, cwd: str, ac: Path, sid, extra=None, timeout=180.0):
    r = acbox.run(cmdline, cwd=cwd, sid=sid, env=env_for(ac, extra), timeout=timeout)
    return {"exit": r.exit_code, "out": r.output[-1500:], "appcontainer": r.token.get("is_appcontainer")}


def size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main() -> int:
    sid, _ = acbox.ensure_profile(PROFILE)
    sid_text = acbox.sid_to_string(sid)
    ac = Path(acbox.container_folder(sid))
    work = Path(tempfile.mkdtemp(prefix="spike006-"))
    try:
        # A: base interpreter in place
        results["A_base_in_place"] = box(f'"{BASE / "python.exe"}" -c "print(42)"', str(ac), ac, sid)

        # B: traversal through an unreadable parent to a narrowly granted child
        outer = work / "outer"; inner = outer / "a" / "b"; inner.mkdir(parents=True)
        (inner / "x.txt").write_text("granted-child\n")
        subprocess.run(["icacls", str(outer), "/inheritance:r", "/grant:r",
                        f"{os.environ['USERNAME']}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                       capture_output=True, check=True)
        subprocess.run(["icacls", str(inner), "/grant", f"*{sid_text}:(OI)(CI)(RX)"],
                       capture_output=True, check=True)
        results["B_traverse_to_granted_child"] = box(f'"{CMD}" /c type "{inner / "x.txt"}"', str(ac), ac, sid)
        results["B_parent_listing"] = box(f'"{CMD}" /c dir "{outer}"', str(ac), ac, sid)

        # C: snapshot interpreter (no base site-packages) + venv site-packages into the container folder
        tools = ac / "tools"
        if tools.exists():
            shutil.rmtree(tools)
        t0 = time.monotonic()
        snap = tools / "python"
        shutil.copytree(BASE, snap, ignore=shutil.ignore_patterns("site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "Doc", "Tools", "include", "libs"))
        shutil.copytree(VENV_SITE, tools / "site-packages", ignore=shutil.ignore_patterns("__pycache__"))
        results["C_snapshot_seconds"] = round(time.monotonic() - t0, 1)
        results["C_snapshot_mb"] = {"interpreter": size(snap) // 2**20, "site_packages": size(tools / "site-packages") // 2**20}
        project = ac / "check-ws"
        if project.exists():
            shutil.rmtree(project)
        (project / "tests").mkdir(parents=True)
        (project / "calc.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
        (project / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
        (project / "conftest.py").write_text(
            "import os, socket, pathlib\n"
            f"REPO = r'{Path.cwd()}'\n"
            "def _try(name, fn):\n"
            "    try:\n        fn(); print('ESCAPE', name, 'ok')\n"
            "    except Exception as e:\n        print('ESCAPE', name, 'denied', type(e).__name__)\n"
            "_try('read_user_repo', lambda: pathlib.Path(REPO, 'pyproject.toml').read_text())\n"
            "_try('write_user_profile', lambda: pathlib.Path('C:/Users', 'pwn.txt').write_text('x'))\n"
            "_try('loopback', lambda: socket.create_connection(('127.0.0.1', 8000), timeout=2))\n"
            "_try('internet', lambda: socket.create_connection(('1.1.1.1', 443), timeout=3))\n"
        )
        py = snap / "python.exe"
        pyenv = {"PYTHONPATH": str(tools / "site-packages"), "PYTHONHOME": str(snap)}
        results["C_python_runs"] = box(f'"{py}" -c "import sys; print(sys.version)"', str(project), ac, sid, pyenv)
        results["C_imports"] = box(f'"{py}" -c "import pytest, coverage; print(pytest.__version__, coverage.__version__)"', str(project), ac, sid, pyenv)
        t1 = time.monotonic()
        results["C_pytest_under_coverage"] = box(
            f'"{py}" -X pycache_prefix={ac / "Temp" / "pyc"} -m coverage run --data-file={ac / "Temp" / ".coverage"} -m pytest -q -p no:cacheprovider -s tests',
            str(project), ac, sid, pyenv, timeout=300)
        results["C_pytest_seconds"] = round(time.monotonic() - t1, 1)
        results["C_coverage_json"] = box(
            f'"{py}" -m coverage json --data-file={ac / "Temp" / ".coverage"} -o {ac / "Temp" / "cov.json"}',
            str(project), ac, sid, pyenv)
        cov = ac / "Temp" / "cov.json"
        results["C_coverage_files"] = sorted(f for f in json.loads(cov.read_text())["files"] if "site-packages" not in f) if cov.exists() else None
    finally:
        print(json.dumps(results, indent=1, default=str))
        shutil.rmtree(work, ignore_errors=True)
        acbox.delete_profile(PROFILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
