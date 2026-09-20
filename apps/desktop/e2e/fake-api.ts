import type { Page, Route } from "@playwright/test";

/** A scriptable stand-in for the backend, served through `page.route`, so failure and scale states are deterministic. */
export interface FakeChange {
  id: string;
  title: string;
  intent: string;
  repository_path: string;
  review_state: string;
  lifecycle_state: string;
  files?: number;
  updated_at?: string;
  revision?: number;
  contract?: Record<string, unknown>;
  /** What the backend reports as legal next states; omitted to simulate an older backend. */
  allowedNext?: string[];
  forkedFrom?: string;
}

export interface FakeApi {
  changes: FakeChange[];
  events: Record<string, unknown[]>;
  tools: unknown[];
  /** null simulates a backend without `GET /actors`. */
  actors: { id: string; display_name: string; kind: string }[] | null;
  online: boolean;
  requireToken: string | null;
  delayMs: number;
  /** path -> handler override, e.g. `{ "/api/v1/repositories/validate": (body) => ({...}) }` */
  validate: (path: string) => { status: number; body: unknown; delayMs?: number };
  createStatus: number;
  posts: { path: string; key: string | undefined; body: any }[];
  /** every mutating call after create: method, operation name, body */
  calls: { method: string; path: string; body: any }[];
  passports: Record<string, unknown>;
  lists: Record<string, Record<string, unknown[]>>;
  requests: string[];
}

const NOW = "2026-09-19T12:00:00Z";

export function makeChange(i: number, over: Partial<FakeChange> = {}): FakeChange {
  return {
    id: `chg-${String(i).padStart(4, "0")}`,
    title: `Change number ${i}`,
    intent: `Intent for change ${i}`,
    repository_path: `C:\\work\\repo-${i % 7}`,
    review_state: i % 5 === 0 ? "MISSING_EVIDENCE" : "NO_CHANGES",
    lifecycle_state: "DRAFT",
    ...over,
  };
}

function view(c: FakeChange) {
  const files = Array.from({ length: c.files ?? 0 }, (_, n) => ({ path: `src/file-${n}.ts`, status: "MODIFIED", additions: 3, deletions: 1 }));
  return {
    id: c.id,
    title: c.title,
    intent: c.intent,
    repository_path: c.repository_path,
    created_at: NOW,
    updated_at: c.updated_at ?? NOW,
    review_state: c.review_state,
    lifecycle_state: c.lifecycle_state,
    revision: c.revision ?? 1,
    risk_level: "UNKNOWN",
    contract: c.contract ?? { allowed_paths: [], forbidden_paths: [], required_checks: [], expected_outcomes: [], authority_ceiling: [], allowed_provider_operations: [], max_risk: "UNKNOWN", recovery_allowed: false, schema_version: 1 },
    git_summary: c.files === undefined ? null : { branch: "main", head_sha: "a".repeat(40), is_clean: c.files === 0, files, patch: "", refreshed_at: NOW, repository_root: c.repository_path, total_additions: (c.files ?? 0) * 3, total_deletions: c.files ?? 0 },
    verification: null,
    ...(c.allowedNext ? { allowed_next_states: c.allowedNext } : {}),
    ...(c.forkedFrom ? { forked_from_change_id: c.forkedFrom, forked_from_checkpoint_id: "cp-00000000-0000" } : {}),
  };
}

export const envelope = (status: number, code: string, message: string) => ({ status, body: { error: { code, message, details: {} } } });

