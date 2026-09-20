"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { buildRuntimeStatus } = require("../runtime-status.cjs");
const { selectFolder } = require("../native-dialogs.cjs");
const { toSafeError } = require("../ipc-errors.cjs");

const backend = { mode: "managed", state: "ready", url: "http://127.0.0.1:5000", detail: null };

test("runtime status has a fixed shape and reports the token only as a boolean", () => {
  const status = buildRuntimeStatus({ packaged: false, backend, token: "super-secret-token", git: { available: true, version: "2.51.0.windows.1" } });
  assert.deepEqual(status, {
    ok: true,
    packaged: false,
    backend: { mode: "managed", state: "ready", url: "http://127.0.0.1:5000", detail: null },
    hasToken: true,
    git: { available: true, version: "2.51.0.windows.1" },
  });
  assert.ok(!JSON.stringify(status).includes("super-secret-token"));
});

test("runtime status drops unknown fields instead of forwarding them", () => {
  const status = buildRuntimeStatus({
    packaged: true,
    backend: { ...backend, token: "leak", env: { SECRET: "x" } },
    token: "",
  });
  assert.equal(status.hasToken, false);
  assert.deepEqual(status.git, { available: false, version: null });
  assert.deepEqual(Object.keys(status.backend).sort(), ["detail", "mode", "state", "url"]);
  assert.ok(!JSON.stringify(status).includes("leak"));
});

test("safe errors never echo internal error messages", () => {
  const unknown = toSafeError(new Error("open C:\\Users\\me\\secret.txt failed, token=abc"));
  assert.equal(unknown.ok, false);
  assert.equal(unknown.error.code, "internal_error");
  assert.ok(!JSON.stringify(unknown).includes("secret.txt"));
  const known = toSafeError(Object.assign(new Error("Only /api/v1 paths are allowed."), { code: "forbidden_path" }));
  assert.equal(known.error.code, "forbidden_path");
});

test("folder picker returns a path or null and nothing else", async () => {
  const picked = await selectFolder({ dialog: { showOpenDialog: async () => ({ canceled: false, filePaths: ["C:\\repo"] }) }, window: null });
  assert.deepEqual(picked, { ok: true, path: "C:\\repo" });
  const canceled = await selectFolder({ dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) }, window: null });
  assert.deepEqual(canceled, { ok: true, path: null });
});
