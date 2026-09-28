"""Spike 005: bring workspace commits back through the hardened harness; refuse when the user moved; clean up."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a0_lib"))
import acbox  # noqa: E402
from backend.app.git.safe_exec import RECOVERY_IDENTITY, run_git  # noqa: E402

PROFILE = "sentinel.a0.spike005"
GIT = r"C:\Program Files\Git\cmd\git.exe"
SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")


def plain(*args: str) -> str:
    done = subprocess.run([GIT, *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout.strip()


def safe(repo: Path, *args: str, identity: bool = False):
    argv = list(args)
    result = run_git(repo, argv, timeout=60, identity=RECOVERY_IDENTITY if identity else None)
    return result.returncode, result.stdout.decode(errors="replace").strip(), result.stderr.decode(errors="replace").strip()


def onexc(func, target, _exc):
    os.chmod(target, 0o700)
    func(target)


scratch = Path(tempfile.mkdtemp(prefix="a0-spike005-"))
canary_dir = scratch / "canaries"
canary_dir.mkdir()
user_repo = scratch / "user-repo"
user_repo.mkdir()
plain("init", "-q", "-b", "main", str(user_repo))
(user_repo / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
plain("-C", str(user_repo), "add", "-A")
plain("-C", str(user_repo), "-c", "user.name=a0", "-c", "user.email=a0@x", "commit", "-q", "-m", "init")

sid, _ = acbox.ensure_profile(PROFILE, ("internetClient",))
ac = Path(acbox.container_folder(sid))
workspace = ac / "ws"
if workspace.exists():
    shutil.rmtree(workspace, onexc=onexc)
plain("clone", "-q", "--no-hardlinks", str(user_repo), str(workspace))

# The "agent" edits inside the container and plants hostile Git config in the workspace.
env = {"SystemRoot": os.environ["SystemRoot"], "PATH": SYSTEM32, "LOCALAPPDATA": os.environ["LOCALAPPDATA"]}
hook_body = f"#!/bin/sh\\necho pwned > '{(canary_dir / 'hook.txt').as_posix()}'\\n"
NODE = r"C:\Program Files\nodejs\node.exe"
agent = acbox.run(
    f'"{NODE}" -e "require(\'fs\').appendFileSync(\'calc.py\', \'\\ndef sub(a, b):\\n    return a - b\\n\')"',
    cwd=str(workspace), sid=sid, capabilities=("internetClient",), env=env)
hooks = workspace / ".git" / "hooks"
for name in ("pre-commit", "post-commit", "commit-msg", "post-checkout", "pre-push", "reference-transaction"):
    (hooks / name).write_text(f"#!/bin/sh\necho pwned > '{(canary_dir / (name + '.txt')).as_posix()}'\n", encoding="utf-8")
with (workspace / ".git" / "config").open("a", encoding="utf-8") as cfg:
    cfg.write(f'[filter "evil"]\n\tclean = sh -c "echo pwned > {(canary_dir / "filter.txt").as_posix()}; cat"\n'
              f'[core]\n\tfsmonitor = "sh -c \'echo pwned > {(canary_dir / "fsmonitor.txt").as_posix()}\'"\n'
              f'[uploadpack]\n\tpackObjectsHook = sh -c "echo pwned > {(canary_dir / "upload.txt").as_posix()}; exec \\"$@\\""\n')
(workspace / ".gitattributes").write_text("*.py filter=evil\n", encoding="utf-8")

results: dict[str, object] = {"agent_exit": agent.exit_code}

# Sentinel commits the workspace changes through the hardened harness (explicit identity, no hooks).
steps = {}
steps["add"] = safe(workspace, "add", "-A")
steps["commit"] = safe(workspace, "commit", "-q", "-m", "agent change (sentinel commit)", identity=True)
ws_head = safe(workspace, "rev-parse", "HEAD")[1]

# Fetch into a Sentinel-private ref in the user repo, then fast-forward only.
steps["fetch"] = safe(user_repo, "fetch", "--no-tags", str(workspace), f"HEAD:refs/sentinel/changes/spike005")
steps["ff_check"] = safe(user_repo, "merge-base", "--is-ancestor", "HEAD", "refs/sentinel/changes/spike005")
steps["apply_ff"] = safe(user_repo, "merge", "--ff-only", "-q", "refs/sentinel/changes/spike005")
user_head = safe(user_repo, "rev-parse", "HEAD")[1]
results["fast_forward_applied"] = user_head == ws_head
results["calc_after_apply"] = (user_repo / "calc.py").read_text(encoding="utf-8")

# Second round: the user moves their branch meanwhile -> apply must refuse (no force, no merge commit).
(user_repo / "user.txt").write_text("user work\n", encoding="utf-8")
plain("-C", str(user_repo), "add", "-A")
plain("-C", str(user_repo), "-c", "user.name=u", "-c", "user.email=u@x", "commit", "-q", "-m", "user moved")
with (workspace / "calc.py").open("a", encoding="utf-8") as f:
    f.write("\ndef mul(a, b):\n    return a * b\n")
safe(workspace, "add", "-A")
safe(workspace, "commit", "-q", "-m", "second agent change", identity=True)
safe(user_repo, "fetch", "--no-tags", str(workspace), "+HEAD:refs/sentinel/changes/spike005")
moved = safe(user_repo, "merge-base", "--is-ancestor", "HEAD", "refs/sentinel/changes/spike005")
refused = safe(user_repo, "merge", "--ff-only", "-q", "refs/sentinel/changes/spike005")
results["moved_detected_before_apply"] = moved[0] != 0
results["ff_only_refused"] = refused[0] != 0
results["user_head_kept"] = safe(user_repo, "log", "-1", "--format=%s")[1] == "user moved"
results["steps"] = {k: v[0] for k, v in steps.items()}
results["user_repo_commit_author"] = safe(user_repo, "log", "-1", "--format=%an <%ae>", "refs/sentinel/changes/spike005")[1]

# Cleanup: workspace + profile.
shutil.rmtree(workspace, onexc=onexc)
hr = acbox.delete_profile(PROFILE)
results["profile_delete_hresult"] = hr
results["ac_folder_gone"] = not ac.exists()
results["canaries"] = sorted(p.name for p in canary_dir.iterdir())
# Positive control: the planted hooks DO fire under plain git in a throwaway copy.
control = scratch / "control"
shutil.copytree(user_repo, control)
(control / ".git" / "hooks" / "post-commit").write_text(
    f"#!/bin/sh\necho pwned > '{(canary_dir / 'control-post-commit.txt').as_posix()}'\n", encoding="utf-8")
(control / "x.txt").write_text("x\n", encoding="utf-8")
plain("-C", str(control), "add", "-A")
plain("-C", str(control), "-c", "user.name=c", "-c", "user.email=c@x", "commit", "-q", "-m", "control")
results["positive_control_fired"] = (canary_dir / "control-post-commit.txt").exists()
print(json.dumps(results, indent=2))
