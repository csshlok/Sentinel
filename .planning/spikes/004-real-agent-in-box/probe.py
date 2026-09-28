"""Spike 004: a real Claude Code run inside the AppContainer, from a tool snapshot and a staged home.

The user's Claude login (~/.claude/.credentials.json) is copied into the staged home for
this one run and deleted afterwards (user decision, 2026-09-28).
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

PROFILE = "sentinel.a0.spike004"
GIT = r"C:\Program Files\Git\cmd\git.exe"
SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")
REAL_CLAUDE = Path(os.environ["USERPROFILE"]) / ".local" / "bin" / "claude.exe"
REAL_CREDS = Path(os.environ["USERPROFILE"]) / ".claude" / ".credentials.json"
DO_EDIT = "--no-edit" not in sys.argv


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
scratch = Path(tempfile.mkdtemp(prefix="a0-spike004-"))
user_repo = scratch / "user-repo"
user_repo.mkdir()
host_git("init", "-q", "-b", "main", str(user_repo))
(user_repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
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
    "CLAUDE_CODE_GIT_BASH_PATH": r"C:\Program Files\Git\bin\bash.exe",
    "DISABLE_AUTOUPDATER": "1",
}

version = acbox.run(f'"{snapshot}" --version', cwd=str(workspace), sid=sid,
                    capabilities=("internetClient",), env=env, timeout=120)
results["version"] = {"exit": version.exit_code, "out": version.output.strip()[:200],
                      "is_appcontainer": version.token["is_appcontainer"]}

staged_creds = home / ".claude" / ".credentials.json"
if DO_EDIT:
    shutil.copy2(REAL_CREDS, staged_creds)
    try:
        prompt = ("Edit calc.py: add a function sub(a, b) that returns a - b. "
                  "Then create notes.txt containing exactly: edited-in-appcontainer. Do nothing else.")
        edit = acbox.run(
            f'"{snapshot}" -p "{prompt}" --permission-mode acceptEdits --allowedTools "Read Edit Write"',
            cwd=str(workspace), sid=sid, capabilities=("internetClient",), env=env, timeout=300)
        results["edit"] = {"exit": edit.exit_code, "timed_out": edit.timed_out,
                           "out_tail": edit.output.strip()[-800:],
                           "calc_py": (workspace / "calc.py").read_text(encoding="utf-8"),
                           "notes_exists": (workspace / "notes.txt").exists(),
                           "git_status": host_git("-C", str(workspace), "status", "--porcelain"),
                           "user_repo_untouched": host_git("-C", str(user_repo), "status", "--porcelain") == ""}
    finally:
        staged_creds.unlink(missing_ok=True)
        results["staged_credentials_removed"] = not staged_creds.exists()

results["workspace"] = str(workspace)
results["user_repo"] = str(user_repo)
print(json.dumps(results, indent=2))
