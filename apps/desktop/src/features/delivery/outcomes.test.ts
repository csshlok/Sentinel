import assert from "node:assert/strict";
import { test } from "node:test";
import { groupOutcomes } from "./outcomes.ts";

const o = (id: string, kind: "CI" | "PULL_REQUEST", status: "PASSED" | "FAILED" | "PENDING", at: string, sha = "aaa") => ({
  id, change_id: "c", kind, status, repository: "o/r", head_sha: sha, provider_reference: id, observed_at: at, details: {},
}) as never;

test("a newer failure supersedes an older pass for the same kind", () => {
  const [g] = groupOutcomes([o("1", "CI", "PASSED", "2026-01-01T00:00:00Z"), o("2", "CI", "FAILED", "2026-01-02T00:00:00Z")], "aaa");
  assert.equal(g!.latest.id, "2");
  assert.equal(g!.supersedesPass, true);
  assert.deepEqual(g!.earlier.map((x) => x.id), ["1"]);
});

test("a newer pass after a failure is not flagged", () => {
  const [g] = groupOutcomes([o("1", "CI", "FAILED", "2026-01-01T00:00:00Z"), o("2", "CI", "PASSED", "2026-01-02T00:00:00Z")], "aaa");
  assert.equal(g!.latest.status, "PASSED");
  assert.equal(g!.supersedesPass, false);
});

test("an outcome for another commit is marked stale against the current HEAD", () => {
  const [g] = groupOutcomes([o("1", "CI", "PASSED", "2026-01-01T00:00:00Z", "old")], "new");
  assert.equal(g!.stale, true);
  assert.equal(groupOutcomes([o("1", "CI", "PASSED", "2026-01-01T00:00:00Z", "same")], "same")[0]!.stale, false);
});

test("unknown HEAD is not treated as a mismatch, and kinds stay separate and ordered", () => {
  const groups = groupOutcomes([o("1", "PULL_REQUEST", "PENDING", "2026-01-01T00:00:00Z"), o("2", "CI", "PASSED", "2026-01-01T00:00:00Z")], null);
  assert.deepEqual(groups.map((g) => g.kind), ["CI", "PULL_REQUEST"]);
  assert.ok(groups.every((g) => !g.stale));
});

test("empty input yields no groups", () => {
  assert.deepEqual(groupOutcomes([], "x"), []);
});
