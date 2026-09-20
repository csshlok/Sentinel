# Desktop frontend: handoff for backend integration (SD / AC)

State: branch `frontend`, fast-forwarded (`git pull origin master --ff-only`) to upstream `f244184`, **uncommitted** (only `apps/` is new). Nothing pushed. Run/test/package instructions: `README.md`. Decisions and history: `FRONTEND_PLAN_ADDENDUM.md`.
The package in `release/win-unpacked` was rebuilt on `f244184` (bundled backend audited clean; launch, connect and clean shutdown verified).
Verified: `api:check`, typecheck, build; 93 unit tests (11 renderer, 82 Electron); Electron smoke (12 checks on the packaged app); **68 Playwright tests** (8 real-backend smoke, 15 resilience, 12 surface, 13 operation-form, 4 final (fork, close PR, declare tool, error details), 9 real-backend operation checks, 6 heavy) against the pulled backend.

## 1. What the UI can do today: every backend operation now has a screen

The UI reaches all 58 operations in the current `openapi.json`, including the new Change forking (`fork`, `forks`, lineage shown on Overview), `pulls/close` and `tools/declare`. Backend `error.details` (guard `missing_requirements`, field errors) are now shown in dialogs.

| Area | Screen | Tested against |
| --- | --- | --- |
| Home, Changes (paging, filter, create), Overview, Contract editing (409 handling), Evidence capture, Passport (build/export), Timeline (paged), Verify trace | Bespoke | Real backend (see below) + fake |
| Refresh, Run verification, Change state, Cancel, **Delete Change** | Bespoke dialogs | Real backend + fake |
| Fork Change / Forks, Close pull request, Declare tool, Actors, delegations (create/revoke), agent launch/attach/stop, assurance plan/run/evaluation, recovery preview/execute, GitHub connect/disconnect/status/grants/pull request/outcomes refresh, tool details and trust decision, git checkpoints/compare, environment, dependencies, tools seen, trace export | **Generic form dialog** driven by `src/features/ops/ops.ts` (required fields, number/JSON/list parsing, secrets as password fields, destructive warning, result view, JSON download) | Fake (13 form tests); requests confirmed accepted by the real backend for actors, delegations, evidence, contract, transition, cancel, delete, verify |
| Agents, Assurance, Authority, Delivery, Recovery lists | Generic record view (real values, credential-like fields redacted) | Fake |

"Generic" means the request forms are complete and validated, but result and list screens show labelled facts rather than tailored layouts. Replace them per area once AC/KB confirm the response schemas.

Not tested end to end because they need external setup: GitHub connect/PR (needs a real token and repo), agent launch (needs an installed adapter), recovery execute (needs a previewed plan and approval token), tool trust (needs an observed tool).

## 1a. Facts learned from running the mutations against the real backend

- `POST /transition` to ACTIVE returns **409 `TRANSITION_GUARD_FAILED`** with `details.missing_requirements: ["authority_valid"]` until a valid delegation exists. The dialog now shows the message and the missing requirements (`Missing: authority_valid`). SD: expose allowed next states and requirements up front (section 3, item 5).
- `GET /git/compare` requires `baseline_id` and `current_id` (checkpoint UUIDs). The UI asks for both.
- `POST /verify` with `git --version` returned **400** (policy/authority gate, not a shape error); AC/SD to confirm what authority a verification command needs.
- `GET /tools/{unknown}` returns 422 (id format), `GET /passport` before a build returns 404, `GET /dependencies` and `/recovery` return 404 when empty. The UI treats these as empty states.
- Contract update, evidence capture, refresh, passport build, actors, delegation create/revoke, cancel and delete all succeeded with the bodies the UI sends. Stale revisions return 409.

## 2. Integration-day checklist (run in this order)

1. Done locally: `frontend` was fast-forwarded to upstream and types regenerated (drift was additive: `fork`, `forks`, `pulls/close`, `tools/declare`, `forked_from_*`). SD: re-run `npm run api:generate && npm run typecheck` after any further backend change.
2. Start a real backend, run `npm run test:e2e` (needs port 8000 free) and `npm test`. `e2e/y-real-ops.spec.ts` already covers the operations above against the real backend; extend it for GitHub, agents, recovery and tool trust once their prerequisites exist.
3. `npm run package:dir`; launch `release/win-unpacked/Change Assurance.exe` with no Python on PATH; create a Change, transition it, edit its contract, build a passport.
4. Force-kill the app and relaunch: the stale backend must be reaped (see addendum section 2.7).

## 3. SD: needed for integration

