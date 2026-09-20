// Launches the PACKAGED app (release/win-unpacked) with an isolated profile and checks the real window over the
// debug port: loads via app://, connects to its bundled backend, keeps the security posture, and shuts down cleanly.
// Usage: npm run package:dir && npm run test:electron:smoke
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const exe = resolve(dirname(fileURLToPath(import.meta.url)), "..", "release", "win-unpacked", "Sentinel.exe");
if (!existsSync(exe)) throw new Error("Run `npm run package:dir` first.");
const PORT = 9430;
const profile = mkdtempSync(join(tmpdir(), "ca-smoke-"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const failures = [];
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  " + extra : ""}`);
  if (!ok) failures.push(name);
};

const child = spawn(exe, [`--remote-debugging-port=${PORT}`], { env: { ...process.env, CHANGE_ASSURANCE_USER_DATA_DIR: profile }, stdio: "ignore" });
const exited = new Promise((r) => child.once("exit", r));

async function page() {
  for (let i = 0; i < 60; i++) {
    try {
      const t = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find((x) => x.type === "page");
      if (t) return t;
    } catch {}
    await wait(500);
  }
  throw new Error("Window did not appear.");
}

try {
  const target = await page();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let n = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) pending.get(d.id)(d.result);
  };
  const ev = (expression) =>
    new Promise((res) => {
      const id = ++n;
      pending.set(id, res);
      ws.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression, awaitPromise: true, returnByValue: true } }));
    }).then((r) => r.result?.value);

  let ready = false;
  for (let i = 0; i < 80 && !ready; i++) {
    ready = await ev("document.body.innerText.includes('Connected')");
    if (!ready) await wait(500);
  }
  check("connects to the bundled backend (chip says Connected)", ready);
  check("served from app://", String(await ev("location.href")).startsWith("app://app/"));
  check("no require/process in the renderer", (await ev("typeof require + typeof process")) === "undefinedundefined");
  const bridge = JSON.parse(await ev("JSON.stringify(Object.fromEntries(Object.entries(window.changeAssuranceDesktop).map(([k,v])=>[k,Object.keys(v).sort()])))"));
  check("bridge surface is exactly the expected one", JSON.stringify(Object.fromEntries(Object.entries(bridge).sort(([a], [b]) => a.localeCompare(b)))) === JSON.stringify({
    api: ["request"],
    diagnostics: ["openLogs"],
    exports: ["saveJson"],
    repositories: ["selectFolder"],
    runtime: ["getStatus", "restartBackend"],
    windowControls: ["close", "getState", "minimize", "onStateChanged", "toggleMaximize"],
  }));
  const status = JSON.parse(await ev("window.changeAssuranceDesktop.runtime.getStatus().then(s => JSON.stringify(s))"));
  check("packaged, managed, ready", status.packaged && status.backend.mode === "managed" && status.backend.state === "ready");
  check("token is reported only as a boolean", status.hasToken === true && !JSON.stringify(status).match(/token"?:\s*"/i));
  check("capabilities load through the bridge", (await ev("window.changeAssuranceDesktop.api.request({method:'GET',path:'/api/v1/capabilities'}).then(r=>r.status)")) === 200);
  check("non-API path rejected", (await ev("window.changeAssuranceDesktop.api.request({method:'GET',path:'/etc/passwd'}).then(r=>r.error&&r.error.code)")) === "forbidden_path");
  check("PATCH rejected", (await ev("window.changeAssuranceDesktop.api.request({method:'PATCH',path:'/api/v1/health'}).then(r=>r.error&&r.error.code)")) === "forbidden_method");
  const dom = await ev("document.documentElement.outerHTML + JSON.stringify([localStorage, sessionStorage])");
  check("no token-like secret in DOM or storage", !/Bearer /i.test(dom));

  const backendPort = new URL(status.backend.url).port;
  await new Promise((r) => { ws.send(JSON.stringify({ id: ++n, method: "Browser.close" })); setTimeout(r, 300); });
  await Promise.race([exited, wait(20_000)]);
  check("app exited after a graceful close", child.exitCode !== null);
  await wait(1500);
  const listening = await new Promise((r) => { const s = net.connect(Number(backendPort), "127.0.0.1"); s.once("connect", () => (s.destroy(), r(true))); s.once("error", () => r(false)); });
  check("bundled backend stopped with the app", !listening, `port ${backendPort}`);
} catch (e) {
  check("smoke run", false, e.message);
} finally {
  try { child.kill(); } catch {}
  rmSync(profile, { recursive: true, force: true });
}
if (failures.length) {
  console.error(`\n${failures.length} check(s) failed.`);
  process.exit(1);
}
console.log("\nElectron smoke passed.");
