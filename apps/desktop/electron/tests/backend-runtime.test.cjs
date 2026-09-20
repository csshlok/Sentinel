"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { createBackendRuntime } = require("../backend-runtime.cjs");

const TOKEN = "managed-session-token";

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.killed = [];
  child.kill = (signal) => {
    child.killed.push(signal ?? "SIGTERM");
    setImmediate(() => child.emit("exit", null, signal ?? "SIGTERM"));
    return true;
  };
  return child;
}

function setup({ healthy = true, authOk = true, fetchThrows = false, identity = { status: 200, service_name: "change-assurance-runtime-backend" }, ...overrides } = {}) {
  const children = [];
  const spawns = [];
  const logs = [];
  const fetchImpl = async (url, init) => {
    if (fetchThrows) throw new Error("ECONNREFUSED");
    if (url.endsWith("/health")) return { ok: healthy };
    if (url.endsWith("/system/backend-identity")) {
      return { ok: identity.status === 200, status: identity.status, json: async () => ({ service_name: identity.service_name }) };
    }
    return { ok: authOk && init?.headers?.Authorization === `Bearer ${TOKEN}` };
  };
  const runtime = createBackendRuntime({
    mode: "managed",
    command: "python",
    args: ["-s", "-m", "uvicorn", "backend.app.main:app"],
    cwd: "C:\\repo",
    dataDir: "C:\\data",
    fetchImpl,
    findFreePort: async () => 51234,
    makeToken: () => TOKEN,
    spawnImpl: (command, args, options) => {
      const child = fakeChild();
      children.push(child);
      spawns.push({ command, args, options });
      return child;
    },
    log: (text) => logs.push(text),
    startupTimeoutMs: 400,
    pollMs: 10,
    stopTimeoutMs: 100,
    ...overrides,
  });
  return { runtime, children, spawns, logs };
}

test("managed start spawns a shell-less loopback child with isolated data and a session token", async () => {
  const { runtime, spawns } = setup();
  await runtime.start();
  assert.equal(runtime.getStatus().state, "ready");
  assert.equal(runtime.getStatus().url, "http://127.0.0.1:51234");
  const [{ command, args, options }] = spawns;
  assert.equal(command, "python");
  assert.deepEqual(args.slice(-4), ["--host", "127.0.0.1", "--port", "51234"]);
  assert.equal(options.shell, false);
  assert.equal(options.windowsHide, true);
  assert.equal(options.env.CHANGE_ASSURANCE_API_TOKEN, TOKEN);
  assert.match(options.env.CHANGE_ASSURANCE_DB_PATH, /^C:\\data[\\/]change_assurance\.sqlite3$/);
  await runtime.stop();
});

test("readiness requires an authenticated response, not just health", async () => {
  const { runtime } = setup({ authOk: false, startupTimeoutMs: 120 });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "failed");
  assert.match(runtime.getStatus().detail, /did not become ready/);
});

test("getStatus and log output never contain the token", async () => {
  const { runtime, children, logs } = setup();
  const starting = runtime.start();
  await new Promise((resolve) => setImmediate(resolve));
  children[0].stdout.emit("data", `listening with ${TOKEN} inside`);
  children[0].stderr.emit("data", `error token=${TOKEN}`);
  await starting;
  assert.ok(!JSON.stringify(runtime.getStatus()).includes(TOKEN));
  assert.ok(logs.length >= 2);
  for (const line of logs) assert.ok(!line.includes(TOKEN), line);
  await runtime.stop();
});

test("early exit during startup is a failure, not a hang", async () => {
  const { runtime, children } = setup({ healthy: false, fetchThrows: true });
  const starting = runtime.start();
  await new Promise((resolve) => setImmediate(resolve));
  children[0].emit("exit", 1, null);
  await starting;
  assert.equal(runtime.getStatus().state, "failed");
  assert.match(runtime.getStatus().detail, /exited during startup/);
});

test("a spawn error is reported as a startup failure", async () => {
  const { runtime, children } = setup({ healthy: false, fetchThrows: true });
  const starting = runtime.start();
  await new Promise((resolve) => setImmediate(resolve));
  children[0].emit("error", Object.assign(new Error("nope"), { code: "ENOENT" }));
  await starting;
  assert.equal(runtime.getStatus().state, "failed");
  assert.match(runtime.getStatus().detail, /ENOENT/);
});

