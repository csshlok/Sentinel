import assert from "node:assert/strict";
import { test } from "node:test";
import { displayPayload, restorationText } from "./payload.ts";

test("credential-looking keys are hidden at any depth", () => {
  const out = displayPayload({ ok: 1, token: "abc", nested: { Authorization: "Bearer x", api_key: "k", fine: "v" }, list: [{ password: "p" }] });
  assert.deepEqual(out, { ok: 1, token: "[hidden]", nested: { Authorization: "[hidden]", api_key: "[hidden]", fine: "v" }, list: [{ password: "[hidden]" }] });
});

test("long strings, long arrays and deep nesting are bounded", () => {
  const long = displayPayload("x".repeat(600)) as string;
  assert.ok(long.length < 560 && long.includes("600 characters"));
  assert.equal((displayPayload(Array.from({ length: 200 }, (_, i) => i)) as number[]).length, 50);
  let deep: unknown = "leaf";
  for (let i = 0; i < 12; i++) deep = { d: deep };
  assert.ok(JSON.stringify(displayPayload(deep)).includes("[nested value omitted]"));
});

test("scalars, null and odd values are handled without throwing", () => {
  assert.equal(displayPayload(null), null);
  assert.equal(displayPayload(3), 3);
  assert.equal(displayPayload(false), false);
  assert.equal(displayPayload(undefined), "undefined");
});

test("input is not mutated", () => {
  const input = { token: "secret", a: { b: 1 } };
  displayPayload(input);
  assert.deepEqual(input, { token: "secret", a: { b: 1 } });
});

test("restoration classes read literally and unknown ones pass through", () => {
  assert.equal(restorationText("none"), "Can't be undone");
  assert.equal(restorationText("exact"), "Can be restored exactly");
  assert.equal(restorationText("something_new"), "something new");
});
