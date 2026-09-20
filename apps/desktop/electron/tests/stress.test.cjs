"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createApiProxy } = require("../api-proxy.cjs");
const { resolveAsset } = require("../app-protocol.cjs");
const { createBackendRuntime } = require("../backend-runtime.cjs");

// Small deterministic PRNG so failures are reproducible.
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 2 ** 32);
}

const ALPHABET = ["a", "Z", "0", "/", "/", ".", ".", "..", "%2e", "%2f", "%5c", "\\", "?", "#", " ", "\0", "\n", "%00", "é", "☃", "api", "v1", "@", ":", "="];
const randomString = (r, max = 24) => Array.from({ length: Math.floor(r() * max) }, () => ALPHABET[Math.floor(r() * ALPHABET.length)]).join("");

test("fuzz: no random path other than a plain /api/v1 path ever reaches the network", async () => {
  const r = rng(42);
  const reached = [];
  const proxy = createApiProxy({
    getBaseUrl: () => "http://127.0.0.1:8000",
    getToken: () => "tok",
    fetchImpl: async (url) => (reached.push(url), { status: 200, text: async () => "{}" }),
  });
  for (let i = 0; i < 4000; i++) {
    const path = r() < 0.4 ? `/api/v1/${randomString(r)}` : randomString(r, 40);
    await proxy({ method: "GET", path }).catch(() => {});
  }
  assert.ok(reached.length > 0, "some valid-looking paths should get through");
  for (const url of reached) {
    const p = url.slice("http://127.0.0.1:8000".length);
    assert.ok(p.startsWith("/api/v1/"), p);
    assert.ok(!p.includes(".."), p);
    assert.ok(!p.includes("//"), p);
    assert.ok(new URL(url).origin === "http://127.0.0.1:8000", url);
  }
});

test("fuzz: random and hostile asset URLs never resolve outside the renderer root", () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "ca-fuzz-"));
  const root = path.join(base, "dist");
  fs.mkdirSync(path.join(root, "assets"), { recursive: true });
  fs.writeFileSync(path.join(root, "index.html"), "x");
  fs.writeFileSync(path.join(root, "assets", "a.js"), "x");
  fs.writeFileSync(path.join(base, "secret.txt"), "SECRET");
  const r = rng(7);
  const rootReal = fs.realpathSync(root);
  let served = 0;
  for (let i = 0; i < 6000; i++) {
    const result = resolveAsset(root, `app://app/${randomString(r, 30)}`);
    if (result.status === 200) {
      served += 1;
      const real = fs.realpathSync(result.filePath);
      assert.ok(real.startsWith(rootReal + path.sep), `${result.filePath} escaped the root`);
    }
  }
  assert.ok(served > 0);
  fs.rmSync(base, { recursive: true, force: true });
});

test("200 concurrent requests are all answered with the token, none leak it, and none interfere", async () => {
  let inFlight = 0;
  let peak = 0;
  const proxy = createApiProxy({
    getBaseUrl: () => "http://127.0.0.1:8000",
    getToken: () => "concurrent-token",
    fetchImpl: async (url, init) => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, Math.random() * 15));
      inFlight -= 1;
      assert.equal(init.headers.Authorization, "Bearer concurrent-token");
      return { status: 200, text: async () => JSON.stringify({ url: url.slice(-3) }) };
    },
  });
  const results = await Promise.all(Array.from({ length: 200 }, (_, i) => proxy({ method: "GET", path: `/api/v1/changes/${String(i).padStart(3, "0")}` })));
  results.forEach((result, i) => {
    assert.equal(result.body.url, String(i).padStart(3, "0"));
    assert.ok(!JSON.stringify(result).includes("concurrent-token"));
  });
  assert.ok(peak > 20, "requests should overlap");
});

test("a slow or failing backend never wedges later requests", async () => {
  let n = 0;
  const proxy = createApiProxy({
    getBaseUrl: () => "http://127.0.0.1:8000",
    getToken: () => "t",
    fetchImpl: async (_url, init) => {
      n += 1;
      if (n % 3 === 0) throw new Error("ECONNRESET");
      if (n % 3 === 1) await new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(Object.assign(new Error("t"), { name: "TimeoutError" }))));
      return { status: 200, text: async () => "{}" };
    },
  });
  const outcomes = await Promise.all(Array.from({ length: 30 }, () => proxy({ method: "GET", path: "/api/v1/x", timeoutMs: 20 }).then((r) => r.status, (e) => e.code)));
  assert.deepEqual([...new Set(outcomes)].sort(), [200, "backend_timeout", "backend_unreachable"].map(String).sort().map((v) => (v === "200" ? 200 : v)).sort());
  assert.equal((await proxy({ method: "GET", path: "/api/v1/ok", timeoutMs: 500 }).catch((e) => e.code)) !== undefined, true);
});

function fakeChild(pid) {
  const child = new EventEmitter();
  child.pid = pid;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.alive = true;
  child.kill = () => {
    setImmediate(() => {
      child.alive = false;
      child.emit("exit", null, "SIGTERM");
    });
    return true;
  };
  return child;
}

test("60 rapid restart cycles never leave a running child or wrong state", async () => {
  const children = [];
  let pid = 1000;
  const runtime = createBackendRuntime({
    mode: "managed",
    command: "python",
    args: ["-m", "uvicorn", "backend.app.main:app"],
    cwd: "C:\\repo",
    dataDir: "C:\\data",
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ service_name: "change-assurance-runtime-backend" }) }),
    findFreePort: async () => 50000 + children.length,
    makeToken: () => `tok-${children.length}`,
    spawnImpl: () => {
      const c = fakeChild(pid++);
      children.push(c);
      return c;
    },
    startupTimeoutMs: 500,
    pollMs: 1,
    stopTimeoutMs: 100,
  });
  await runtime.start();
  for (let i = 0; i < 60; i++) {
    await runtime.restart();
    assert.equal(runtime.getStatus().state, "ready", `cycle ${i}`);
    assert.equal(children.filter((c) => c.alive).length, 1, `exactly one live child after cycle ${i}`);
  }
  await runtime.stop();
  assert.equal(children.filter((c) => c.alive).length, 0);
  assert.equal(runtime.getStatus().state, "idle");
});

test("concurrent start() calls spawn one backend, and stop() during startup wins", async () => {
  const children = [];
  const runtime = createBackendRuntime({
    mode: "managed",
    command: "python",
    args: [],
    cwd: "C:\\repo",
    dataDir: "C:\\data",
    fetchImpl: async () => {
      await new Promise((r) => setTimeout(r, 20));
      return { ok: true };
    },
    findFreePort: async () => 51000,
    makeToken: () => "t",
    spawnImpl: () => {
      const c = fakeChild(2000 + children.length);
      children.push(c);
      return c;
    },
    startupTimeoutMs: 1000,
    pollMs: 2,
    stopTimeoutMs: 50,
  });
  await Promise.all([runtime.start(), runtime.start(), runtime.start(), runtime.start()]);
  assert.equal(children.length, 1);
  await runtime.stop();
  assert.equal(children.filter((c) => c.alive).length, 0);
});
