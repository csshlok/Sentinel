"""Spike 002: S3 workspace writes inside the AppContainer; everything else denied."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a0_lib"))
import acbox  # noqa: E402

PROFILE = "sentinel.a0.spike002"
GIT = r"C:\Program Files\Git\cmd\git.exe"
SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")
CMD = os.path.join(SYSTEM32, "cmd.exe")


def _force_rmtree(path: Path) -> None:
    def onerror(func, target, _exc):
        os.chmod(target, 0o700)
        func(target)
    shutil.rmtree(path, onexc=onerror)


def host_git(*args: str, cwd: str | None = None) -> str:
    done = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {args} failed: {done.stderr}")
    return done.stdout.strip()


def step(name: str, command: str) -> str:
    # Each probe prints one machine-readable line.
    return f'({command}) >nul 2>&1 && echo RESULT {name} ok || echo RESULT {name} fail'


def parse(output: str) -> dict[str, str]:
    found = {}
    for line in output.splitlines():
        parts = line.strip().split()
        if len(parts) == 3 and parts[0] == "RESULT":
            found[parts[1]] = parts[2]
    return found


sid, _ = acbox.ensure_profile(PROFILE, ("internetClient",))
ac_folder = Path(acbox.container_folder(sid))
scratch = Path(tempfile.mkdtemp(prefix="a0-spike002-"))
user_repo = scratch / "user-repo"
user_repo.mkdir()
host_git("init", "-q", "-b", "main", str(user_repo))
(user_repo / "app.py").write_text("print('v1')\n", encoding="utf-8")
(user_repo / "keep.txt").write_text("keep\n", encoding="utf-8")
host_git("-C", str(user_repo), "add", "-A")
host_git("-C", str(user_repo), "-c", "user.name=a0", "-c", "user.email=a0@x", "commit", "-q", "-m", "init")
t_drive_canary_dir = Path(r"T:\csshl") if Path(r"T:\csshl").exists() else scratch
home_canary = Path(os.environ["USERPROFILE"]) / "a0-spike002-canary.txt"

results: dict[str, object] = {"ac_folder": str(ac_folder), "user_repo": str(user_repo)}
for mode in ("local-hardlinks", "no-hardlinks"):
    workspace = ac_folder / f"ws-{mode}"
    if workspace.exists():
        _force_rmtree(workspace)
    clone_args = ["clone", "-q"] + (["--local"] if mode == "local-hardlinks" else ["--no-hardlinks"])
    host_git(*clone_args, str(user_repo), str(workspace))
    git_env = {
        "SystemRoot": os.environ["SystemRoot"], "windir": os.environ["windir"],
        "PATH": rf"C:\Program Files\Git\cmd;{SYSTEM32}", "TEMP": str(ac_folder / "Temp"),
        "TMP": str(ac_folder / "Temp"), "HOME": str(ac_folder), "USERPROFILE": str(ac_folder),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
    }
    (ac_folder / "Temp").mkdir(exist_ok=True)
    g = f'"{GIT}" -c user.name=agent -c user.email=agent@x -c core.fsmonitor=false'
    script = " & ".join([
        "echo SEEN LOCALAPPDATA=%LOCALAPPDATA% TEMP=%TEMP%",
        step("create", "echo new> new.txt"),
        step("overwrite", "echo print('v2')> app.py"),
        step("rename", "ren keep.txt kept.txt"),
        step("mkdir", "mkdir sub && echo x> sub\\f.txt"),
        step("delete", "del /q new.txt"),
        step("git_status", f"{g} status --porcelain"),
        step("git_add", f"{g} add -A"),
        step("git_commit", f'{g} commit -q -m agent-change'),
        step("git_log", f"{g} log --oneline -1"),
        step("write_user_repo", f'echo pwn> "{user_repo}\\pwn.txt"'),
        step("read_user_repo", f'type "{user_repo}\\app.py"'),
        step("write_home", f'echo pwn> "{home_canary}"'),
        step("write_t_drive", f'echo pwn> "{t_drive_canary_dir}\\a0-spike002-canary.txt"'),
        step("write_sentinel_store_parent", f'echo pwn> "{os.environ["LOCALAPPDATA"]}\\a0-spike002-canary.txt"'),
    ])
    run = acbox.run(f'"{CMD}" /d /c {script}', cwd=str(workspace), sid=sid,
                    capabilities=("internetClient",), env=git_env, timeout=120)
    parsed = parse(run.output)
    head_in_ws = host_git("-C", str(workspace), "log", "--oneline", "-1")
    results[mode] = {
        "token_is_appcontainer": run.token["is_appcontainer"],
        "probes": parsed,
        "workspace_head_after": head_in_ws,
        "user_repo_untouched": not (user_repo / "pwn.txt").exists()
        and host_git("-C", str(user_repo), "status", "--porcelain") == "",
        "seen_env": [l for l in run.output.splitlines() if l.startswith("SEEN")],
        "raw_tail": run.output[-400:],
    }

canaries = [home_canary, t_drive_canary_dir / "a0-spike002-canary.txt",
            Path(os.environ["LOCALAPPDATA"]) / "a0-spike002-canary.txt"]
results["canaries_present"] = [str(p) for p in canaries if p.exists()]
for path in canaries:
    path.unlink(missing_ok=True)
print(json.dumps(results, indent=2))
