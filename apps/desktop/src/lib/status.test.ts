import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { formatRelative, lifecycleInfo, repoName, reviewInfo, riskInfo, shortSha, signatureInfo, trustInfo, LIFECYCLE_PATH } from "./status.ts";

const spec = JSON.parse(readFileSync(new URL("../../../../openapi.json", import.meta.url), "utf8"));
const enumOf = (name: string): string[] => spec.components.schemas[name].enum;

test("every backend enum value has a real label (no undefined, no raw codes leaking as blanks)", () => {
  for (const s of enumOf("ChangeLifecycleState")) assert.ok(lifecycleInfo(s as never)?.label.length > 0, s);
  for (const s of enumOf("ReviewState")) assert.ok(reviewInfo(s as never)?.label.length > 0, s);
  for (const s of enumOf("RiskLevel")) assert.ok(riskInfo(s as never)?.label.length > 0, s);
  for (const s of enumOf("ToolTrustState")) assert.ok(trustInfo(s as never)?.label.length > 0, s);
  for (const s of enumOf("ToolSignatureState")) assert.ok(signatureInfo(s as never)?.label.length > 0, s);
});

test("the lifecycle rail only contains real lifecycle states, in order, without duplicates", () => {
  const all = new Set(enumOf("ChangeLifecycleState"));
  assert.ok(LIFECYCLE_PATH.every((s) => all.has(s)));
  assert.equal(new Set(LIFECYCLE_PATH).size, LIFECYCLE_PATH.length);
});

test("denied and failed states are never shown as a success tone", () => {
  assert.equal(trustInfo("DENIED").tone, "danger");
  assert.equal(lifecycleInfo("FAILED").tone, "danger");
  assert.equal(lifecycleInfo("BLOCKED").tone, "danger");
  assert.equal(reviewInfo("FAILED_VERIFICATION").tone, "danger");
  assert.equal(signatureInfo("invalid").tone, "danger");
});

test("relative time handles boundaries, the future, and bad input", () => {
  const now = Date.parse("2026-09-19T12:00:00Z");
  const ago = (s: number) => new Date(now - s * 1000).toISOString();
  assert.equal(formatRelative(ago(5), now), "just now");
  assert.equal(formatRelative(ago(59), now), "just now");
  assert.match(formatRelative(ago(60), now), /1 minute ago/);
  assert.match(formatRelative(ago(3 * 3600), now), /3 hours ago/);
  assert.match(formatRelative(ago(2 * 86400), now), /2 days ago/);
  assert.equal(formatRelative(new Date(now + 20_000).toISOString(), now), "just now");
  assert.equal(formatRelative(null, now), "—");
  assert.equal(formatRelative(undefined, now), "—");
});

test("short sha and repository names cope with odd values", () => {
  assert.equal(shortSha("abcdef1234567890"), "abcdef12");
  assert.equal(shortSha(null), "—");
  assert.equal(shortSha(""), "—");
  assert.equal(repoName("C:\\work\\my repo"), "my repo");
  assert.equal(repoName("/home/u/project"), "project");
  assert.equal(repoName(""), "");
});

test("a value from a newer backend degrades to a neutral label instead of throwing", async () => {
  const status = await import("./status.ts");
  const fns = [status.lifecycleInfo, status.reviewInfo, status.trustInfo, status.signatureInfo, status.agentRunInfo, status.assuranceInfo, status.evidenceInfo, status.outcomeInfo, status.recoveryInfo, status.riskInfo] as ((v: never) => { label: string; tone: string })[];
  for (const fn of fns) {
    const out = fn("SOMETHING_NEW" as never);
    assert.equal(out.label, "something new");
    assert.equal(out.tone, "neutral");
  }
});