test("a spawn exception is caught", async () => {
  const { runtime } = setup({
    spawnImpl: () => {
      throw Object.assign(new Error("boom"), { code: "EACCES" });
    },
  });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "failed");
});

test("startup timeout fails and kills the child it started", async () => {
  const { runtime, children } = setup({ healthy: false, startupTimeoutMs: 80 });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "failed");
  assert.equal(children[0].killed.length >= 1, true);
});

test("an unexpected exit after ready is surfaced as exited", async () => {
  const { runtime, children } = setup();
  await runtime.start();
  children[0].emit("exit", 3, null);
  assert.equal(runtime.getStatus().state, "exited");
  assert.match(runtime.getStatus().detail, /unexpectedly/);
});

test("stop terminates exactly the owned child and ends idle", async () => {
  const { runtime, children } = setup();
  await runtime.start();
  await runtime.stop();
  assert.equal(children.length, 1);
  assert.deepEqual(children[0].killed, ["SIGTERM"]);
  assert.equal(runtime.getStatus().state, "idle");
  await runtime.stop(); // idempotent
  assert.equal(children[0].killed.length, 1);
});

test("stop escalates when the child ignores the polite signal", async () => {
  const { runtime, children } = setup();
  await runtime.start();
  const child = children[0];
  child.kill = (signal) => {
    child.killed.push(signal ?? "SIGTERM");
    if (signal === "SIGKILL") setImmediate(() => child.emit("exit", null, "SIGKILL"));
    return true;
  };
  await runtime.stop();
  assert.deepEqual(child.killed, ["SIGTERM", "SIGKILL"]);
});

test("missing command or backend directory fails without spawning", async () => {
  const { runtime, spawns } = setup({ command: undefined });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "failed");
  assert.equal(spawns.length, 0);
});

test("external mode probes only: never spawns and never kills", async () => {
  const spawned = [];
  const runtime = createBackendRuntime({
    mode: "external",
    externalUrl: "http://127.0.0.1:8000",
    readExternalToken: () => "dev-token",
    fetchImpl: async () => ({ ok: true }),
    spawnImpl: () => spawned.push(1),
  });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "ready");
  assert.equal(runtime.getStatus().mode, "external");
  assert.equal(runtime.getToken(), "dev-token");
  await runtime.stop();
  assert.equal(spawned.length, 0);
});

test("external mode reports an unreachable backend honestly", async () => {
  const runtime = createBackendRuntime({
    mode: "external",
    fetchImpl: async () => {
      throw new Error("ECONNREFUSED");
    },
  });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "failed");
  assert.match(runtime.getStatus().detail, /No backend answered/);
});

test("restart stops the owned child and starts a fresh one", async () => {
  const { runtime, children, spawns } = setup();
  await runtime.start();
  await runtime.restart();
  assert.equal(spawns.length, 2);
  assert.deepEqual(children[0].killed, ["SIGTERM"]);
  assert.equal(runtime.getStatus().state, "ready");
  await runtime.stop();
});

test("restart in external mode re-probes without spawning or killing", async () => {
  let healthy = false;
  const spawned = [];
  const runtime = createBackendRuntime({
    mode: "external",
    fetchImpl: async () => ({ ok: healthy }),
    spawnImpl: () => spawned.push(1),
  });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "failed");
  healthy = true;
  await runtime.restart();
  assert.equal(runtime.getStatus().state, "ready");
  assert.equal(spawned.length, 0);
});

test("a different service answering on the port is not accepted as the backend", async () => {
  const { runtime } = setup({ identity: { status: 200, service_name: "some-other-service" }, startupTimeoutMs: 120 });
  await runtime.start();
  assert.notEqual(runtime.getStatus().state, "ready");
  await runtime.stop();
});

test("a backend that predates the identity endpoint (404) is still accepted", async () => {
  const { runtime } = setup({ identity: { status: 404, service_name: "" } });
  await runtime.start();
  assert.equal(runtime.getStatus().state, "ready");
  await runtime.stop();
});

test("a backend that names itself correctly becomes ready", async () => {
  const { runtime } = setup();
  await runtime.start();
  assert.equal(runtime.getStatus().state, "ready");
  await runtime.stop();
});