export async function installFakeApi(page: Page, overrides: Partial<FakeApi> = {}): Promise<FakeApi> {
  const api: FakeApi = {
    changes: [],
    events: {},
    tools: [],
    actors: null,
    online: true,
    requireToken: null,
    delayMs: 0,
    validate: () => ({ status: 200, body: { branch: "main", head_sha: "b".repeat(40), root: "C:\\work\\repo" } }),
    createStatus: 201,
    posts: [],
    calls: [],
    passports: {},
    lists: {},
    requests: [],
    ...overrides,
  };
  const json = (route: Route, status: number, body: unknown) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    api.requests.push(`${req.method()} ${path}${url.search}`);
    if (!api.online) return route.abort("connectionrefused");
    if (api.delayMs) await new Promise((r) => setTimeout(r, api.delayMs));
    if (path === "/api/v1/health") return json(route, 200, { api_version: "1", status: "ok" });
    const auth = req.headers()["authorization"];
    if (api.requireToken && auth !== `Bearer ${api.requireToken}`) {
      const e = envelope(401, "UNAUTHENTICATED", auth ? "The bearer token is invalid." : "A bearer token is required.");
      return json(route, e.status, e.body);
    }
    if (path === "/api/v1/capabilities") {
      return json(route, 200, { items: [{ id: "change_lifecycle", name: "Change Lifecycle", state: "AVAILABLE", reason: null, limitations: [] }] });
    }
    if (path === "/api/v1/system/backend-identity") return json(route, 200, { service_name: "change-assurance", api_version: "1", instance_id: "0123456789abcdef", started_at: NOW });
    if (path === "/api/v1/actors" && req.method() === "GET") {
      if (api.actors === null) return json(route, 404, envelope(404, "NOT_FOUND", "Not found.").body);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 100);
      const items = api.actors.slice(offset, offset + limit);
      return json(route, 200, { count: items.length, total: api.actors.length, items });
    }
    if (path === "/api/v1/actors" && req.method() === "POST") {
      const body = req.postDataJSON();
      api.calls.push({ method: "POST", path, body });
      const actor = { id: `actor-${(api.actors?.length ?? 0) + 1}-0000`, display_name: body.display_name, kind: body.kind, created_at: NOW, updated_at: NOW, revision: 1 };
      api.actors?.push(actor);
      return json(route, 201, actor);
    }
    if (path === "/api/v1/tools") return json(route, 200, { count: api.tools.length, items: api.tools });
    if (path === "/api/v1/repositories/validate") {
      const body = req.postDataJSON();
      const out = api.validate(body.path);
      if (out.delayMs) await new Promise((r) => setTimeout(r, out.delayMs));
      return json(route, out.status, out.body);
    }
    if (path === "/api/v1/changes" && req.method() === "GET") {
      const limit = Number(url.searchParams.get("limit") ?? 100);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const items = api.changes.slice(offset, offset + limit).map(view);
      return json(route, 200, { count: items.length, total: api.changes.length, items });
    }
    if (path === "/api/v1/changes" && req.method() === "POST") {
      const body = req.postDataJSON();
      api.posts.push({ path, key: req.headers()["idempotency-key"], body });
      if (api.createStatus !== 201) {
        const e = envelope(api.createStatus, "SERVER_ERROR", "The service failed.");
        return json(route, e.status, e.body);
      }
      const existing = api.changes.find((c) => c.title === body.title && c.repository_path === body.repository_path);
      const change = existing ?? makeChange(api.changes.length + 1, { title: body.title, intent: body.intent, repository_path: body.repository_path });
      if (!existing) api.changes.unshift(change);
      return json(route, 201, view(change));
    }
    const op = path.match(/^\/api\/v1\/changes\/([^/]+)\/(refresh|transition|cancel|verify|contract|passport|agents|outcomes|delegations|recovery|assurance\/facts|assurance\/plan|replay\/verify|evidence\/(?:baseline|current))$/);
    if (op) {
      const chg = api.changes.find((c) => c.id === decodeURIComponent(op[1]!));
      const name = op[2]!;
      if (!chg) return json(route, 404, envelope(404, "NOT_FOUND", "Change not found.").body);
      const method = req.method();
      const body = method === "GET" ? undefined : req.postData() ? req.postDataJSON() : undefined;
      if (method !== "GET") api.calls.push({ method, path: name, body });
      const rev = chg.revision ?? 1;
      const stale = () => (body?.expected_revision !== rev ? json(route, 409, envelope(409, "REVISION_CONFLICT", "The Change was modified by someone else.").body) : null);
      if (name === "refresh" || name === "verify") return json(route, 200, view(chg));
      if (name === "transition") { const r = stale(); if (r) return r; chg.lifecycle_state = body.target_state; chg.revision = rev + 1; return json(route, 200, view(chg)); }
      if (name === "cancel") { const r = stale(); if (r) return r; chg.lifecycle_state = "CANCELLED"; chg.revision = rev + 1; return json(route, 200, view(chg)); }
      if (name === "contract") { const r = stale(); if (r) return r; chg.contract = body.contract; chg.revision = rev + 1; return json(route, 200, view(chg)); }
      if (name.startsWith("evidence/")) return json(route, 200, { limitations: ["Git state only; file writes are not attributed."] });
      if (name === "passport") {
        if (method === "POST") api.passports[chg.id] = { id: "p1", change_id: chg.id, canonical_digest: "d".repeat(64), generated_at: NOW, lifecycle_state: chg.lifecycle_state, limitations: ["No replay verification."], outcomes: [], actor_ids: [], authority_summary: [], evidence: [], schema_version: 1 };
        return api.passports[chg.id] ? json(route, 200, api.passports[chg.id]) : json(route, 404, envelope(404, "NOT_FOUND", "No passport.").body);
      }
      if (["agents", "outcomes", "delegations"].includes(name)) { const items = api.lists[name]?.[chg.id] ?? []; return json(route, 200, { count: items.length, items }); }
      if (name === "recovery") return json(route, 404, envelope(404, "NOT_FOUND", "No recovery plan.").body);
      if (name === "assurance/facts") return json(route, 200, { required_evidence_complete: false, required_assurance_passed: false, assurance_fresh: false, deviations_resolved: true, reasons: ["No baseline checkpoint."] });
      if (name === "assurance/plan") return method === "POST" ? json(route, 200, { id: "plan-1", change_id: chg.id }) : json(route, 404, envelope(404, "NOT_FOUND", "No plan.").body);
      if (name === "replay/verify") return json(route, 200, { verified: true, checked_events: (api.events[chg.id] ?? []).length, first_break_seq: null });
    }
    const match = path.match(/^\/api\/v1\/changes\/([^/]+)(?:\/(evidence|events))?$/);
    if (match) {
      const change = api.changes.find((c) => c.id === decodeURIComponent(match[1]!));
      if (!change) {
        const e = envelope(404, "NOT_FOUND", "Change not found.");
        return json(route, e.status, e.body);
      }
      if (match[2] === "evidence") return json(route, 200, { baseline_captured: false, checkpoints: [], latest_checkpoint_fresh: null });
      if (match[2] === "events") {
        const all = (api.events[change.id] ?? []) as { seq: number }[];
        // Mirrors the real contract: since_seq is inclusive and must be >= 1; limit must be 1..10000.
        const since = Number(url.searchParams.get("since_seq") ?? 1);
        const limit = Number(url.searchParams.get("limit") ?? 1000);
        if (!(since >= 1) || !(limit >= 1 && limit <= 10000)) {
          return json(route, 422, envelope(422, "VALIDATION_ERROR", "The request did not match the API contract.").body);
        }
        const items = all.filter((e) => e.seq >= since).slice(0, limit);
        return json(route, 200, { count: items.length, items });
      }
      if (req.method() === "DELETE") { api.calls.push({ method: "DELETE", path, body: null }); api.changes = api.changes.filter((c) => c.id !== change.id); return route.fulfill({ status: 204, body: "" }); }
      return json(route, 200, view(change));
    }
    const toolMatch = path.match(/^\/api\/v1\/tools\/([^/]+)(\/trust)?$/);
    if (toolMatch) {
      const tool = (api.tools as { id: string }[]).find((t) => t.id === decodeURIComponent(toolMatch[1]!));
      if (!tool) return json(route, 404, envelope(404, "NOT_FOUND", "Tool not found.").body);
      if (req.method() === "GET") return json(route, 200, tool);
      const body = req.postDataJSON();
      api.calls.push({ method: "POST", path, body });
      return json(route, 200, { id: "td-1", tool_id: tool.id, decided_by_actor_id: body.actor_id, decision: body.decision, scope: body.scope, decided_at: NOW });
    }
    // Any other operation: record it and echo, so form tests can assert the exact request.
    const other = req.method();
    const echo = other !== "GET" && req.postData() ? req.postDataJSON() : {};
    if (other !== "GET") api.calls.push({ method: other, path, body: echo });
    if (other === "DELETE") { const id = path.split("/").pop(); api.changes = api.changes.filter((c) => c.id !== id); return route.fulfill({ status: 204, body: "" }); }
    return json(route, 200, { ok: true, path, ...echo });
  });
  return api;
}

export const makeEvent = (changeId: string, seq: number) => ({
  id: `evt-${changeId}-${seq}`,
  change_id: changeId,
  seq,
  occurred_at: NOW,
  event_type: seq === 1 ? "change.created" : "change.git_summary_refreshed",
  event_hash: seq.toString(16).padStart(64, "0"),
  payload: {},
  schema_version: 1,
});

export const makeTool = (i: number) => ({
  id: `tool-${i}`,
  name: `tool-${i}.exe`,
  version: `1.${i}.0`,
  publisher: i % 2 ? "Acme" : null,
  artifact_digest: i.toString(16).padStart(64, "a"),
  first_seen_at: NOW,
  last_seen_at: NOW,
  signature_state: "valid",
  trust_state: "OBSERVED",
  source: "test",
  capabilities: [],
});
