import assert from "node:assert/strict";
import { test } from "node:test";
import { buildDiagnostics } from "./diagnostics.ts";

const runtime = {
  ok: true as const,
  packaged: true,
  backend: { mode: "managed" as const, state: "ready" as const, url: "http://127.0.0.1:53211", detail: "C:\\Users\\me\\secret-path" },
  hasToken: true,
  git: { available: true, version: "2.47.1" },
};

test("the summary lists versions and states", () => {
  const text = buildDiagnostics({ interfaceKind: "desktop", api: "1", reachable: true, runtime, capabilities: [{ id: "journal", state: "AVAILABLE" }] });
  for (const expected of ["Interface: desktop", "Service reachable: yes", "API version: 1", "Build: packaged", "Backend mode: managed", "Git: 2.47.1", "journal: AVAILABLE"]) {
    assert.ok(text.includes(expected), expected);
  }
});

test("it never includes the backend URL, its detail text or a token", () => {
  const text = buildDiagnostics({ interfaceKind: "desktop", api: "1", reachable: true, runtime, capabilities: [] });
  assert.ok(!text.includes("127.0.0.1"));
  assert.ok(!text.includes("secret-path"));
  assert.ok(!/token/i.test(text));
});

test("it still works in a browser with nothing known", () => {
  const text = buildDiagnostics({ interfaceKind: "browser", api: null, reachable: false, runtime: null, capabilities: [] });
  assert.equal(text, "Interface: browser\nService reachable: no\nAPI version: unknown");
});
