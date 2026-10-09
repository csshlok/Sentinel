"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { createBundleFetch, BUNDLE_MEDIA_TYPE } = require("../api-proxy.cjs");
const { savePassportBundle } = require("../native-dialogs.cjs");

const TOKEN = "secret-token-value-123";
const ID = "1b2c3d4e-0000-4000-8000-00000000abcd";

function fetcher({ status = 200, type = BUNDLE_MEDIA_TYPE, bytes = Buffer.from("PK\u0003\u0004zip"), baseUrl = "http://127.0.0.1:8000", fail } = {}) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    if (fail) throw fail;
    return {
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (name) => (name.toLowerCase() === "content-type" ? type : null) },
      arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    };
  };
  return { fetchBundle: createBundleFetch({ getBaseUrl: () => baseUrl, getToken: () => TOKEN, fetchImpl }), calls };
}

test("fetches only the fixed bundle route for a UUID, with the token, and returns the bytes", async () => {
  const { fetchBundle, calls } = fetcher();
  const result = await fetchBundle(ID);
  assert.equal(result.ok, true);
  assert.equal(result.bytes.toString("latin1"), "PK\u0003\u0004zip");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `http://127.0.0.1:8000/api/v1/changes/${ID}/passport/v2/bundle`);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(calls[0].init.redirect, "error");
});

test("refuses anything that is not a Change UUID before any request", async () => {
  const { fetchBundle, calls } = fetcher();
  for (const bad of [undefined, null, 5, "", "../../health", `${ID}/../x`, "not-a-uuid", `${ID}?x=1`]) {
    await assert.rejects(fetchBundle(bad), (e) => e.code === "invalid_request");
  }
  assert.equal(calls.length, 0);
});

test("a non-loopback backend is refused", async () => {
  const { fetchBundle, calls } = fetcher({ baseUrl: "http://evil.example:8000" });
  await assert.rejects(fetchBundle(ID), (e) => e.code === "invalid_backend_url");
  assert.equal(calls.length, 0);
});

test("an error envelope or a wrong media type is an error result, never saved bytes", async () => {
  const envelope = Buffer.from(JSON.stringify({ error: { code: "PASSPORT_V2_UNAVAILABLE", message: "No signing key." } }));
  const failed = await fetcher({ status: 409, type: "application/json", bytes: envelope }).fetchBundle(ID);
  assert.deepEqual(failed, { ok: false, error: { code: "bundle_unavailable", message: "No signing key." } });
  const html = await fetcher({ status: 200, type: "text/html", bytes: Buffer.from("<html>") }).fetchBundle(ID);
  assert.equal(html.ok, false);
  assert.equal(html.error.message, "The backend did not return a Passport bundle.");
});

test("network failure and timeout map to stable codes", async () => {
  await assert.rejects(fetcher({ fail: new TypeError("refused") }).fetchBundle(ID), (e) => e.code === "backend_unreachable");
  const timeout = Object.assign(new Error("t"), { name: "TimeoutError" });
  await assert.rejects(fetcher({ fail: timeout }).fetchBundle(ID), (e) => e.code === "backend_timeout");
});

function deps(dialogResult, fetched) {
  const calls = { dialog: [], writes: [], fetched: [] };
  return {
    calls,
    deps: {
      window: {},
      dialog: { showSaveDialog: async (...a) => (calls.dialog.push(a), dialogResult) },
      writeFile: async (...a) => void calls.writes.push(a),
      fetchBundle: async (id) => (calls.fetched.push(id), fetched),
    },
  };
}

test("saves the fetched bytes only to the path the user picked, adding the .sentinel extension", async () => {
  const bytes = Buffer.from("zip");
  const h = deps({ canceled: false, filePath: "C:\\Users\\me\\bundle" }, { ok: true, bytes });
  const result = await savePassportBundle(h.deps, { changeId: ID });
  assert.deepEqual(result, { ok: true, path: "C:\\Users\\me\\bundle.sentinel" });
  assert.deepEqual(h.calls.writes, [["C:\\Users\\me\\bundle.sentinel", bytes]]);
  assert.equal(h.calls.dialog[0][1].defaultPath, `change-${ID}.sentinel`);
});

test("cancel writes nothing; a failed fetch shows no dialog", async () => {
  const cancelled = deps({ canceled: true }, { ok: true, bytes: Buffer.from("zip") });
  assert.deepEqual(await savePassportBundle(cancelled.deps, { changeId: ID }), { ok: true, path: null });
  assert.equal(cancelled.calls.writes.length, 0);
  const failure = { ok: false, error: { code: "bundle_unavailable", message: "No." } };
  const failed = deps({ canceled: false, filePath: "C:\\x.sentinel" }, failure);
  assert.deepEqual(await savePassportBundle(failed.deps, { changeId: ID }), failure);
  assert.equal(failed.calls.dialog.length, 0);
  assert.equal(failed.calls.writes.length, 0);
});
