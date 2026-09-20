"use strict";

const net = require("node:net");
const path = require("node:path");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");

/**
 * Backend lifecycle for the desktop app.
 *
 * - "external": the backend is started separately (default in development). We only probe it; we never stop it.
 * - "managed": we start our own child on a free loopback port with an isolated data directory and a
 *   per-session token, and stop exactly that child on exit. This is not the product's removed process
 *   supervisor; it never observes or controls anything an agent spawns.
 *
 * The token lives only inside this closure. `getStatus()` is safe to hand to the renderer.
 */
function createBackendRuntime(options) {
  const {
    mode,
    externalUrl = "http://127.0.0.1:8000",
    readExternalToken = () => "",
    command,
    args = [],
    cwd,
    dataDir,
    fetchImpl = fetch,
    spawnImpl = spawn,
    findFreePort = defaultFindFreePort,
    makeToken = () => crypto.randomBytes(32).toString("base64url"),
    log = () => {},
    // Optional collaborators for crash recovery. Without them the runtime behaves exactly as before.
    descriptor = null,
    describeProcess = () => null,
    killTree = null,
    startupTimeoutMs = 30_000,
    pollMs = 250,
    stopTimeoutMs = 5_000,
  } = options;

  let state = "idle";
  let detail = null;
  let url = mode === "external" ? externalUrl : "";
  let token = "";
  let child = null;

  const setState = (next, message = null) => {
    state = next;
    detail = message;
  };

  const redact = (text) => (token ? String(text).split(token).join("[redacted]") : String(text));

  /**
   * Confirms the answering service is this project's backend, so a different program on the port is never treated as ready.
   * A backend older than the identity endpoint answers 404, which is accepted; any other answer must name this service.
   */
  async function isThisBackend(baseUrl, authToken) {
    const res = await fetchImpl(`${baseUrl}/api/v1/system/backend-identity`, {
      headers: { Authorization: `Bearer ${authToken}` },
      signal: AbortSignal.timeout(2_000),
    });
    if (res.status === 404) return true;
    if (!res.ok) return false;
    const body = await res.json();
    return typeof body?.service_name === "string" && body.service_name.startsWith("change-assurance");
  }

  async function probe(baseUrl, authToken) {
    try {
      const health = await fetchImpl(`${baseUrl}/api/v1/health`, { signal: AbortSignal.timeout(2_000) });
      if (!health.ok) return false;
      if (!authToken) return true;
      const authed = await fetchImpl(`${baseUrl}/api/v1/capabilities`, {
        headers: { Authorization: `Bearer ${authToken}` },
        signal: AbortSignal.timeout(2_000),
      });
      if (!authed.ok) return false;
      return await isThisBackend(baseUrl, authToken);
    } catch {
      return false;
    }
  }

  /**
   * If a previous run of this app was killed without cleaning up, its backend may still be alive. Kill it only
   * when the recorded PID is verifiably that backend (same module and port on its command line), never by PID alone.
   */
  function reapStale() {
    const stale = descriptor?.read();
    if (!stale) return;
    const info = describeProcess(stale.pid);
    if (info && info.commandLine.includes("backend.app.main:app") && info.commandLine.includes(stale.marker)) {
      if (killTree) killTree(stale.pid);
      log(`reaped stale backend pid=${stale.pid}`);
    }
    descriptor.clear();
  }

  async function startExternal() {
    setState("starting");
    token = readExternalToken();
    const ok = await probe(url, null);
    if (ok) setState("ready");
    else setState("failed", "No backend answered at the configured address. Start it, then reopen Settings.");
  }

  async function startManaged() {
    if (!command || !cwd || !dataDir) {
      setState("failed", "The bundled backend is not available in this build.");
      return;
    }
    setState("starting");
    reapStale();
    let port;
    try {
      port = await findFreePort();
    } catch {
      setState("failed", "No free local port was available for the backend.");
      return;
    }
    token = makeToken();
    url = `http://127.0.0.1:${port}`;

    let exited = false;
    let spawnError = null;
    try {
      child = spawnImpl(command, [...args, "--host", "127.0.0.1", "--port", String(port)], {
        cwd,
        shell: false,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          CHANGE_ASSURANCE_DB_PATH: path.join(dataDir, "change_assurance.sqlite3"),
          CHANGE_ASSURANCE_API_TOKEN: token,
        },
      });
    } catch (error) {
      setState("failed", `Could not start the backend (${error?.code ?? "spawn error"}).`);
      return;
    }

    const proc = child;
    if (Number.isInteger(proc.pid)) descriptor?.write({ pid: proc.pid, port, marker: `--port ${port}` });
    proc.stdout?.on("data", (chunk) => log(redact(chunk)));
    proc.stderr?.on("data", (chunk) => log(redact(chunk)));
    proc.once("error", (error) => {
      spawnError = error;
    });
    proc.once("exit", (code, signal) => {
      exited = true;
      if (child === proc) child = null;
      descriptor?.clear();
      if (state === "stopping") setState("idle");
      else if (state === "starting") setState("failed", `The backend exited during startup (${signal ?? `code ${code}`}).`);
      else setState("exited", `The backend exited unexpectedly (${signal ?? `code ${code}`}).`);
    });

    const deadline = Date.now() + startupTimeoutMs;
    while (Date.now() < deadline) {
      if (spawnError) {
        setState("failed", `Could not start the backend (${spawnError.code ?? "spawn error"}).`);
        return;
      }
      if (exited) return; // state already set by the exit handler
      if (await probe(url, token)) {
        if (state === "starting") setState("ready");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, pollMs));
    }
    setState("failed", "The backend did not become ready in time.");
    await stop();
    setState("failed", "The backend did not become ready in time.");
  }

  async function start() {
    if (state === "starting" || state === "ready") return;
    if (mode === "managed") await startManaged();
    else await startExternal();
  }

  /** Managed: stop our child and start a fresh one. External: probe again. Used by the repair action. */
  async function restart() {
    await stop();
    setState("idle");
    await start();
  }

  /** Stop only the child this instance started. External backends are never touched. */
  async function stop() {
    const proc = child;
    if (!proc || mode !== "managed") return;
    const previous = state;
    if (previous !== "failed") setState("stopping");
    await new Promise((resolve) => {
      let done = false;
      const finish = () => {
        if (!done) {
          done = true;
          resolve();
        }
      };
      proc.once("exit", finish);
      const timer = setTimeout(() => {
        try {
          if (killTree && Number.isInteger(proc.pid)) killTree(proc.pid);
          else proc.kill("SIGKILL");
        } catch {
          /* already gone */
        }
        setTimeout(finish, 500).unref?.();
      }, stopTimeoutMs);
      timer.unref?.();
      try {
        proc.kill();
      } catch {
        finish();
      }
    });
    child = null;
  }

  return {
    start,
    stop,
    restart,
    getBaseUrl: () => url,
    getToken: () => token,
    getStatus: () => ({ mode, state, url, detail }),
  };
}

function defaultFindFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

module.exports = { createBackendRuntime };
