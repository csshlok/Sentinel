"""Spike 003: what the AppContainer can and cannot reach (credentials, profile, loopback, internet, registry)."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a0_lib"))
import acbox  # noqa: E402

SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")
CMD = os.path.join(SYSTEM32, "cmd.exe")
NODE = r"C:\Program Files\nodejs\node.exe"
CLAUDE_SETTINGS = Path(os.environ["USERPROFILE"]) / ".claude" / "settings.json"
CLAUDE_CREDS = Path(os.environ["USERPROFILE"]) / ".claude" / ".credentials.json"

# Host-side loopback server the container should NOT be able to reach.
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(("127.0.0.1", 0))
server.listen(5)
PORT = server.getsockname()[1]
accepted: list[str] = []


def _serve() -> None:
    server.settimeout(30)
    try:
        while True:
            conn, _ = server.accept()
            accepted.append("connected")
            conn.sendall(b"hello-from-host\n")
            conn.close()
    except OSError:
        pass


threading.Thread(target=_serve, daemon=True).start()

NODE_NET = (
    "const net=require('net'),https=require('https');const r={};let n=2;"
    "const done=()=>{if(--n===0)console.log('NET '+JSON.stringify(r))};"
    f"const s=net.connect({PORT},'127.0.0.1',()=>{{r.loopback='connected';s.destroy();done()}});"
    "s.setTimeout(4000,()=>{r.loopback='timeout';s.destroy();done()});"
    "s.on('error',e=>{r.loopback='error '+e.code;done()});"
    "const q=https.get('https://api.anthropic.com/',res=>{r.internet='http '+res.statusCode;res.resume();done()});"
    "q.setTimeout(8000,()=>{r.internet='timeout';q.destroy()});"
    "q.on('error',e=>{if(!r.internet)r.internet='error '+e.code;done()});"
)


def step(name: str, command: str) -> str:
    return f'({command}) >nul 2>&1 && echo RESULT {name} ok || echo RESULT {name} fail'


def parse(output: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0] == "RESULT":
            found[parts[1]] = parts[2]
        if line.startswith("NET "):
            found["net"] = line[4:].strip()
    return found


results: dict[str, object] = {"loopback_port": PORT}
for label, caps in (("internetClient", ("internetClient",)), ("no_capabilities", ())):
    profile = f"sentinel.a0.spike003.{label}"
    sid, _ = acbox.ensure_profile(profile, caps)
    ac = acbox.container_folder(sid)
    env = {"SystemRoot": os.environ["SystemRoot"], "PATH": SYSTEM32, "LOCALAPPDATA": os.environ["LOCALAPPDATA"],
           "TEMP": ac + r"\Temp", "TMP": ac + r"\Temp"}
    os.makedirs(ac + r"\Temp", exist_ok=True)
    script = " & ".join([
        step("read_claude_settings", f'type "{CLAUDE_SETTINGS}"'),
        step("read_claude_credentials", f'type "{CLAUDE_CREDS}"'),
        step("list_user_profile", f'dir "{os.environ["USERPROFILE"]}"'),
        step("reg_read_hkcu_software", r"reg query HKCU\Software /ve"),
        step("reg_write_hkcu", r"reg add HKCU\Software\SentinelA0Spike /v x /d y /f"),
        step("reg_write_hklm", r"reg add HKLM\Software\SentinelA0Spike /v x /d y /f"),
        'cmdkey /list > cmdkey.txt 2>&1 & type cmdkey.txt',
    ])
    shell = acbox.run(f'"{CMD}" /d /c {script}', cwd=ac, sid=sid, capabilities=caps, env=env, timeout=60)
    net = acbox.run(f'"{NODE}" -e "{NODE_NET}"', cwd=ac, sid=sid, capabilities=caps, env=env, timeout=30)
    parsed = parse(shell.output)
    parsed.update(parse(net.output))
    cmdkey_lines = [line for line in shell.output.splitlines()
                    if line.strip() and not line.startswith("RESULT")]
    results[label] = {"probes": parsed, "cmdkey_output": cmdkey_lines[:6],
                      "token": shell.token, "net_exit": net.exit_code}

# Host control: loopback reachable from a normal process.
control = acbox.run(f'"{NODE}" -e "{NODE_NET}"', cwd=SYSTEM32, sid=None, timeout=30)
results["host_control"] = parse(control.output)
results["loopback_accepts_total"] = len(accepted)
server.close()
print(json.dumps(results, indent=2))
