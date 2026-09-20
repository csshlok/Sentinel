import assert from "node:assert/strict";
import { test } from "node:test";

// Node's test runner can't resolve the "@/" alias, so this checks the pure rules through a local re-import of the module's logic.
const { canExecute, approvalPhrase } = await import("./rules.ts");

const plan = (over: Record<string, unknown> = {}) =>
  ({ id: "12345678-aaaa-bbbb-cccc-000000000000", change_id: "c", source_checkpoint_id: "s", created_at: "2026-01-01T00:00:00Z", status: "PLANNED", conflicts: [], unsupported_effects: [], actions: [{ id: "a", kind: "git_revert", description: "d", supported: true, reversible_commit: "ABCDEF" }], ...over }) as never;

test("a fresh planned, supported plan is executable when the contract allows recovery", () => {
  assert.deepEqual(canExecute(plan(), "abcdef", true), { ok: true, reasons: [] });
});

test("HEAD moving since the preview makes the plan stale", () => {
  const r = canExecute(plan(), "999999", true);
  assert.equal(r.ok, false);
  assert.match(r.reasons.join(" "), /HEAD moved/);
});

test("conflicts, unsupported actions, disallowed contract and non-planned status each block execution", () => {
  assert.match(canExecute(plan({ conflicts: ["x"] }), "abcdef", true).reasons.join(" "), /conflicts/);
  assert.match(canExecute(plan({ actions: [{ id: "a", kind: "k", description: "d", supported: false }] }), "abcdef", true).reasons.join(" "), /isn't supported/);
  assert.match(canExecute(plan(), "abcdef", false).reasons.join(" "), /doesn't allow recovery/);
  assert.match(canExecute(plan({ status: "RECOVERED" }), "abcdef", true).reasons.join(" "), /recovered/);
});

test("an approval phrase is the plan's first eight characters", () => {
  assert.equal(approvalPhrase(plan()), "12345678");
});

test("unknown HEAD does not block on staleness", () => {
  assert.equal(canExecute(plan(), null, true).ok, true);
});
