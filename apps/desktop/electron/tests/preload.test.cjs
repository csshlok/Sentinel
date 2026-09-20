"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");

/** Load the real preload against a fake `electron` module and capture what it exposes. */
function loadPreload() {
  const exposed = {};
  const invocations = [];
  const listeners = [];
  const fakeElectron = {
    contextBridge: { exposeInMainWorld: (name, value) => (exposed[name] = value) },
    ipcRenderer: {
      invoke: (...args) => (invocations.push(args), Promise.resolve({ ok: true })),
      on: (channel, listener) => listeners.push({ channel, listener }),
      removeListener: (channel, listener) => {
        const index = listeners.findIndex((l) => l.channel === channel && l.listener === listener);
        if (index >= 0) listeners.splice(index, 1);
      },
    },
  };
  const original = Module._load;
  Module._load = function (request, ...rest) {
    if (request === "electron") return fakeElectron;
    return original.call(this, request, ...rest);
  };
  const file = path.join(__dirname, "..", "preload.cjs");
  delete require.cache[require.resolve(file)];
  try {
    require(file);
  } finally {
    Module._load = original;
  }
  return { exposed, invocations, listeners };
}

test("exposes exactly one namespace with a narrow, frozen surface", () => {
  const { exposed } = loadPreload();
  assert.deepEqual(Object.keys(exposed), ["changeAssuranceDesktop"]);
  const bridge = exposed.changeAssuranceDesktop;
  assert.deepEqual(Object.keys(bridge).sort(), ["api", "diagnostics", "exports", "repositories", "runtime", "windowControls"]);
  assert.deepEqual(Object.keys(bridge.api), ["request"]);
  assert.deepEqual(Object.keys(bridge.runtime).sort(), ["getStatus", "restartBackend"]);
  assert.deepEqual(Object.keys(bridge.repositories), ["selectFolder"]);
  assert.deepEqual(Object.keys(bridge.exports), ["saveJson"]);
  assert.deepEqual(Object.keys(bridge.diagnostics), ["openLogs"]);
  assert.deepEqual(Object.keys(bridge.windowControls).sort(), ["close", "getState", "minimize", "onStateChanged", "toggleMaximize"]);
  for (const value of [bridge, bridge.api, bridge.runtime, bridge.repositories, bridge.exports, bridge.diagnostics, bridge.windowControls]) {
    assert.ok(Object.isFrozen(value));
  }
});

test("does not expose Node, generic IPC, raw electron, or token access", () => {
  const { exposed } = loadPreload();
  const serialized = Object.keys(exposed.changeAssuranceDesktop)
    .flatMap((ns) => Object.keys(exposed.changeAssuranceDesktop[ns]))
    .join(",");
  for (const forbidden of ["invoke", "send", "on", "require", "process", "token", "getToken", "readFile", "exec", "shell", "ipcRenderer"]) {
    assert.ok(!serialized.split(",").includes(forbidden), `${forbidden} must not be exposed`);
  }
  assert.equal(exposed.ipcRenderer, undefined);
  assert.equal(exposed.require, undefined);
});

test("each method maps to exactly one named channel", async () => {
  const { exposed, invocations } = loadPreload();
  const bridge = exposed.changeAssuranceDesktop;
  await bridge.api.request({ method: "GET", path: "/api/v1/health" });
  await bridge.runtime.getStatus();
  await bridge.repositories.selectFolder();
  await bridge.exports.saveJson({ suggestedName: "a.json", content: "{}" });
  await bridge.diagnostics.openLogs();
  await bridge.runtime.restartBackend();
  await bridge.windowControls.getState();
  await bridge.windowControls.minimize();
  await bridge.windowControls.toggleMaximize();
  await bridge.windowControls.close();
  assert.deepEqual(
    invocations.map(([channel]) => channel),
    [
      "api:request",
      "runtime:get-status",
      "repositories:select-folder",
      "exports:save-json",
      "diagnostics:open-logs",
      "runtime:restart-backend",
      "window:get-state",
      "window:minimize",
      "window:toggle-maximize",
      "window:close",
    ],
  );
});

test("window state subscription uses one fixed channel, hides the IPC event, and unsubscribes", () => {
  const { exposed, listeners } = loadPreload();
  const received = [];
  const unsubscribe = exposed.changeAssuranceDesktop.windowControls.onStateChanged((...args) => received.push(args));
  assert.equal(listeners.length, 1);
  assert.equal(listeners[0].channel, "window:state-changed");
  listeners[0].listener({ sender: "secret-ipc-event" }, { maximized: true, fullScreen: false });
  assert.deepEqual(received, [[{ maximized: true, fullScreen: false }]]);
  unsubscribe();
  assert.equal(listeners.length, 0);
});
