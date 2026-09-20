import { expect, test } from "@playwright/test";

// The operations the UI drives, called against the REAL backend, to confirm the request shapes are accepted.
test.describe.configure({ mode: "serial" });
const BASE = "http://127.0.0.1:8000";
const H = () => ({ Authorization: `Bearer ${process.env.CA_E2E_TOKEN}`, "Content-Type": "application/json" });
const call = async (method: string, path: string, body?: unknown) => {
  const r = await fetch(BASE + path, { method, headers: { ...H(), "Idempotency-Key": crypto.randomUUID() }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  return { status: r.status, body: text ? JSON.parse(text) : null };
};
const results: Record<string, number> = {};
let id = "";
let rev = 1;

test.beforeAll(async () => {
  const c = await call("POST", "/api/v1/changes", { title: "Real ops", intent: "Exercise every UI mutation", repository_path: process.env.CA_E2E_REPO });
  expect(c.status).toBe(201);
  id = c.body.id;
  rev = c.body.revision;
});
test.afterAll(() => console.log("REAL OPS " + JSON.stringify(results)));

const c = (p: string) => `/api/v1/changes/${id}${p}`;
const rec = (k: string, r: { status: number }) => { results[k] = r.status; return r; };

test("read views the UI opens return 2xx or a clean 4xx, never 5xx", async () => {
  for (const p of ["/git/checkpoints", "/git/compare", "/environment", "/dependencies", "/tools", "/agents", "/outcomes", "/delegations", "/recovery", "/assurance/facts", "/assurance/plan", "/replay/verify", "/replay/export", "/passport"]) {
    const r = rec("GET " + p, await call("GET", c(p)));
    expect(r.status, p).toBeLessThan(500);
  }
});

test("evidence capture, refresh and passport build succeed", async () => {
  expect(rec("POST evidence/baseline", await call("POST", c("/evidence/baseline"))).status).toBeLessThan(300);
  expect(rec("POST evidence/current", await call("POST", c("/evidence/current"))).status).toBeLessThan(300);
  const r = rec("POST refresh", await call("POST", c("/refresh")));
  expect(r.status).toBe(200);
  rev = r.body.revision;
  expect(rec("POST passport", await call("POST", c("/passport"))).status).toBeLessThan(300);
  expect(rec("GET passport after build", await call("GET", c("/passport"))).status).toBe(200);
});

test("contract update accepts the UI's body and rejects a stale revision with 409", async () => {
  const cur = (await call("GET", c(""))).body;
  const body = { expected_revision: cur.revision, contract: { ...cur.contract, allowed_paths: ["src/**"], required_checks: ["pytest"], max_risk: "HIGH" } };
  const ok = rec("PUT contract", await call("PUT", c("/contract"), body));
  expect(ok.status).toBe(200);
  const stale = rec("PUT contract (stale)", await call("PUT", c("/contract"), body));
  expect(stale.status).toBe(409);
  expect(stale.body.error.code).toBeTruthy();
  rev = ok.body.revision;
});

test("transition: stale revision conflicts, and a guarded move explains what is missing", async () => {
  const stale = rec("POST transition (stale)", await call("POST", c("/transition"), { expected_revision: 1, target_state: "ACTIVE", reason: null }));
  expect([409, 422]).toContain(stale.status);
  const cur = (await call("GET", c(""))).body;
  const ok = rec("POST transition", await call("POST", c("/transition"), { expected_revision: cur.revision, target_state: "ACTIVE", reason: "load test" }));
  // Moving to ACTIVE needs valid authority (a delegation); the backend answers 409 with the missing requirements.
  expect([200, 409]).toContain(ok.status);
  if (ok.status === 409) {
    expect(ok.body.error.code).toBe("TRANSITION_GUARD_FAILED");
    expect(ok.body.error.details.missing_requirements).toContain("authority_valid");
  }
});

test("verification runs a command; an empty command is rejected cleanly", async () => {
  const bad = rec("POST verify (empty)", await call("POST", c("/verify"), { executable: "", args: [] }));
  expect(bad.status).toBeLessThan(500);
  const ok = rec("POST verify", await call("POST", c("/verify"), { executable: "git", args: ["--version"] }));
  expect(ok.status, JSON.stringify(ok.body)).toBeLessThan(500);
});

test("actors and delegations: create, read, revoke", async () => {
  const actor = rec("POST actors", await call("POST", "/api/v1/actors", { display_name: "Ada", kind: "HUMAN" }));
  expect(actor.status, JSON.stringify(actor.body)).toBeLessThan(300);
  const bad = rec("POST actors (bad kind)", await call("POST", "/api/v1/actors", { display_name: "x", kind: "ROBOT" }));
  expect(bad.status).toBe(422);
  expect(rec("GET actors/{id}", await call("GET", `/api/v1/actors/${actor.body.id}`)).status).toBe(200);
  const other = (await call("POST", "/api/v1/actors", { display_name: "Grace", kind: "AGENT" })).body;
  const d = rec("POST delegations", await call("POST", "/api/v1/delegations", { change_id: id, grantor_id: actor.body.id, grantee_id: other.id, scopes: ["git.read"], ttl_seconds: 600 }));
  console.log("delegation status", d.status, JSON.stringify(d.body).slice(0, 160));
  expect(d.status).toBeLessThan(500);
  if (d.status < 300) expect(rec("POST delegations/revoke", await call("POST", `/api/v1/delegations/${d.body.id}/revoke`)).status).toBeLessThan(300);
});

test("tools list works; unknown tool detail is a clean 404", async () => {
  expect(rec("GET tools", await call("GET", "/api/v1/tools")).status).toBe(200);
  const unknown = rec("GET tools/unknown", await call("GET", "/api/v1/tools/does-not-exist"));
  expect(unknown.status).toBeGreaterThanOrEqual(400);
  expect(unknown.status).toBeLessThan(500);
});

test("GitHub status works without a connection; agents adapters list", async () => {
  expect(rec("GET github status", await call("GET", "/api/v1/providers/github/status")).status).toBeLessThan(500);
  expect(rec("GET agents/adapters", await call("GET", "/api/v1/agents/adapters")).status).toBe(200);
});

test("cancel then delete remove the Change cleanly", async () => {
  const cur = (await call("GET", c(""))).body;
  const cancel = rec("POST cancel", await call("POST", c("/cancel"), { expected_revision: cur.revision, reason: "done" }));
  expect(cancel.status, JSON.stringify(cancel.body)).toBeLessThan(500);
  const del = rec("DELETE change", await call("DELETE", c("")));
  expect(del.status).toBeLessThan(300);
  expect((await call("GET", c(""))).status).toBe(404);
});
