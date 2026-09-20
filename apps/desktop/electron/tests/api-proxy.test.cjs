"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { createApiProxy, parseLoopbackBase } = require("../api-proxy.cjs");

const TOKEN = "secret-token-value-123";

function harness({ status = 200, body = { ok: true }, baseUrl = "http://127.0.0.1:8000", fail } = {}) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    if (fail) throw fail;
    return { status, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) };
  };
  const proxy = createApiProxy({ getBaseUrl: () => baseUrl, getToken: () => TOKEN, fetchImpl });
  return { proxy, calls };
}

const rejects = (promise, code) =>
  assert.rejects(promise, (error) => {
    assert.equal(error.code, code);
    return true;
  });

test("allows GET, POST, PUT and DELETE on /api/v1 paths", async () => {
  for (const method of ["GET", "POST", "PUT", "DELETE"]) {
    const { proxy, calls } = harness();
    const result = await proxy({ method, path: "/api/v1/changes", body: method === "GET" ? undefined : { a: 1 } });
    assert.equal(result.ok, true);
    assert.equal(calls[0].init.method, method);
    assert.equal(calls[0].url, "http://127.0.0.1:8000/api/v1/changes");
  }
});

test("rejects PATCH, HEAD, OPTIONS and unknown methods", async () => {
  for (const method of ["PATCH", "HEAD", "OPTIONS", "TRACE", "get", undefined, 5]) {
    const { proxy, calls } = harness();
    await rejects(proxy({ method, path: "/api/v1/health" }), "forbidden_method");
    assert.equal(calls.length, 0, `${String(method)} must not reach the network`);
  }
});

test("rejects non-API, traversal and malformed paths", async () => {
  const bad = [
    "/etc/passwd",
    "/api/v2/health",
    "/api/v1",
    "api/v1/health",
    "/api/v1/../secret",
    "/api/v1//health",
    "http://evil.example/api/v1/health",
    "//evil.example/api/v1/x",
    "",
    null,
    {},
  ];
  for (const path of bad) {
    const { proxy, calls } = harness();
    await rejects(proxy({ method: "GET", path }), "forbidden_path");
    assert.equal(calls.length, 0, `${String(path)} must not reach the network`);
  }
});

test("injects the bearer token only in the outgoing request", async () => {
  const { proxy, calls } = harness();
  const result = await proxy({ method: "GET", path: "/api/v1/capabilities" });
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.ok(!JSON.stringify(result).includes(TOKEN), "token must not appear in the bridge return value");
});

test("ignores renderer-supplied headers and never returns request headers", async () => {
  const { proxy, calls } = harness();
  const result = await proxy({
    method: "GET",
    path: "/api/v1/health",
    headers: { Authorization: "Bearer attacker", Host: "evil" },
  });
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(calls[0].init.headers.Host, undefined);
  assert.deepEqual(Object.keys(result).sort(), ["body", "ok", "status"]);
});

test("only forwards a well-formed idempotency key", async () => {
  const good = harness();
  await good.proxy({ method: "POST", path: "/api/v1/changes", body: {}, idempotencyKey: "abc-123" });
  assert.equal(good.calls[0].init.headers["Idempotency-Key"], "abc-123");
  const bad = harness();
  await bad.proxy({ method: "POST", path: "/api/v1/changes", body: {}, idempotencyKey: "x\r\nInjected: 1" });
  assert.equal(bad.calls[0].init.headers["Idempotency-Key"], undefined);
});

test("refuses redirects and oversized request bodies", async () => {
  const { proxy, calls } = harness();
  await proxy({ method: "GET", path: "/api/v1/health" });
  assert.equal(calls[0].init.redirect, "error");
  await rejects(
    proxy({ method: "POST", path: "/api/v1/changes", body: { blob: "x".repeat(2_000_000) } }),
    "request_too_large",
  );
});

test("passes backend error statuses through as data, not exceptions", async () => {
  const { proxy } = harness({ status: 401, body: { error: { code: "UNAUTHENTICATED", message: "A bearer token is required." } } });
  const result = await proxy({ method: "GET", path: "/api/v1/capabilities" });
  assert.equal(result.ok, true);
  assert.equal(result.status, 401);
});

test("maps network failure, timeout and bad JSON to stable codes", async () => {
  await rejects(harness({ fail: new Error("ECONNREFUSED") }).proxy({ method: "GET", path: "/api/v1/health" }), "backend_unreachable");
  const timeout = Object.assign(new Error("t"), { name: "TimeoutError" });
  await rejects(harness({ fail: timeout }).proxy({ method: "GET", path: "/api/v1/health" }), "backend_timeout");
  await rejects(harness({ body: "<html>" }).proxy({ method: "GET", path: "/api/v1/health" }), "invalid_response");
});

test("reports an unavailable backend when no URL is set", async () => {
  const proxy = createApiProxy({ getBaseUrl: () => "", getToken: () => TOKEN, fetchImpl: async () => assert.fail("no network") });
  await rejects(proxy({ method: "GET", path: "/api/v1/health" }), "backend_unreachable");
});

test("accepts only plain loopback http base URLs", () => {
  for (const good of ["http://127.0.0.1:8000", "http://localhost:9000"]) assert.ok(parseLoopbackBase(good));
  for (const bad of [
    "https://127.0.0.1:8000",
    "http://example.com",
    "http://user:pw@127.0.0.1:8000",
    "http://127.0.0.1:8000/api",
    "file:///etc/passwd",
    "not a url",
  ]) {
    assert.throws(() => parseLoopbackBase(bad), (error) => error.code === "invalid_backend_url", bad);
  }
});
