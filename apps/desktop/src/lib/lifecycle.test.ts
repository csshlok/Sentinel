import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ALLOWED_TRANSITIONS, GUARDS, allowedTargets, guardText } from "./lifecycle.ts";

const source = readFileSync(new URL("../../../../backend/app/core/lifecycle.py", import.meta.url), "utf8");

/** Parses `_S.NAME` tokens out of a python fragment. */
const names = (fragment: string) => [...fragment.matchAll(/_S\.([A-Z_]+)/g)].map((m) => m[1]!);

test("transition table matches backend/app/core/lifecycle.py", () => {
  const block = source.slice(source.indexOf("ALLOWED_TRANSITIONS"), source.indexOf("GUARDS"));
  // Each entry looks like `_S.FROM: frozenset({ ... }),` possibly spanning lines.
  const entries = [...block.matchAll(/_S\.([A-Z_]+):\s*frozenset\(([\s\S]*?)\),?\s*(?=_S\.[A-Z_]+:|\}\s*$)/g)];
  assert.ok(entries.length >= 19, `expected 19 states, parsed ${entries.length}`);
  for (const [, from, targets] of entries) {
    const expected = names(targets!).sort();
    const actual = [...ALLOWED_TRANSITIONS[from as keyof typeof ALLOWED_TRANSITIONS]].sort();
    assert.deepEqual(actual, expected, `transitions from ${from}`);
  }
  assert.equal(Object.keys(ALLOWED_TRANSITIONS).length, entries.length);
});

test("guards match backend/app/core/lifecycle.py", () => {
  const block = source.slice(source.indexOf("GUARDS"), source.indexOf("def allowed_targets"));
  const entries = [...block.matchAll(/_S\.([A-Z_]+):\s*\(([^)]*)\)/g)];
  assert.ok(entries.length >= 10);
  for (const [, state, guards] of entries) {
    const expected = [...guards!.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    assert.deepEqual([...(GUARDS[state as keyof typeof GUARDS] ?? [])], expected, `guards for ${state}`);
  }
});

test("cancelled is terminal and unknown state falls back to draft moves", () => {
  assert.deepEqual([...allowedTargets("CANCELLED")], []);
  assert.deepEqual([...allowedTargets(undefined)], ["ACTIVE", "CANCELLED"]);
});

test("guard text is readable and unknown guards pass through", () => {
  assert.equal(guardText("authority_valid"), "A valid, unexpired delegation exists");
  assert.equal(guardText("some_new_guard"), "some new guard");
});
