import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

const mem = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => mem.get(k) ?? null,
  setItem: (k: string, v: string) => void mem.set(k, v),
};
const known = await import("./known.ts");

beforeEach(() => mem.clear());

const a = (id: string, name = id) => ({ id, display_name: name, kind: "HUMAN" as const });

test("remembers actors newest first and de-duplicates by id", () => {
  known.rememberActor(a("1", "Ada"));
  known.rememberActor(a("2", "Bo"));
  known.rememberActor(a("1", "Ada Lovelace"));
  assert.deepEqual(known.knownActors().map((x) => [x.id, x.display_name]), [["1", "Ada Lovelace"], ["2", "Bo"]]);
});

test("corrupt or hostile storage yields an empty list, never a throw", () => {
  mem.set("ca.known-actors.v1", "{not json");
  assert.deepEqual(known.knownActors(), []);
  mem.set("ca.known-actors.v1", JSON.stringify([{ id: 5 }, null, "x", { id: "ok", display_name: "Ok", kind: "AGENT" }]));
  assert.deepEqual(known.knownActors().map((x) => x.id), ["ok"]);
});

test("grants are scoped to their Change and never store a token", () => {
  known.rememberGrant({ id: "g1", change_id: "c1", actor_id: "a", provider: "github", scopes: ["pulls:write"], issued_at: "2026-01-01T00:00:00Z", expires_at: "2026-01-02T00:00:00Z" });
  known.rememberGrant({ id: "g2", change_id: "c2", actor_id: "a", provider: "github", scopes: [], issued_at: "", expires_at: "" });
  assert.deepEqual(known.knownGrants("c1").map((g) => g.id), ["g1"]);
  assert.ok(!/token|secret/i.test(mem.get("ca.known-grants.v1")!));
  known.markGrantRevoked("g1");
  assert.equal(known.knownGrants("c1")[0]!.revoked, true);
});

test("mergeActors keeps the first source's copy", () => {
  const merged = known.mergeActors([a("1", "Fresh")], [a("1", "Stale"), a("2")]);
  assert.deepEqual(merged.map((x) => x.display_name), ["Fresh", "2"]);
});

test("storage is capped", () => {
  for (let i = 0; i < 260; i++) known.rememberActor(a(String(i)));
  assert.equal(known.knownActors().length, 200);
});
