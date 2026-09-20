import assert from "node:assert/strict";
import { test } from "node:test";
import { tuiCommands } from "./tui.ts";

test("builds install, token and run commands for a loopback service", () => {
  const c = tuiCommands({ apiUrl: "http://127.0.0.1:8000/" })!;
  assert.equal(c.install, 'python -m pip install -e ".[tui]"');
  assert.equal(c.run, "python -m backend.app.tui.app --api-url http://127.0.0.1:8000");
  assert.match(c.token, /CHANGE_ASSURANCE_API_TOKEN/);
});

test("the token value never appears in any command", () => {
  const c = tuiCommands({ apiUrl: "http://127.0.0.1:8000" })!;
  for (const line of Object.values(c)) assert.ok(!/Bearer|[A-Za-z0-9_-]{40,}/.test(line));
});

test("an actor id is added only when it looks like an id", () => {
  assert.match(tuiCommands({ apiUrl: "http://localhost:9000", actorId: "0d3201c7-5347-4622-8e80-0ef3d12daf76" })!.run, /--actor-id 0d3201c7-/);
  assert.ok(!tuiCommands({ apiUrl: "http://localhost:9000", actorId: "x; rm -rf /" })!.run.includes("--actor-id"));
});

test("a non-loopback or malformed address produces no command", () => {
  for (const bad of ["http://evil.example:8000", "https://127.0.0.1:8000", "", "127.0.0.1:8000", "http://127.0.0.1"]) assert.equal(tuiCommands({ apiUrl: bad }), null);
});
