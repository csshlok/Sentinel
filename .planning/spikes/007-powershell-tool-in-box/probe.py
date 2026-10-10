r"""Spike 007: real Claude Code renames/deletes through its PowerShell tool inside the AppContainer.

Git Bash (MSYS2) cannot initialise in the box (0xC0000142, spike 004 / 01-04). Windows PowerShell
5.1 starts, but it normalizes the location by listing every ancestor directory, which the box may
not list, so it lands at C:\. The container folder (AC) is therefore exposed as a per-run DOS drive
(DefineDosDeviceW) and the workspace is Q:\ws: its only ancestor is the AC folder, which the box may
list. At the drive root itself, Claude Code's PowerShell guard refuses Remove-Item on Q:\<file> as a
protected system path. The user's Claude login is copied into the
staged home for this one run and deleted afterwards (user request, 2026-10-08).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a0_lib"))
import acbox  # noqa: E402

PROFILE = "sentinel.a0.spike007"
GIT = r"C:\Program Files\Git\cmd\git.exe"
SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")
REAL_CLAUDE = Path(os.environ["USERPROFILE"]) / ".local" / "bin" / "claude.exe"
REAL_CREDS = Path(os.environ["USERPROFILE"]) / ".claude" / ".credentials.json"
DO_EDIT = "--no-edit" not in sys.argv
DRIVE = "Q:"
import ctypes  # noqa: E402
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def host_git(*args: str) -> str:
    done = subprocess.run([GIT, *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout.strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


sid, _ = acbox.ensure_profile(PROFILE, ("internetClient",))
ac = Path(acbox.container_folder(sid))
tools, home, temp = ac / "tools", ac / "home", ac / "Temp"
for d in (tools, home / ".claude", home / "AppData" / "Roaming", temp):
    d.mkdir(parents=True, exist_ok=True)

# Tool snapshot (content-addressed evidence).
snapshot = tools / "claude.exe"
if not snapshot.exists() or snapshot.stat().st_size != REAL_CLAUDE.stat().st_size:
    shutil.copy2(REAL_CLAUDE, snapshot)
results: dict[str, object] = {"snapshot_sha256": sha256(snapshot), "source_sha256": sha256(REAL_CLAUDE)}

# Disposable user repo + S3 workspace clone.
scratch = Path(tempfile.mkdtemp(prefix="a0-spike007-"))
user_repo = scratch / "user-repo"
user_repo.mkdir()
host_git("init", "-q", "-b", "main", str(user_repo))
(user_repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
(user_repo / "old.txt").write_text("remove me\n", encoding="utf-8")
(user_repo / "sub").mkdir()
(user_repo / "sub" / "gone.txt").write_text("remove me too\n", encoding="utf-8")
host_git("-C", str(user_repo), "add", "-A")
host_git("-C", str(user_repo), "-c", "user.name=a0", "-c", "user.email=a0@x", "commit", "-q", "-m", "init")
workspace = ac / "ws"
if workspace.exists():
    def _onexc(func, target, _exc):
        os.chmod(target, 0o700)
        func(target)
    shutil.rmtree(workspace, onexc=_onexc)
host_git("clone", "-q", "--no-hardlinks", str(user_repo), str(workspace))

env = {
    "SystemRoot": os.environ["SystemRoot"], "windir": os.environ["windir"],
    "PATH": rf"{tools};C:\Program Files\Git\cmd;C:\Program Files\nodejs;{SYSTEM32}",
    "LOCALAPPDATA": os.environ["LOCALAPPDATA"], "TEMP": str(temp), "TMP": str(temp),
    "USERPROFILE": str(home), "HOME": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
    "HOMEDRIVE": str(home)[:2], "HOMEPATH": str(home)[2:],
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
    "CLAUDE_CODE_USE_POWERSHELL_TOOL": "1",
    "PSModulePath": rf"{SYSTEM32}\WindowsPowerShell\v1.0\Modules",
    "DISABLE_AUTOUPDATER": "1",
}

if not _k32.DefineDosDeviceW(0, DRIVE, str(ac)):
    raise OSError(ctypes.get_last_error(), "DefineDosDeviceW")
root = DRIVE + "\\ws"
real_creds_before = sha256(REAL_CREDS)
version = acbox.run(f'"{snapshot}" --version', cwd=root, sid=sid,
                    capabilities=("internetClient",), env=env, timeout=120)
results["version"] = {"exit": version.exit_code, "out": version.output.strip()[:200],
                      "is_appcontainer": version.token["is_appcontainer"]}

staged_creds = home / ".claude" / ".credentials.json"
if DO_EDIT:
    shutil.copy2(REAL_CREDS, staged_creds)
    try:
        prompt = ("Use only the PowerShell tool for every step. In the current directory: "
                  "rename calc.py to calculator.py with Rename-Item, delete old.txt and sub\\gone.txt with Remove-Item, "
                  "and create ps.txt containing exactly ps-in-appcontainer with Set-Content. "
                  "Then run Get-ChildItem -Name and report the output. Do nothing else.")
        edit = acbox.run(
            f'"{snapshot}" -p "{prompt}" --permission-mode acceptEdits --allowedTools "PowerShell"',
            cwd=root, sid=sid, capabilities=("internetClient",), env=env, timeout=300)
        results["edit"] = {"exit": edit.exit_code, "timed_out": edit.timed_out,
                           "out_tail": edit.output.strip()[-800:],
                           "files": sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*")
                                  if ".git" not in p.parts),
                           "ps_txt": (workspace / "ps.txt").read_text(encoding="utf-8").strip()
                           if (workspace / "ps.txt").exists() else None,
                           "git_status": host_git("-C", str(workspace), "status", "--porcelain"),
                           "user_repo_untouched": host_git("-C", str(user_repo), "status", "--porcelain") == ""}
    finally:
        staged_creds.unlink(missing_ok=True)
        results["staged_credentials_removed"] = not staged_creds.exists()
        results["real_credentials_unchanged"] = sha256(REAL_CREDS) == real_creds_before
        _k32.DefineDosDeviceW(2, DRIVE, str(ac))  # DDD_REMOVE_DEFINITION
        results["drive_removed"] = not os.path.exists(DRIVE + "\\")

results["workspace"] = str(workspace)
results["user_repo"] = str(user_repo)
print(json.dumps(results, indent=2))
