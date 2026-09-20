import assert from "node:assert/strict";
import test from "node:test";
import {
  ApiError,
  assertApiPath,
  kindFromBridgeCode,
  kindFromStatus,
  unwrapEnvelope,
  withAbort,
} from "./client.ts";

test("assertApiPath accepts plain /api/v1 paths", () => {
  for (const ok of ["/api/v1/health", "/api/v1/changes/abc-123", "/api/v1/changes?limit=5"]) {
    assert.doesNotThrow(() => assertApiPath(ok), ok);
  }
});

test("assertApiPath rejects everything else", () => {
  for (const bad of ["/health", "/api/v2/x", "api/v1/x", "/api/v1/../x", "/api/v1//x", "https://x/api/v1/y", "/api/v1/a b", "/api/v1/a#b", "/api/v1\\x", ""]) {
    assert.throws(() => assertApiPath(bad), (e: unknown) => e instanceof ApiError && e.code === "invalid_path", bad);
  }
});

test("status codes map to actionable kinds, with auth kept distinct", () => {
  assert.equal(kindFromStatus(401), "auth");
  assert.equal(kindFromStatus(403), "auth");
  assert.equal(kindFromStatus(404), "not_found");
  assert.equal(kindFromStatus(409), "conflict");
  assert.equal(kindFromStatus(422), "validation");
  assert.equal(kindFromStatus(500), "server");
  assert.equal(kindFromBridgeCode("backend_unreachable"), "offline");
  assert.equal(kindFromBridgeCode("backend_timeout"), "timeout");
  assert.equal(kindFromBridgeCode("forbidden_path"), "bridge");
});

test("unwrapEnvelope returns 2xx bodies and normalizes the error envelope", () => {
  assert.deepEqual(unwrapEnvelope(200, { a: 1 }), { a: 1 });
  assert.equal(unwrapEnvelope(204, null), null);
  try {
    unwrapEnvelope(401, { error: { code: "UNAUTHENTICATED", message: "A bearer token is required." } });
    assert.fail("should throw");
  } catch (error) {
    assert.ok(error instanceof ApiError);
    assert.equal(error.kind, "auth");
    assert.equal(error.code, "UNAUTHENTICATED");
    assert.equal(error.status, 401);
  }
});

test("unwrapEnvelope tolerates malformed error bodies without leaking them", () => {
  for (const body of [null, "boom", { error: 5 }, { detail: "secret-token" }]) {
    try {
      unwrapEnvelope(500, body);
      assert.fail("should throw");
    } catch (error) {
      assert.ok(error instanceof ApiError);
      assert.equal(error.kind, "server");
      assert.ok(!error.message.includes("secret-token"));
    }
  }
});

test("withAbort rejects with an aborted error and cleans up", async () => {
  const controller = new AbortController();
  const pending = withAbort(new Promise(() => {}), controller.signal);
  controller.abort();
  await assert.rejects(pending, (e: unknown) => e instanceof ApiError && e.kind === "aborted");
  await assert.rejects(withAbort(Promise.resolve(1), AbortSignal.abort()), (e: unknown) => e instanceof ApiError && e.kind === "aborted");
  assert.equal(await withAbort(Promise.resolve(7)), 7);
});