1. **Ownership.** The plan gives `apps/desktop/**` to `[KB]` and says `[AC]` has no path there; upstream `AGENT_COORDINATION.md` still lists `frontend/` as unassigned and records no claim. Record who owns it (this work was built by the `AC:` contributor) before anything is committed.
2. **Gate 0 and OpenAPI freeze.** Plan 6.2 lists 10 readiness items; SD is still landing threat-model fixes upstream. Publish the frozen `openapi.json` hash so the UI can pin `OPENAPI_SHA256`.
3. **`GET /api/v1/system/backend-identity`** (plan 6.3): service name, API version, instance id. The desktop currently trusts "health + an authenticated call".
4. **Missing `git` returns an opaque 500** for `/repositories/validate` and `POST /changes`. Please return a clear 4xx with a stable code; the UI shows Git status in Settings but cannot explain the 500.
5. **Allowed transitions.** The state dialog lists every state and lets the backend reject. Please expose the allowed next states (in `ChangeView` or a small endpoint) so the UI only offers valid moves and can explain guards.
6. **List totals and cursors.** `count` is the page length, so the UI cannot show "N of M". A `total` (or `next_offset`) on list responses would fix it. Confirm `since_seq` (inclusive, min 1) and `limit` caps are intended and documented.
7. **Structured validation errors.** 422 details carry field locations; confirm they are stable so forms can attach messages to fields.
8. **Typed response schemas** for `AgentRun`, `Outcome`, `Delegation`, `RecoveryPlan`, `AssurancePlan`, `EnvironmentView` are in `openapi.json` but the UI shows them generically. Confirm them as stable so bespoke screens can replace `RecordView`.
9. **Product-copy sign-off** for the limitations text (no process tree, no file attribution, no general undo, trace not replay).
10. **Release:** signing identity, app icon and metadata, installer target (NSIS), update policy, and the final release decision (plan section 18).
11. CORS is no longer needed for development (Vite proxy). Allow `127.0.0.1:5173` only if you want direct browser calls.

## 4. AC: needed for integration

1. **List actors.** The API has `POST /actors` and `GET /actors/{id}` only. An Authority screen that creates delegations needs a list (or the Change's actor ids resolved to actors).
2. **GitHub connect flow.** Define what the UI collects (token paste vs device flow), what `providers/github/status` returns without secrets, and the grant lifecycle (`grants`, revoke). Then build Delivery: connect, grant, create PR, close PR, refresh outcomes.
3. **Recovery.** Confirm the preview → approve → execute contract (freshness binding, idempotency, "recovered" vs "post-recovery verified") so the UI can present preview and approval as separate actions.
4. **Passport exactness.** Confirm the exported JSON should be the server payload verbatim (the UI exports exactly what `GET /passport` returns) and whether replay verification is included.
5. **Tool trust.** `tools/{id}/trust` scopes (`exact_version`, `publisher_policy`), decision reasons, and the `tools/declare` semantics, so the Tools detail and trust dialog can be built.
6. **TUI parity.** Decide which flows must exist in both the terminal UI and the desktop app so copy and behaviour don't diverge.
7. `[KB]`-owned pieces the UI also waits on: agent adapter list and launch/attach/stop request shapes; assurance plan create/run/evaluate; checkpoint compare and environment/dependency views.

## 5. Frontend work still to do (my side)

Everything below is polish or blocked on a backend answer; no backend operation lacks a screen.

1. Bespoke result screens to replace the generic view: agent runs, assurance evaluation, delegations/actors, delivery/outcomes, recovery plan and approval, tool detail, forks (needs confirmed response schemas from AC/KB).
2. Pickers instead of pasted ids (actor, grant, checkpoint, tool) (needs list endpoints, e.g. list actors).
3. Show a fork's parent and children as a tree; "fork from checkpoint" from the checkpoints table (needs the fork response shape).
4. Offer only valid state moves (needs allowed next states from SD).
5. Installer (NSIS), signing, app icon and metadata, update policy.
6. React component tests, dark theme, native save dialog for exports. (`npm run test:electron:smoke` now exists: it launches the packaged app and checks load, backend, security posture and clean shutdown; run it after `npm run package:dir`.)
7. Real end-to-end runs that need external setup: GitHub connect/PR/close, agent launch, recovery execute, tool trust/declare.

## 6. Risks to know

- Generic forms send the field names in `ops.ts`; if a schema changes, that table (and `e2e/fake-api.ts`) must change with it.
- Verification runs an arbitrary command in the user's repository. The dialog warns, but the policy gate is the backend's, and it returned 400 for `git --version` in the real backend; confirm the authority it needs.
- The heavy scenario is a 60-second soak on one machine, in the browser renderer, not a long-duration test in the packaged window.
- Windows x64 only; Git must be installed; the package is about 400 MB (Electron dominates).
