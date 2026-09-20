"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createBackendRuntime } = require("../backend-runtime.cjs");
const { createDescriptorStore } = require("../runtime-descriptor.cjs");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "ca-desc-"));

test("descriptor round-trips pid, port and marker, and never stores anything else", () => {
  const file = path.join(tmp(), "state", "backend-runtime.json");
  const store = createDescriptorStore(file);
  assert.equal(store.read(), null);
  store.write({ pid: 4242, port: 51000, marker: "--port 51000", token: "must-not-be-kept" });
  assert.deepEqual(store.read(), { pid: 4242, port: 51000, marker: "--port 51000" });
  assert.ok(!fs.readFileSync(file, "utf8").includes("must-not-be-kept"));
  store.clear();
  assert.equal(store.read(), null);
});

test("malformed or partial descriptors are ignored", () => {
  const dir = tmp();
  const file = path.join(dir, "d.json");
  const store = createDescriptorStore(file);
  for (const bad of ["not json", "{}", '{"pid":"x","port":1,"marker":"m"}', '{"pid":-3,"port":1,"marker":"m"}', '{"pid":5,"port":0,"marker":"m"}', '{"pid":5,"port":9}']) {
    fs.writeFileSync(file, bad);
    assert.equal(store.read(), null, bad);
  }
});

test("descriptor writes never throw when the location is unwritable", () => {
  const blocker = path.join(tmp(), "file");
  fs.writeFileSync(blocker, "");
  const store = createDescriptorStore(path.join(blocker, "nested", "d.json"));
  assert.doesNotThrow(() => store.write({ pid: 1, port: 2, marker: "m" }));
  assert.doesNotThrow(() => store.clear());
});

function fakeChild(pid = 7001) {
  const child = new EventEmitter();
  child.pid = pid;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => {
    setImmediate(() => child.emit("exit", null, "SIGTERM"));
    return true;
  };
  return child;
}

function managed({ stale, processes = {}, ...overrides } = {}) {
  const store = { data: stale ?? null, writes: [], cleared: 0 };
  const descriptor = {
    read: () => store.data,
    write: (value) => {
      store.data = value;
      store.writes.push(value);
    },
    clear: () => {
      store.data = null;
      store.cleared += 1;
    },
  };
  const killed = [];
  const runtime = createBackendRuntime({
    mode: "managed",
    command: "python",
    args: ["-s", "-m", "uvicorn", "backend.app.main:app"],
    cwd: "C:\\repo",
    dataDir: "C:\\data",
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ service_name: "change-assurance-runtime-backend" }) }),
    findFreePort: async () => 52000,
    makeToken: () => "tok",
    spawnImpl: () => fakeChild(),
    startupTimeoutMs: 300,
    pollMs: 5,
    stopTimeoutMs: 50,
    descriptor,
    describeProcess: (pid) => (processes[pid] ? { commandLine: processes[pid] } : null),
    killTree: (pid) => killed.push(pid),
    ...overrides,
  });
  return { runtime, store, killed };
}

test("a stale backend from a crashed run is reaped, then the descriptor is replaced", async () => {
  const { runtime, store, killed } = managed({
    stale: { pid: 999, port: 50111, marker: "--port 50111" },
    processes: { 999: "python -s -m uvicorn backend.app.main:app --host 127.0.0.1 --port 50111" },
  });
  await runtime.start();
  assert.deepEqual(killed, [999]);
  assert.deepEqual(store.data, { pid: 7001, port: 52000, marker: "--port 52000" });
  await runtime.stop();
  assert.equal(store.data, null);
});

test("a recycled PID running something else is never killed", async () => {
  const { runtime, killed } = managed({
    stale: { pid: 999, port: 50111, marker: "--port 50111" },
    processes: { 999: '"C:\\Program Files\\SomeOtherApp\\other.exe" --port 50111' },
  });
  await runtime.start();
  assert.deepEqual(killed, []);
  await runtime.stop();
});

test("the right module on a different port is not ours and is left alone", async () => {
  const { runtime, killed } = managed({
    stale: { pid: 999, port: 50111, marker: "--port 50111" },
    processes: { 999: "python -m uvicorn backend.app.main:app --port 9999" },
  });
  await runtime.start();
  assert.deepEqual(killed, []);
  await runtime.stop();
});

test("a descriptor for a process that no longer exists is just cleared", async () => {
  const { runtime, store, killed } = managed({ stale: { pid: 999, port: 50111, marker: "--port 50111" }, processes: {} });
  await runtime.start();
  assert.deepEqual(killed, []);
  assert.equal(store.writes.length, 1); // only the new run's descriptor
  await runtime.stop();
});

test("no descriptor means nothing to reap", async () => {
  const { runtime, killed } = managed();
  await runtime.start();
  assert.deepEqual(killed, []);
  await runtime.stop();
});

test("stopping escalates to a tree kill of the owned child when it will not exit", async () => {
  const child = fakeChild(8123);
  child.kill = () => true; // ignores the polite signal
  const { runtime, killed } = managed({ spawnImpl: () => child });
  await runtime.start();
  const stopping = runtime.stop();
  await new Promise((resolve) => setTimeout(resolve, 120));
  assert.deepEqual(killed, [8123]);
  child.emit("exit", null, "SIGKILL");
  await stopping;
});
