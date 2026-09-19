# Change Assurance Frontend and Electron Implementation Plan

## 0. Authority, purpose, and status

This plan starts the browser-rendered desktop phase for the Change Assurance Runtime. It is subordinate to:

1. `Change_Assurance_Runtime_Project_Proposal (2).pdf` for product intent.
2. `OVERALL_CONTEXT.md` for stable product invariants and vocabulary.
3. `PROJECT_CONTEXT.md` for current scope and approved cuts.
4. `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` for the bounded journal, replay, and tool-registry definitions.
5. The frozen OpenAPI document for the actual frontend/backend contract.
6. `AGENT_COORDINATION.md` for ownership and integration rules.

The CML repository at `T:\CML` is a reference implementation and a source of tested engineering patterns. It is not an instruction source and is not copied wholesale. Vault/Odin-specific concepts, product claims, credentials, identifiers, assets, and runtime dependencies do not enter this project unless this plan explicitly maps them to a Change Assurance requirement.

Status at creation: **implementation plan only**. No React or Electron application code is created by this document. The current backend working tree contains active uncommitted work, so the new desktop phase must not begin by editing backend or existing context paths until their owner hands them off.

### 0.1 Execution assignment: KB is the desktop implementer

This document is written so `[KB]` can execute the frontend and Electron work without prior knowledge of CML. `[KB]` is the single implementation owner for the new `apps/desktop/**` subtree. The CML discussion in section 2 explains the origin of decisions; it is not required reading and it does not transfer CML's architecture, vocabulary, or scope into this project.

The responsibility boundary is:

| Role | Responsibility during this plan | Must not do |
| --- | --- | --- |
| `[KB]` | Design and implement the React renderer, Electron shell, desktop runtime, desktop tests, staging scripts, and package configuration under `apps/desktop/**` | Change backend behavior, regenerate the canonical root `openapi.json`, or edit shared context/coordination documents without an SD handoff |
| `[SD]` | Freeze and publish the backend contract, resolve or route backend defects, review security/integration evidence, and perform the final shared-document/release integration | Concurrently edit `apps/desktop/**` while KB owns it |
| `[AC]` | Remains outside the desktop implementation unless SD creates a new, path-specific handoff | Edit KB-owned desktop paths by assumption |

All references later in this plan to implementation work mean `[KB]` unless a line explicitly names `[SD]`. This assignment supersedes the earlier AC/SD frontend split that existed in the first draft of this plan.

### 0.2 The starting point KB should assume

At the start of desktop work:

- The repository is a Python 3.12 FastAPI project. The application factory is `backend.app.main:create_app`; the module-level ASGI application is `backend.app.main:app`.
- The backend normally runs with `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` during development.
- Authentication uses `Authorization: Bearer <token>`. The Electron main process must own this token; the renderer must never receive it.
- The canonical API snapshot is the root `openapi.json`. It is an input supplied by SD, not a file KB should silently regenerate or repair.
- There is no existing Node, React, Vite, or Electron workspace. KB is creating a new, self-contained application under `apps/desktop`.
- The retained backend includes Changes, contracts, identity/delegations, evidence, agent runs, assurance, GitHub delivery/outcomes, journal/replay, tool trust, recovery, and Passport.
- The removed proposal subsystems remain removed: filesystem observer, general process supervisor, internal agent-tool interception, and general undo. The bounded event journal and top-level tool registry are now retained and must be represented honestly.
- The existing Textual CLI/TUI is a separate interface. Do not delete it, rewrite it, or make the Electron application depend on it.

### 0.3 Rules KB follows on every task

1. Claim `apps/desktop/**` in `AGENT_COORDINATION.md` through SD before the first edit. Do not personally edit that shared file during an active integration window.
2. Read this plan, `OVERALL_CONTEXT.md`, `PROJECT_CONTEXT.md`, and the proposal PDF before implementation. Read the CML repository only when a task below names a specific reference file.
3. Work in small commits identified with `[KB]` and one task ID from section 15. Never combine unrelated backend fixes with desktop work.
4. Keep the Node project self-contained: `apps/desktop/package.json` and `apps/desktop/package-lock.json`. Do not create or modify a root `package.json` during KB implementation.
5. Do not hand-write API DTOs. Generate them from the SD-frozen root `openapi.json` into `apps/desktop/src/lib/api/generated/`.
6. Do not work around a false backend response in UI code. Record a minimal request/response reproduction and hand the defect to SD.
7. Finish each task with its specified automated tests and evidence before starting the next task.
8. If a required API is absent, a mutation is unsafe, or the live API differs from `openapi.json`, stop only that feature. Continue independent read-only or shell work.
9. Do not copy `T:\CML\apps\desktop\electron\main.cjs`, `AppShell.tsx`, or `backend.ts` wholesale. They are large product-specific files and are references only.
10. Any copied or substantially adapted MIT-licensed CML code must be listed in `apps/desktop/CML_REUSE.md` with source path, target path, adaptation, and notice status.

### 0.4 Required KB handoff format

For every completed task packet, KB must provide SD:

```text
Task: KB-<area>-<number>
Commit: <sha>
Paths changed: <exact paths>
Behavior implemented: <user-visible and internal behavior>
Commands run: <exact commands>
Results: <pass/fail totals>
Manual evidence: <screenshots/logs/fixture repository>
Contract used: <openapi hash or SD freeze identifier>
Known limitations: <truthful remaining gaps>
Backend defects found: <reproduction or "none">
CML code reused: <CML_REUSE.md rows or "none">
```

SD must be able to verify a handoff from this evidence without reconstructing KB's local reasoning.

## 1. Outcome

Deliver a Windows-first Electron desktop application whose renderer is also runnable in a browser during development. It must let a developer complete the retained Change Assurance workflow through the real authenticated API:

1. Start or connect to the local runtime.
2. Select and validate a Git repository.
3. Create a Change and edit its Change Contract.
4. Create actors and scoped delegations.
5. Capture baseline evidence.
6. Launch or attach a top-level agent.
7. Capture current evidence and inspect Git, environment, and dependency drift.
8. Plan, run, and evaluate assurance.
9. Connect GitHub, create or refresh a pull request, and inspect exact-SHA outcomes.
10. Inspect the event timeline and verify trace replay.
11. Review top-level tool manifests and make explicit trust decisions.
12. Preview and explicitly approve supported recovery.
13. Build, inspect, and export a Change Passport.

The application must preserve the product's honest limits: no process-tree visibility, no filesystem-level attribution, no general undo, no replay re-execution, no interception of an agent's internal tool calls, and no claims of sandboxing.

## 2. CML review scope and findings

### 2.1 Reference areas examined

The planning review covered the CML desktop architecture, route structure, desktop bridge, backend client, Odin project views, Vault onboarding/settings, UI audit/remediation records, security architecture, and packaging flow. The most relevant sources were:

- `T:\CML\apps\desktop\src\components\AppShell.tsx`
- `T:\CML\apps\desktop\src\components\WindowChrome.tsx`
- `T:\CML\apps\desktop\src\components\layout\WindowAware.tsx`
- `T:\CML\apps\desktop\src\components\product\Notifications.tsx`
- `T:\CML\apps\desktop\src\lib\backend.ts`
- `T:\CML\apps\desktop\src\lib\useVisiblePolling.ts`
- `T:\CML\apps\desktop\src\routes\onboarding.tsx`
- `T:\CML\apps\desktop\src\routes\_app.projects.tsx`
- `T:\CML\apps\desktop\src\routes\_app.projects.$projectId.tsx`
- `T:\CML\apps\desktop\src\components\ProjectFlowArtifact.tsx`
- `T:\CML\apps\desktop\src\components\ProjectGraphArtifact.tsx`
- `T:\CML\apps\desktop\src\routes\_app.settings.tsx`
- `T:\CML\apps\desktop\electron\main.cjs`
- `T:\CML\apps\desktop\electron\preload.cjs`
- `T:\CML\apps\desktop\electron\setup-state.cjs`
- `T:\CML\apps\desktop\electron\runtime-descriptor.cjs`
- `T:\CML\apps\desktop\electron\token-store.cjs`
- `T:\CML\apps\desktop\electron\window-controls.cjs`
- `T:\CML\scripts\packaging\package-windows.ps1`
- CML's packaging, migration, security, product-flow, and UI-audit documents under `T:\CML\docs`.

This was a deliberate architecture and behavior review, not a claim that every one of CML's roughly 73,000 tracked frontend/Electron/script lines should be transplanted. Backend evaluation scripts and product-specific Vault retrieval/model code are outside the reusable desktop foundation.

### 2.2 What CML proved useful

1. A local desktop product needs explicit startup, degraded, repair, and ready states; a blank renderer is not a startup strategy.
2. A frameless Windows shell requires tested window controls, sender-window scoping, draggable-region rules, and collision-safe page headers.
3. The backend child process needs authenticated readiness checks, identity verification, bounded startup waits, captured logs, graceful shutdown, and visible repair actions.
4. First-run/setup state must be durable, revisioned, atomically written, resumable, and able to quarantine corrupt state.
5. Renderer access to OS features belongs behind a narrow, typed preload bridge with `contextIsolation`, sandboxing, and no Node integration.
6. Polling must be visibility-aware, non-overlapping, abortable, and backed off after failures.
7. Long-lived collections require cursor or explicit pagination; loading a bounded first page and treating it as a total is incorrect.
8. One failed optional request must not blank an otherwise usable screen.
9. Destructive and security-sensitive actions need preview, consequence copy, typed or explicit confirmation, operation-specific pending state, and durable result reconciliation.
10. Packaged validation must use an isolated Electron `userData` directory, not merely overridden environment variables.
11. The package must verify its embedded helpers and ensure immutable program resources do not overlap writable runtime data.
12. Package success is not release proof; unpacked, installed, first-run, restart, migration, shortcut, log, and uninstall checks are distinct gates.
13. UI tests should assert behavior, geometry, accessibility, and state transitions rather than exact Tailwind strings or source-code fragments.

### 2.3 Adopt, adapt, and reject matrix

| CML pattern | Decision | Change Assurance use |
| --- | --- | --- |
| React, TypeScript, Vite | Adopt | Renderer foundation |
| TanStack Router | Adopt | Typed nested routes and route-level error boundaries |
| TanStack Query | Adopt | Server-state cache, invalidation, cancellation, and focused polling |
| Tailwind plus a small Radix-based primitive layer | Adapt | Use project-specific tokens and only required primitives |
| Lucide icon family | Adopt | Consistent code-native controls, with accessible labels |
| Frameless window and integrated chrome | Adopt | Windows desktop shell with safe-zone-aware headers |
| Sandboxed preload bridge | Adopt | Repository picker, save/export, reveal path, window controls, diagnostics |
| Durable setup-state file | Adapt | Much smaller setup state: runtime readiness, first-run completion, optional GitHub status, tour version |
| Startup and repair HTML surfaces | Adopt | Render before React/backend readiness and survive renderer failure |
| Backend child-process logging | Adopt | Desktop log plus backend stdout/stderr in `userData/logs` |
| Helper integrity manifest and package-layout audit | Adopt | Verify portable Python and backend payload before launch |
| Workspace-local Electron Builder temp/output directories | Adopt | Avoid system-drive and concurrent staging failures |
| Isolated-profile packaged smoke tests | Adopt | Prevent tests from consuming a developer's real Change database |
| Visible, non-overlapping polling | Adopt | Agent status, outcomes, health, and long-running operations |
| Odin project list/workspace hierarchy | Adapt | Changes list and evidence-centered Change workspace |
| Odin Flow evidence inspector | Adapt | Timeline event/effect inspector and assurance evidence detail |
| Vault's broad 11-item navigation | Reject | Use four primary destinations plus contextual Change sections |
| One 3,000+ line API module | Reject | Generate contract types and split transport from feature query modules |
| One 2,000+ line Electron main file | Reject | Split lifecycle, backend runtime, IPC, logging, protocol, and packaging concerns |
| Raw backend token exposed to renderer | Reject | Main process injects authorization through a constrained API proxy |
| Variable-port packaged renderer HTTP server | Reject | Use a stable secure custom application protocol for packaged assets |
| TanStack Start/SSR and Cloudflare build plugins | Reject | The product is a local SPA; SSR and Cloudflare add no user value |
| Vault model, OCR, Playwright-browser, tunnel, MCP, and vector runtimes | Reject | None is needed for Change Assurance desktop delivery |
| Vault storage move/deletion machinery | Reject | Repository paths are selected evidence targets, not app-owned data roots |
| Project graph canvas as a default dashboard | Reject | Change Assurance needs a lifecycle/evidence workbench, not a decorative graph |

### 2.4 Reuse and license rule

The inspected CML repository is MIT-licensed. Architectural ideas may be reimplemented freely. If substantial CML code is copied or adapted instead of independently rewritten, preserve the required copyright and MIT permission notice in the distributed source/package notices and record the exact source/target mapping in KB-FE-00. CML branding and product assets remain excluded even when code reuse is legally permitted.

### 2.5 CML lookup guide for a developer unfamiliar with CML

KB does not need to survey CML. Consult only the following source when implementing the named target, then return to this plan:

| CML reference | Target in this project | Learn or adapt | Explicitly discard |
| --- | --- | --- | --- |
| `apps/desktop/electron/window-controls.cjs` | `electron/window-controls.cjs` | sender-window scoping; minimize/maximize/restore/close behavior | CML channel names and branding |
| `apps/desktop/electron/preload.cjs` | `electron/preload.cjs` | frozen narrow API and structured IPC failures | token exposure and unrelated Vault methods |
| `apps/desktop/electron/setup-state.cjs` | `electron/startup-state.cjs` | versioned atomic JSON, validation, corrupt-file quarantine | Vault setup steps and model/runtime fields |
| `apps/desktop/electron/runtime-descriptor.cjs` | `electron/runtime-descriptor.cjs` | identity-bound runtime descriptor and stale-process checks | CML ports, service identity, paths |
| `apps/desktop/electron/main.cjs` | all split `electron/*.cjs` modules | lifecycle ordering, secure window flags, child logging, shutdown sequence | the file structure itself, raw-token bridge, embedded renderer server, unrelated IPC |
| `apps/desktop/src/lib/useVisiblePolling.ts` | `src/lib/state/useVisiblePolling.ts` | pause while hidden, no overlapping request, abort, backoff | feature-specific queries |
| `apps/desktop/src/components/product/Notifications.tsx` | `src/components/product/OperationNotice.tsx` | live-region semantics and operation feedback | CML styling and copy |
| `apps/desktop/src/components/layout/WindowAware.tsx` | `src/components/layout/WindowAware.tsx` | desktop-titlebar safe zone | CML layout assumptions |
| `scripts/packaging/package-windows.ps1` | `apps/desktop/scripts/packaging/*` | isolated staging, deterministic paths, audit-before-package | CML runtime payloads and root-workspace assumptions |
| CML packaging investigation docs | package verification checklist | installed/unpacked/isolated-profile distinctions | historical CML incidents as product requirements |

Before adapting code, create the corresponding row in `apps/desktop/CML_REUSE.md`. If KB can implement the behavior cleanly from this specification, independent implementation is preferred and the row may say “concept only; no copied code.”

Required `CML_REUSE.md` columns are: source commit, source path, target path, copied/adapted/concept-only, behavioral reason, removed assumptions, license notice location, and reviewer.

## 3. Product and design direction

### 3.1 Interface character

The application should inherit CML/Vault's useful temperament—calm, precise, local-first, and evidence-centered—without cloning Vault branding or page structure. The Change Assurance identity should feel like an engineering control room: restrained, readable, and explicit about risk and uncertainty.

Design rules:

- Use one clear primary action per state.
- Prefer rails, lists, timelines, tables, and inspectors over generic card grids.
- Use color plus an icon and text for every status.
- Keep evidence and limitations adjacent to the claim they qualify.
- Do not show fabricated metrics, placeholder success, or fake live activity.
- Preserve readable content at 1024x680 and at a 200% effective zoom width.
- Respect `prefers-reduced-motion`.
- Keep keyboard access, focus transfer, and accessible names mandatory.
- Treat long repository paths, branch names, error messages, and command lines as normal data.

### 3.2 Design-spec gate

Before renderer implementation, create and approve visual concepts for these complete states:

1. Changes home with empty and populated variants.
2. Change workspace overview at 1280x820.
3. Evidence/assurance workspace with table and inspector.
4. Timeline/replay workspace with chain status and event detail.
5. Tool trust list/detail and decision confirmation.
6. Recovery preview/approval confirmation.
7. First-run/runtime repair screen.
8. Narrow/200%-zoom workspace behavior.

The approved concept becomes a design contract. Extract tokens, typography, component variants, icon inventory, spacing, responsive rules, and visible copy before coding. Browser screenshots must later be compared directly with the accepted concepts.

## 4. Target application architecture

```text
Electron main process
  -> stable app:// renderer protocol
  -> BackendRuntimeSupervisor
       -> bundled portable Python
       -> uvicorn on 127.0.0.1:<ephemeral-port>
       -> SQLite under Electron userData/state
  -> authenticated BackendApiProxy (token remains in main process)
  -> allowlisted native IPC (dialogs, export, reveal, logs, window controls)
  -> startup/repair renderer available without backend

Sandboxed preload
  -> window.changeAssuranceDesktop
       -> api.request(...)
       -> repositories.selectFolder()
       -> files.saveExport(...)
       -> shell.revealPath(...)
       -> diagnostics.openLogs()
       -> windowControls.*

React renderer
  -> TanStack Router
  -> TanStack Query
  -> generated OpenAPI types
  -> feature-scoped query/mutation modules
  -> reusable status/evidence/action primitives
```

The Electron shell owns only its own backend child process. This must never be described as the proposal's removed process supervisor: it does not observe, attribute, or clean up agent descendant processes.

## 5. Repository layout

Create the desktop application as a self-contained project rather than placing renderer files in the Python package or changing shared root package files:

```text
apps/
  desktop/
    package.json
    package-lock.json
    tsconfig.json
    vite.config.ts
    playwright.config.ts
    vitest.config.ts
    electron-builder.yml
    CML_REUSE.md
    src/
      app/
      components/
        layout/
        product/
        ui/
      features/
        changes/
        contract/
        identity/
        evidence/
        agents/
        assurance/
        delivery/
        timeline/
        tools/
        recovery/
        passport/
        settings/
      lib/
        api/
        state/
        formatting/
      routes/
      styles/
      types/
    electron/
      main.cjs
      preload.cjs
      backend-runtime.cjs
      api-proxy.cjs
      app-protocol.cjs
      startup-state.cjs
      runtime-descriptor.cjs
      logging.cjs
      window-controls.cjs
      native-dialogs.cjs
      ipc-errors.cjs
      startup.html
      repair.html
      tests/
    e2e/
    build/
    scripts/
      api/
      packaging/
    test-results/
```

Ownership must be frozen before code starts:

- `[KB]`: all files under `apps/desktop/**`, including renderer, Electron, local scripts, package lock, tests, and documentation specific to that subtree.
- `[SD]`: root `openapi.json`, backend fixes, cross-system acceptance, shared context documents, and final integration/release decision.
- `[AC]`: no path in this plan unless SD records a later, non-overlapping reassignment.

This assignment becomes active only after SD records it in `AGENT_COORDINATION.md`. Keeping the Node lockfile and packaging scripts inside `apps/desktop` lets KB implement independently without colliding with root or backend owners.

### 5.1 Exact bootstrap procedure

KB performs the following from the repository root after the ownership claim is recorded:

```powershell
New-Item -ItemType Directory -Force apps/desktop | Out-Null
Set-Location apps/desktop
npm init -y
npm install react react-dom @tanstack/react-query @tanstack/react-router lucide-react clsx tailwind-merge class-variance-authority
npm install @radix-ui/react-alert-dialog @radix-ui/react-dialog @radix-ui/react-popover @radix-ui/react-progress @radix-ui/react-select @radix-ui/react-switch
npm install -D electron electron-builder vite typescript @vitejs/plugin-react tailwindcss @tailwindcss/vite
npm install -D vitest @vitest/coverage-v8 jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw
npm install -D @playwright/test openapi-typescript eslint prettier
```

Commit the resulting exact versions and `package-lock.json`; never depend on floating global packages. Before accepting the bootstrap commit, KB must inspect `npm audit --omit=dev`, document unresolved runtime findings, and ensure `npm ci` works from a clean clone.

The package scripts must expose these stable commands:

```json
{
  "scripts": {
    "dev": "vite",
    "dev:electron": "electron electron/main.cjs",
    "api:generate": "node scripts/api/generate.mjs",
    "api:check": "node scripts/api/check.mjs",
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "build:renderer": "vite build",
    "build": "npm run api:check && npm run typecheck && npm run test && npm run build:renderer",
    "package:dir": "electron-builder --dir",
    "package:win": "electron-builder --win nsis",
    "verify:package": "node scripts/packaging/verify-package.mjs"
  }
}
```

KB may refine commands as implementation requires, but the semantic entry points and clean-clone behavior must remain.

## 6. Contract and backend readiness gate

### 6.1 Frozen contract requirements

The frontend consumes generated TypeScript types from `openapi.json`. It must not manually duplicate 100 Pydantic schemas. Add a deterministic generation/check command and fail CI when generated types differ from the committed OpenAPI snapshot.

Required contract behavior:

- Stable bearer authentication.
- Stable `{error: {code, message, details}}` parsing.
- Idempotency keys on every mutation that supports replay safety.
- Optimistic concurrency revisions on Change/Contract mutations.
- Pagination metadata for collections that can grow indefinitely, especially events, outcomes, runs, and tools.
- Explicit missing, partial, stale, denied, unsupported, and unavailable states.
- A desktop runtime identity response that cannot be confused with another loopback service.
- No secret, raw environment value, provider token, or credential location in any response.

### 6.2 Backend correctness prerequisites

The previous independent review found cross-module defects that can make a polished UI confidently display the wrong state. Gate 0 must re-run and close or explicitly defer each finding before enabling the related mutation in the desktop app:

1. Committed changes must remain visible to Change comparison, dependency analysis, and deviation checks.
2. Legacy verification must not bypass authority/environment isolation.
3. Delegation use limits must be consumed atomically and idempotently.
4. Tool drift must never turn a later explicit denial into a launchable provisional state.
5. CI gating must use the latest applicable exact-SHA outcome, not any historical pass.
6. Recovery must bind approval to a fresh plan/current HEAD and remain idempotent.
7. Domain mutation and journal emission must satisfy the documented transaction boundary.
8. Persisted credential grants must remain usable or truthfully invalid after restart.
9. `openapi.json` must match the live app.
10. Capability reporting must describe journal, replay, and tool registry consistently with their actual routes.

Read-only renderer scaffolding can proceed while these are fixed. The desktop UI must not expose affected privileged actions as production-ready before their acceptance tests pass.

### 6.3 Desktop-specific backend additions

Keep additions minimal:

- `GET /api/v1/system/backend-identity`: service name, API version, instance ID, schema version, and capability digest. Do not expose secrets or unnecessary local paths.
- Optionally extend health with migration/readiness state if identity cannot carry it cleanly.
- Add pagination only where the current API can exceed its bounded response contract.
- Add export content-disposition metadata only if the renderer cannot name Passport/replay exports deterministically.

Do not add UI-shaped aggregation endpoints until measurement shows that several independent calls prevent a usable screen. When aggregation is justified, its response must still use the canonical domain models.

### 6.4 API-to-feature implementation map for KB

This table is the initial routing map. Generated operation types remain authoritative if names or shapes differ. KB must not infer an endpoint that is not present in the frozen contract.

| Desktop feature module | Backend operations it owns |
| --- | --- |
| `lib/api/system.ts` | `GET /api/v1/health`, `GET /api/v1/capabilities`, and the proposed backend-identity operation once SD supplies it |
| `features/changes/api.ts` | list/create/get/delete Change, refresh, verify, cancel, transition, and contract update |
| `features/changes/repository-api.ts` | `POST /api/v1/repositories/validate` |
| `features/identity/api.ts` | create/get actors; create/get/revoke delegations; list Change delegations |
| `features/evidence/api.ts` | get evidence; capture baseline/current; Git checkpoints/compare; environment; dependencies |
| `features/agents/api.ts` | list adapters and Change runs; launch, attach, and stop a run |
| `features/assurance/api.ts` | facts; get/create plan; run plan; get evaluation |
| `features/delivery/api.ts` | GitHub connect/disconnect/status; grant/revoke; create pull; list/refresh outcomes |
| `features/timeline/api.ts` | Change events; replay; replay verify; replay export |
| `features/tools/api.ts` | global tool list/detail/trust and Change-scoped tool observations |
| `features/recovery/api.ts` | get recovery status; preview; execute an approved plan |
| `features/passport/api.ts` | get latest Passport and build a new Passport |

Every feature API module has the same four-layer shape:

1. Generated request/response types from `src/lib/api/generated/schema.ts`.
2. A transport call through `src/lib/api/client.ts`; no feature calls `fetch` directly.
3. Query-key factories in `queries.ts` and mutations in `mutations.ts`.
4. Components that consume hooks and render explicit loading/empty/error/partial states.

### 6.5 Generated-contract procedure

`scripts/api/generate.mjs` must resolve the root snapshot with a path relative to the script, never the caller's current directory. It generates to a temporary file, normalizes deterministic output, and atomically replaces `src/lib/api/generated/schema.ts`. `scripts/api/check.mjs` generates to a temporary file and exits nonzero when the committed generated file differs.

KB records the SHA-256 of root `openapi.json` in `src/lib/api/generated/OPENAPI_SHA256`. A changed hash requires a separate generated-contract commit and a review of renamed/removed operations before feature code is changed. Tests must include one representative successful payload and the standard error envelope from the same frozen snapshot.

### 6.6 Stop and escalation conditions

KB stops the affected feature and sends SD a reproduction when any of these occurs:

- live status, body, or field shape differs from the frozen OpenAPI document;
- a mutation lacks the authority, revision, approval, or idempotency value required by the backend model;
- an endpoint returns a secret, raw environment value, provider credential, or unrestricted local path;
- the UI would need to claim descendant-process control, filesystem attribution, replay execution, or general undo;
- a collection can truncate but supplies no paging/completeness signal;
- the renderer would need the bearer token to complete the design;
- a backend bug would have to be hidden by optimistic UI state.

The escalation contains method, path, sanitized request, status, sanitized response, expected contract, exact backend revision, and the smallest reproduction. KB continues work on independent features while SD resolves it.

## 7. Information architecture and routes

### 7.1 Primary navigation

Use four primary destinations:

1. **Changes** — default home, creation, repository selection, current status.
2. **Activity** — cross-Change journal events and active operations only if a real API supports it; otherwise omit rather than simulate.
3. **Tools** — top-level tool inventory, signature/trust state, and observations.
4. **Settings** — runtime health, GitHub connection, appearance/accessibility, diagnostics, and advanced limits.

Global command palette actions: open Change, create Change, capture evidence, open Tools, open Settings, and show keyboard shortcuts. Commands unavailable in the current state must explain why.

### 7.2 Route map

```text
/
  -> /changes
/onboarding
/repair
/changes
/changes/new
/changes/:changeId
  /overview
  /contract
  /authority
  /agent
  /evidence
  /assurance
  /delivery
  /timeline
  /recovery
  /passport
/tools
/tools/:toolId
/settings
  ?section=runtime|github|appearance|diagnostics|advanced
```

Selected Change and selected inspector item belong in route/search state when that state should survive reload or deep linking. Ephemeral dialog visibility and draft input remain local.

### 7.3 Screen contracts

#### Changes home

- Repository-aware create action using an Electron folder picker or validated manual path in browser development.
- List rows show title, lifecycle state, repository name, branch/HEAD when available, evidence freshness, blocking finding count, and next required action.
- Empty state explains the first real workflow; no demo metrics.
- Pagination or incremental loading; never infer totals from a bounded page.
- Per-row operations use independent pending states.

#### Change overview

- Header: Change title, repository, lifecycle state, risk, refresh time.
- Lifecycle rail: achieved, current, available-next, blocked, and unsupported stages.
- “Next action” section derived from current backend facts, not hardcoded workflow guesses.
- Compact summaries for authority, latest checkpoint, assurance, PR/CI, replay integrity, tool risk, and recovery.
- Limitations panel always visible when evidence is partial or a cut prevents a claim.

#### Contract

- Revision-aware form for allowed/forbidden paths, expected outcomes, required checks, authority ceiling, and maximum risk.
- Dirty draft is never overwritten by polling.
- Conflict response offers reload/compare; it does not silently discard edits.
- Pattern examples are explanatory, not implied validation results.

#### Authority

- Actor list and actor creation.
- Delegation list showing grantor, grantee, scopes, expiry, revocation, use limit, and uses.
- Creation form with human-readable scopes and raw scope disclosure.
- Revoke confirmation names the actor and affected Change.
- Expired/exhausted/revoked states are distinct.

#### Agent

- Adapter availability from the API.
- Launch and attach are separate explicit flows.
- Show top-level command, status, timestamps, bounded output summary, limitations, and linked observed tool.
- Stop is shown only when backend state says it is meaningful.
- Never imply descendant processes were stopped or observed.

#### Evidence

- Baseline/current checkpoint actions and comparison summary.
- Git changed-path table with status, additions/deletions, truncation and untracked limitations.
- Environment drift grouped as added/removed/changed/unknown without raw secrets.
- Dependency changes with ecosystem, version movement, source, confidence, and risk notes.
- Master/detail inspector modeled after Odin Flow: selected fact on the right, source evidence and limitations adjacent.
- A committed-change regression fixture is mandatory.

#### Assurance

- Plan rationale, required/optional checks, coverage gaps, and checkpoint identity.
- Running state per check rather than a single global spinner.
- Results show status, duration, bounded output, truncation, and freshness.
- Evaluation separates “checks passed,” “evidence complete,” “fresh,” and “deviations resolved.”
- Passing tests must never be labeled proof of correctness.

#### Delivery

- GitHub disconnected state with one explicit connect action.
- Credential grants shown as scope/expiry metadata only.
- PR creation preview before mutation.
- Outcomes bound visibly to repository and exact head SHA.
- Newer pending/failing outcomes supersede older success in presentation.
- Provider errors remain recoverable without blanking local evidence.

#### Timeline and replay

- Ordered event rail with sequence, time, event type, subject, actor when present, and bounded payload summary.
- Event detail inspector lists associated effects and restoration class.
- Chain verification status is visible and independently refreshable.
- Broken chain identifies the first break sequence.
- Copy states: “trace verified” rather than “system replayed” or “change proven.”
- Limitations always state no re-execution, no process tree, and no filesystem write timeline.

#### Tools

- List top-level executable/declared manifest name, version, publisher, digest short form, signature state, trust state, last seen, and observed Changes.
- Detail page shows the full manifest, capability claims, decision history, drift, and observations.
- Approve/deny confirmation includes exact scope (`exact_version` or `publisher_policy`), actor, reason, and affected Change when applicable.
- A denial remains visually and behaviorally dominant until an explicit later decision changes it.
- Explain that internal agent tool/MCP calls are not intercepted.

#### Recovery

- Preview first; execution never shares the preview button.
- Display source checkpoint, planned branch, actions, unsupported effects, conflicts, and freshness.
- Require actor selection and an explicit approval confirmation bound to the displayed plan.
- On execute, reconcile from the server before showing a terminal state.
- Repeated submission must return the existing result rather than change outcome.
- “Recovered” and “post-recovery verified” are separate states.

#### Passport

- Build and retrieve are separate actions.
- Show intent, lifecycle, actors, authority, evidence references, outcomes, recovery, tool trust, replay verification, digest, and limitations.
- Export uses a native save dialog in Electron and browser download in web development.
- Exported JSON is exactly the server payload, not a renderer reconstruction.

#### Settings

- Runtime: backend version/identity, port, database readiness, logs, restart action.
- GitHub: connection status and disconnect confirmation; never display token material.
- Appearance/accessibility: theme, density, reduced motion preference where applicable.
- Diagnostics: open logs, copy safe diagnostic summary, API/capability versions.
- Advanced: only real tunables; no implementation-shaped clutter.
- Destructive operations belong in a separated Danger Zone.

## 8. Renderer data and state architecture

### 8.1 Generated contracts

- Generate `src/lib/api/generated/schema.ts` from the SD-frozen root `openapi.json`.
- Commit generated output for reproducible builds.
- Add `npm run api:check` to regenerate in a temporary target and diff.
- Wrap generated operations in small feature modules; do not create another monolithic `backend.ts`.
- Normalize stable API errors into `ChangeAssuranceRequestError` with code, status, details, retry safety, and optional field issues.

### 8.2 Transport boundary

Define one transport interface:

```text
request<T>({ method, path, body, headers, timeout, signal }): Promise<T>
```

- Electron implementation invokes the main-process API proxy; the bearer token never enters renderer JavaScript.
- Browser-development implementation fetches the configured loopback API and reads a development-only token supplied explicitly by the developer.
- Both implementations enforce loopback HTTP, bounded timeout, JSON size limits, safe error parsing, and abort semantics.
- Mutation timeouts warn that the action may have completed and require status reconciliation before retry.

### 8.3 Query ownership

Use feature query-key factories:

- `changes.*`
- `identity.*`
- `evidence.*`
- `assurance.*`
- `delivery.*`
- `journal.*`
- `tools.*`
- `recovery.*`
- `passport.*`
- `runtime.*`

Mutations invalidate only affected keys. Broad “reload everything” behavior is prohibited. Optional panels load independently so one failure does not block primary content.

### 8.4 Refresh and polling rules

- Health: 8 seconds online, exponential backoff offline, 4x slower while hidden.
- Active agent/check/recovery: poll only while state is nonterminal.
- Outcomes: user refresh plus a conservative poll while Delivery is visible.
- Static contract/evidence/passport data: no background polling.
- Abort prior request on route/key change.
- Reject stale responses using query keys or a request generation guard.
- Never overwrite a dirty form draft from polling.

### 8.5 Mutation safety

- Generate one idempotency key per user intent and retain it across transport retry.
- Do not reuse a key for changed request bodies.
- Disable only the operation being submitted.
- After ambiguous timeout, query status before offering retry.
- Use optimistic UI only for reversible local presentation state, never lifecycle, authority, trust, provider, or recovery state.

## 9. Electron shell design

### 9.1 BrowserWindow baseline

- Default 1280x820, minimum 1024x680.
- Frameless with app-integrated 32px chrome.
- `contextIsolation: true`.
- `nodeIntegration: false`.
- `sandbox: true`.
- `webSecurity: true`.
- Hidden until startup or repair surface is ready.
- Deny popup creation and arbitrary navigation.
- Permit external opening only for allowlisted HTTPS URLs.

### 9.2 Stable packaged renderer origin

Register a secure, standard custom scheme such as `change-assurance://app`. Serve only files under the packaged renderer directory using normalized, containment-checked paths. Fall back to `index.html` for router paths. Add a strict CSP.

Development continues through Vite at `127.0.0.1`; packaged state must not depend on a random renderer port. This directly avoids a problem CML identified with browser storage tied to variable ports.

### 9.3 Backend runtime supervisor

Responsibilities:

1. Resolve development or packaged Python/backend paths.
2. Allocate a loopback port from a bounded range.
3. Create or load the desktop API token securely in the main process.
4. Set `CHANGE_ASSURANCE_DB_PATH` under `userData/state`.
5. Set `CHANGE_ASSURANCE_API_TOKEN` only in the child environment.
6. Spawn `python -s -m uvicorn backend.app.main:app --host 127.0.0.1 --port <port>` with `shell: false`, hidden window, and piped logs.
7. Poll authenticated health and identity with a bounded cold-start timeout.
8. Verify service/API identity before accepting readiness.
9. Publish a safe runtime descriptor without the token.
10. On quit/restart, request graceful exit, wait, then terminate only the exact owned backend child if needed.

It must not search for or terminate unrelated Python processes.

### 9.4 Preload API

Expose only namespaced operations:

- `api.request`
- `runtime.getStatus`, `runtime.restart`, `runtime.openLogs`
- `repositories.selectFolder`, `repositories.reveal`
- `exports.saveJson`
- `shell.openExternal`
- `windowControls.getState/minimize/toggleMaximize/close/onStateChanged`
- `startup.getState/updateState/reset`

Validate every argument in the main process. No arbitrary filesystem read/write, command execution, environment access, raw token retrieval, or generic IPC channel is exposed.

### 9.5 Startup and repair state machine

```text
starting_shell
  -> verifying_package
  -> starting_backend
  -> verifying_backend_identity
  -> loading_renderer
  -> ready

Any pre-ready state -> repair_required
repair_required -> retry | open_logs | reset_desktop_setup
ready -> restarting_backend -> verifying_backend_identity -> ready|repair_required
```

Startup HTML must display real phase and elapsed time. Repair UI must show safe errors, log locations, retry, and exit. It must not offer destructive database reset as a casual repair action.

### 9.6 Desktop setup state

Persist a small revisioned JSON document with atomic temporary-write-and-rename behavior:

- schema version and revision;
- setup phase;
- onboarding completion;
- last selected Change ID (presentation preference only);
- theme/density preference;
- tour version/status;
- last safe runtime diagnostic code.

Do not duplicate canonical backend entities, GitHub credentials, Change state, or repository evidence in desktop setup state.

### 9.7 File-by-file Electron contract

KB implements the Electron layer as small CommonJS modules because Electron loads the main/preload entry points directly. Each module has one purpose and can be unit-tested without launching the entire app.

| File | Required exports/behavior | Direct tests |
| --- | --- | --- |
| `electron/main.cjs` | compose modules, register scheme before ready, create startup/main window, sequence startup, own shutdown | startup success, startup failure, second-instance focus, orderly quit with fakes |
| `electron/backend-runtime.cjs` | `start`, `getStatus`, `restart`, `stop`; exact-child ownership; authenticated readiness/identity; bounded logs | ready, timeout, early exit, wrong identity, restart, graceful/forced stop |
| `electron/api-proxy.cjs` | accept allowlisted API request object, inject token, enforce loopback base, timeout, body limit, sanitize errors | valid GET/POST, forbidden URL/header, timeout, invalid JSON, oversized response, token redaction |
| `electron/app-protocol.cjs` | register secure scheme; normalize and containment-check asset paths; SPA fallback | root, nested route, asset, traversal denial, missing file |
| `electron/preload.cjs` | expose frozen `changeAssuranceDesktop`; invoke named channels only | public shape snapshot and absence of Node/token/generic invoke |
| `electron/ipc-errors.cjs` | convert internal errors into stable safe code/message/details | secret/path redaction and unknown-error fallback |
| `electron/window-controls.cjs` | act on `event.sender`'s owning window; publish maximize state | each control, missing/destroyed sender, state events |
| `electron/native-dialogs.cjs` | folder picker, reveal selected path, save exact JSON, open logs; validate arguments | cancel/success, invalid path/type, exact saved bytes |
| `electron/startup-state.cjs` | versioned validation, atomic update, migration, quarantine corrupt data | create/read/update, concurrent revision failure, corrupt file, migration |
| `electron/runtime-descriptor.cjs` | store only safe pid/port/instance/start metadata; reject stale/mismatched descriptor | live match, stale PID, wrong identity, malformed file |
| `electron/logging.cjs` | rotating safe desktop/backend logs under `userData/logs` | rotation, redaction, write failure does not crash app |
| `electron/startup.html` | dependency-free phase UI that appears before React | DOM smoke and copy review |
| `electron/repair.html` | dependency-free error/retry/log/exit UI | action wiring, keyboard access, safe diagnostics |

`main.cjs` must remain orchestration code. If it exceeds roughly 350 lines or contains transport, path-normalization, JSON-store, or packaging logic, move that logic into the responsible module before continuing.

### 9.8 File-by-file renderer contract

The renderer starts with these foundation files before feature screens:

| File | Responsibility |
| --- | --- |
| `src/main.tsx` | mount React, query provider, router provider, error boundary |
| `src/app/router.tsx` | route tree and not-found/error routes; no data access implementation |
| `src/app/query-client.ts` | query defaults, retry policy, mutation error routing |
| `src/app/DesktopContext.tsx` | typed access to bridge plus browser-development substitute |
| `src/lib/api/client.ts` | transport-neutral request interface and normalized errors |
| `src/lib/api/electron-transport.ts` | bridge-backed requests only |
| `src/lib/api/browser-transport.ts` | development-only loopback fetch with explicit token entry |
| `src/lib/api/errors.ts` | `ChangeAssuranceRequestError`, retry classification, field issues |
| `src/lib/state/useVisiblePolling.ts` | visibility-aware abortable non-overlapping polling |
| `src/styles/tokens.css` | approved color, typography, spacing, radius, focus, motion tokens |
| `src/components/layout/AppShell.tsx` | window chrome, primary navigation, route outlet, global notices |
| `src/components/layout/ChangeWorkspace.tsx` | Change header, lifecycle rail, contextual section navigation |
| `src/components/product/*` | status, evidence, operation, boundary, path, confirmation primitives |

Each feature directory then contains `api.ts`, `queries.ts`, `mutations.ts` where applicable, `components/`, route-facing `screens/`, fixtures, and colocated tests. Route files should compose screens and validate parameters; they should not accumulate domain logic.

### 9.9 First real vertical slice, in exact order

KB proves the architecture before broad screen work:

1. Bootstrap the renderer and show a static app shell in browser development.
2. Generate types from the frozen API and make `api:check` pass.
3. Implement browser transport and display real health/capabilities.
4. Implement the secure BrowserWindow, preload, API proxy, and development backend launch.
5. Display the same real health/capabilities through Electron without exposing the token.
6. Implement Changes list with empty/loading/error/populated states.
7. Implement repository folder selection, validation, and Change creation.
8. Open the created Change overview using `GET /changes/{id}`.
9. Close and restart the entire Electron app; confirm the Change persists and reopens from canonical backend state.
10. Force a backend startup failure; confirm repair UI appears and retry recovers.

Do not begin assurance, GitHub, recovery, or packaging work until this slice passes unit, component, and Playwright tests. This is the architecture proof that prevents later features from building on mocked assumptions.

## 10. Security model

### 10.1 Trust boundaries

- Renderer is untrusted relative to the main process.
- Main process owns API credentials and native capabilities.
- Backend owns domain authorization and must not trust renderer presentation state.
- Selected repositories are user data and are never copied into application resources.
- Exported Passport/replay bundles are user-selected outputs.

### 10.2 Mandatory controls

- Strict CSP with no remote scripts and no unsafe eval in production.
- No raw HTML insertion unless audited and sanitized; prefer React text rendering.
- IPC sender validation and explicit channel registration.
- Loopback URL validation including protocol, hostname, path, credentials, and port.
- Bounded IPC request/response sizes.
- Redaction in desktop/backend logs.
- Safe messages in renderer; diagnostics separated from user copy.
- `safeStorage` for any persisted desktop secret; memory-only fallback when unavailable.
- Package helper hashes verified before backend launch.
- No auto-update implementation until signing, migration, rollback, and update policy are explicitly designed.

### 10.3 Product-copy constraints

Never use these unqualified claims:

- “All processes stopped.”
- “Every file change tracked.”
- “Fully reversible.”
- “Replay reproduced the run.”
- “Tool calls are controlled.”
- “Verified correct.”

Use observable language: “top-level run stopped,” “Git checkpoint changed,” “trace chain verified,” “required checks passed for this checkpoint,” and “this top-level executable is denied.”

## 11. Windows packaging

### 11.1 Package contents

- Electron shell and built renderer.
- Backend Python package.
- Portable 64-bit Python runtime with locked production dependencies.
- Helper integrity manifest.
- App icon, installer/uninstaller icon, startup/repair assets.
- Uninstall helper that stops only executables whose resolved paths are under the exact install root.

Do not bundle Node package caches, tests, source maps containing sensitive paths, developer databases, `.change-assurance`, logs, `.env`, Git data, or CML assets/branding.

### 11.2 Packaging pipeline

1. Check Windows/x64, Node, Python, dependencies, disk space, and icon inputs.
2. Run backend tests required for the release tier.
3. Run generated OpenAPI/type drift check.
4. Run renderer typecheck, lint, unit/component tests, accessibility audit, and production build.
5. Stage backend source and portable Python into an isolated exact directory.
6. Remove caches and development-only packages from the staged runtime.
7. Generate and verify the helper manifest.
8. Audit that packaged resources and writable roots do not overlap.
9. Build `win-unpacked` first.
10. Smoke the unpacked app with isolated `--user-data-dir`.
11. Build NSIS installer with workspace-local `TEMP`/`TMP` and isolated builder output.
12. Copy verified artifacts to the requested release directory.
13. Produce checksums and a machine-readable build receipt.

Recommended Electron Builder policy:

- `asar` for renderer/main application files.
- backend/Python as `extraResources` because they must execute outside ASAR.
- per-user install by default, `asInvoker` execution level.
- no forced deletion of user data on uninstall.
- signing disabled only for local development artifacts; signed release is a separate mandatory gate.

### 11.3 Installed-app verification

Use a disposable Windows user/profile or healthy clean VM and verify:

- install and uninstall;
- executable and shortcut targets;
- correct icons;
- first launch uses isolated state;
- backend starts and identity matches;
- repository with spaces can be selected and validated;
- create/read-only Change workflow persists over full desktop restart;
- API token does not appear in renderer storage or logs;
- Passport/replay export uses a selected location;
- logs and repair page remain available after forced backend startup failure;
- uninstall stops only install-owned runtime processes and preserves the Change database unless the user explicitly removes it.

## 12. Testing architecture

### 12.1 Pure unit tests

- Lifecycle/status-to-copy mapping.
- Next-action derivation from API facts.
- Error normalization.
- Idempotency-key retention.
- Query-key factories.
- Path display without changing native values.
- Timeline ordering and chain-break presentation.
- Trust-decision precedence.
- Recovery state copy.
- Setup-state normalization and transitions.
- Runtime URL and path containment validation.

### 12.2 Component/integration tests

Use Vitest, React Testing Library, user-event, and a contract-faithful mock transport generated from real schema examples.

Required behaviors:

- optional panel failure leaves primary content usable;
- dirty Contract draft survives background refresh;
- stale responses cannot replace a newer selection;
- mutation timeout prompts reconciliation rather than blind retry;
- status is never color-only;
- keyboard focus moves after navigation;
- dialogs trap focus and close on Escape where safe;
- destructive confirmations identify their target;
- unsupported and missing states are visible;
- long paths/errors wrap without hiding actions;
- 10,000 timeline items remain bounded through pagination/virtualization.

### 12.3 Electron unit tests

Use Node's test runner for CommonJS main-process modules:

- BrowserWindow security options.
- IPC allowlist and argument validation.
- sender-window resolution.
- stable custom protocol containment/traversal rejection.
- backend environment construction and secret redaction.
- authenticated identity acceptance/rejection.
- startup timeout and repair transition.
- exact-child graceful shutdown and fallback termination.
- setup-state atomicity, revision conflict, corruption quarantine, and concurrent lock behavior.
- helper manifest verification.
- isolated `userData` routing.

### 12.4 API acceptance tests for UI contracts

Add black-box backend tests before renderer wiring for:

- complete primary workflow using a real disposable Git repository;
- every UI-consumed error envelope;
- exact-SHA outcome precedence;
- stale evidence and lifecycle guards;
- delegation exhaustion;
- recovery stale-plan and repeated-execution behavior;
- denied tool plus artifact drift;
- journal sequence/integrity and pagination;
- restart persistence of every entity shown after relaunch;
- export round trips with no secret canary.

### 12.5 Playwright rendered tests

Run the web renderer with a real local test backend for contract-critical flows. Use the Electron launcher for native-bridge workflows.

Viewport matrix:

- 1024x680;
- 1280x820;
- 1440x900;
- narrow effective viewport representing 200% zoom;
- Windows display scaling check at 125% for final manual QA.

State matrix:

- no Changes;
- populated Change at each reachable lifecycle stage;
- missing/partial/stale evidence;
- backend offline and wrong identity;
- GitHub disconnected/unavailable;
- active/failed/timed-out agent and assurance runs;
- intact/broken journal chain;
- observed/provisional/approved/denied/drifted tools;
- recovery planned/conflicted/recovered/failed;
- long paths, names, output, and errors;
- reduced motion and keyboard-only navigation.

Capture traces and screenshots only on failure in CI, with a deliberate visual-regression set for approved primary screens.

### 12.6 Manual product QA

- Folder picker and Windows paths with spaces.
- Frameless drag/minimize/maximize/restore/close.
- Native save/reveal behavior.
- Screen reader announcement of status/errors.
- 200% zoom and high-DPI scaling.
- Backend crash/restart while a screen is open.
- Installer, shortcut, first run, restart, repair, and uninstall on a clean Windows environment.

## 13. Delivery phases and gates

### Phase 0 — Contract reconciliation and clean ownership

Tasks:

- Finish or hand off current uncommitted backend/context work.
- Re-run the ten backend readiness items in section 6.2.
- Regenerate and freeze OpenAPI.
- Record frontend/Electron ownership in coordination docs.
- Define the desktop runtime identity contract.
- Freeze visible product language and capability boundaries.

Gate 0:

- clean or explicitly partitioned working tree;
- OpenAPI snapshot equals live application;
- no unresolved P1 behavior behind a planned privileged UI action;
- `[SD]` publishes the `apps/desktop/**` claim and frozen OpenAPI hash; `[KB]` acknowledges both before editing.

### Phase 1 — Design contract and application skeleton

KB work:

- `[KB]`: full-screen concepts, tokens, typography, icon inventory, responsive rules, app shell, route skeleton, reusable primitives, self-contained workspace configuration, generated OpenAPI pipeline, transport interface, Electron module contracts, and fakes.
- `[SD]`: review product claims and confirm the frozen contract; do not edit KB-owned paths.

Gate 1:

- approved concepts for all states in section 3.2;
- renderer loads with static contract fixtures;
- no CML/Vault branding or product-specific runtime copied;
- typecheck and accessibility smoke pass.

### Phase 2 — Secure desktop shell and read-only vertical slice

`[KB]` implements:

- secure app protocol;
- BrowserWindow and chrome controls;
- sandboxed preload;
- token-hiding API proxy;
- backend runtime supervisor;
- startup/repair UI and logs;
- setup-state persistence.

`[KB]` also implements:

- Changes list;
- Change overview;
- capability and runtime health presentation;
- read-only Contract, evidence, timeline, tools, and Passport summaries.

Gate 2:

- packaged-style Electron app starts a real backend;
- token is absent from renderer storage/global API;
- create/list/get is not yet required, but all reads use real API data;
- backend failure opens repair instead of a blank window;
- Electron/unit/component suites pass.

### Phase 3 — Change intake, Contract, and authority

Tasks:

- repository picker and validation;
- Change creation;
- revision-aware Contract editing;
- actor/delegation workflows;
- lifecycle transition preview and errors;
- first-run setup reduced to runtime check, repository selection, optional GitHub, and first Change.

Gate 3:

- new user can create an ACTIVE Change without terminal commands;
- concurrency conflict and delegation expiry/exhaustion are visible;
- no hidden optimistic authority state;
- restart preserves backend and renderer state correctly.

### Phase 4 — Evidence, agents, and assurance

Tasks:

- baseline capture;
- launch/attach/stop top-level agent;
- current capture and comparison;
- evidence inspectors;
- assurance plan/run/evaluation;
- freshness-driven lifecycle actions.

Gate 4:

- real disposable repository completes baseline -> agent -> current -> assurance;
- committed and uncommitted changes are both represented according to contract;
- timeout, truncation, stale evidence, coverage gap, and unsupported evidence paths are tested;
- UI never claims process/file attribution.

### Phase 5 — Delivery, timeline, tools, recovery, and Passport

Tasks:

- GitHub connection/grants/PR/outcomes;
- event timeline and replay verification;
- tool inventory/detail/approve/deny;
- recovery preview/approval/result;
- Passport build and native export.

Gate 5:

- exact-SHA provider evidence is enforced;
- broken journal chain is visible;
- denied tool remains denied under drift until explicit later decision;
- stale/repeated recovery cannot produce contradictory terminal state;
- exported Passport/replay matches backend payload and contains no canary secret.

### Phase 6 — Performance, accessibility, and UX convergence

Tasks:

- pagination/virtualization at scale;
- focus, announcements, shortcut and keyboard passes;
- all empty/loading/failure/partial/unsupported states;
- narrow viewport, zoom, reduced motion, high-DPI;
- visual fidelity pass against approved concepts;
- remove duplicated route logic and dead controls.

Gate 6:

- browser and Electron workflows pass at all target sizes;
- direct concept/render comparison has no material mismatch;
- no control is inert or falsely enabled;
- no route module becomes a new oversized monolith without a recorded decomposition plan.

### Phase 7 — Packaging and installed release proof

Tasks:

- stage portable runtime and backend;
- integrity manifest/layout audit;
- win-unpacked smoke;
- NSIS build;
- isolated installed-app validation;
- build receipt, checksums, and release notes;
- healthy clean-machine rerun.

Gate 7:

- all package artifacts verified;
- first launch, restart, repair, export, logs, shortcuts, and uninstall proven;
- no developer data or credentials included;
- signed production artifact or an explicit non-production development label;
- release decision recorded by `[SD]`.

## 14. Parallel work and intersections

### 14.1 Safe parallel streams

| Stream | Owner | Exclusive area | Can begin after |
| --- | --- | --- | --- |
| Design system and renderer shell | `[KB]` | `apps/desktop/src`, renderer tests | Gate 0 contracts |
| Electron runtime and native bridge | `[KB]` | `apps/desktop/electron`, Electron tests | bridge contract recorded |
| OpenAPI generation/client contract | `[KB]` | `apps/desktop/scripts/api`, generated output | SD freezes live OpenAPI |
| Packaging | `[KB]` | `apps/desktop/scripts/packaging`, desktop build config | runtime layout frozen |
| Backend defect corrections | permanent backend owner via `[SD]` | existing backend-owned paths only | KB supplies failing acceptance evidence |
| Independent acceptance/release verification | `[SD]` | backend acceptance and release decision | each KB handoff |

### 14.2 Required intersections

1. **OpenAPI intersection:** `[SD]` freezes the root snapshot; `[KB]` regenerates types, records its hash, and reports any diff.
2. **IPC intersection:** `[KB]` owns both the preload contract and renderer consumer; `[SD]` reviews the security boundary at Gate 2.
3. **Design intersection:** `[KB]` supplies accepted screen contracts; `[SD]` checks product claims against backend capabilities.
4. **Mutation intersection:** `[KB]` supplies UI intent/idempotency behavior and reproductions; `[SD]` verifies backend semantics before enabling a blocked mutation.
5. **Packaging intersection:** `[KB]` stages, audits, packages, and supplies evidence; `[SD]` verifies the included backend revision and records release approval.
6. **Defect intersection:** frontend-discovered backend defects return to the permanent owner with a reproduction; renderer does not mask them.

No agent edits KB's `apps/desktop/package.json`, lockfile, generated API output, Electron IPC types, shared design tokens, or Electron modules concurrently. KB does not edit root `openapi.json`, `pyproject.toml`, `backend/**`, or shared context documents without an explicit SD handoff.

## 15. Task packets

### KB-FE-00 — CML extraction manifest

Produce a table of every CML file reused conceptually, the target file, adaptation, license/provenance note, and excluded product assumptions. Copy no code until this manifest is reviewed.

### KB-FE-01 — Design contract

Produce the concept set, tokens, typography, component/container inventory, status semantics, responsive behavior, and interaction ledger described in section 3.

### KB-FE-02 — Workspace and generated API

Create the self-contained desktop package, strict TypeScript, Vite, TanStack Router/Query, test harness, OpenAPI generation/check, feature query module skeletons, and browser-development transport. Prove clean `npm ci`, `api:check`, typecheck, lint, unit smoke, and Playwright smoke.

### KB-FE-03 — Product primitives

Implement `AppShell`, `WindowChrome`, `PageHeader`, `StatusMark`, `EvidenceState`, `OperationNotice`, `AsyncActionButton`, `DegradedState`, `SkeletonRegion`, `EntityInspector`, `EvidenceDisclosure`, `PathText`, `DangerZone`, `ConfirmAction`, and `CapabilityBoundary`.

Every shared primitive must replace at least two feature-specific copies or represent a cross-cutting safety/accessibility contract.

### KB-FE-04 — First real Change vertical slice

Execute section 9.9 end to end: runtime health, Changes list, native folder picker, validation, create, overview, restart persistence, and repair. Final proof must use the real backend, not only MSW. After that, add read-only contract, evidence, timeline, tools, and Passport summaries.

### KB-FE-05 — Intake and authority

Implement folder selection, repository validation, Change create, Contract edit, actors, delegations, revocation, and guarded transitions.

### KB-FE-06 — Evidence and execution

Implement baseline/current capture, comparisons, agent launch/attach/stop, output display, environment/dependency inspectors, and honest limitation copy.

### KB-FE-07 — Assurance and delivery

Implement assurance plan/run/evaluation, GitHub status/connect/grants/PR, outcome refresh, exact-SHA presentation, and stage transitions.

### KB-FE-08 — Journal, replay, and tools

Implement paginated event timeline, effect inspector, chain verification/export, tool list/detail, drift history, and explicit trust decision flow.

### KB-FE-09 — Recovery and Passport

Implement preview, approval-bound execution, conflict/failure states, post-recovery verification distinction, Passport build/view/export, and exact payload download.

### KB-EL-00 — Electron contracts

Freeze IPC request/response types, allowed channels, runtime state model, startup-state schema, log paths, renderer protocol, and test fakes.

### KB-EL-01 — Secure shell

Implement BrowserWindow, stable protocol, window controls, navigation denial, external URL allowlist, preload bridge, CSP, and startup window.

### KB-EL-02 — Backend runtime

Implement portable/development path resolution, token ownership, child environment, start/readiness/identity, log capture, restart, shutdown, descriptor, and repair transitions.

### KB-EL-03 — Native workflows

Implement repository picker, reveal path, save JSON export, open logs, diagnostics copy, and strict argument/path validation.

### KB-PKG-00 — Reproducible runtime staging

Implement prerequisites, locked dependencies, runtime cache fingerprint, exact staging cleanup, Python optimization, helper manifest, and layout audit.

### KB-PKG-01 — Windows artifacts

Implement generated Electron Builder config, win-unpacked and NSIS targets, workspace temp/output isolation, icons, uninstall helper, checksums, and build receipt.

### KB-PKG-02 — Installed lifecycle proof

Implement isolated profile launch, runtime smoke, real Change persistence restart test, installer/shortcut/registry checks, repair-mode injection, uninstall, and clean-machine evidence bundle.

### 15.1 Required completion loop for every packet

KB uses the same loop for every packet so implementation quality does not depend on unstated CML knowledge:

1. Re-read the relevant screen contract, API map, and capability limitation in this plan.
2. Confirm the generated operation and schema names in the frozen contract; do not infer fields from screenshots or CML.
3. Add or update fixtures for success, empty, partial, denied, stale, and failure states that apply.
4. Write the lowest-level behavior tests first for validation, state transitions, and safety boundaries.
5. Implement the smallest vertical behavior through transport, query/mutation, screen, and user feedback.
6. Run targeted tests while developing, then the full desktop unit suite before commit.
7. Exercise the behavior against a real backend and disposable repository when the packet touches persistence, Git, execution, or exports.
8. Check keyboard flow, focus, accessible names, status announcement, long values, narrow layout, and reduced motion for any changed interface.
9. Check logs, renderer storage, DOM, screenshots, and exported payloads for a canary secret such as `CA_TEST_SECRET_DO_NOT_LEAK`.
10. Update the desktop README and `CML_REUSE.md` when setup, scripts, packaging, or provenance changes.
11. Commit only the packet's paths and provide the handoff template from section 0.4.

### 15.2 Test depth required by code type

| Code type | Minimum automated proof | Additional real proof |
| --- | --- | --- |
| Pure formatter/validator/reducer | branch-focused unit tests including invalid/null/long input | none unless security-sensitive |
| Query/mutation module | MSW success and standard error; key/invalidation; abort; idempotency where relevant | one call against real backend per operation family |
| Form/dialog | validation, keyboard submit/cancel, focus trap/restore, server field error, pending state | successful and denied workflow against real backend |
| Polling/long operation | fake-timer unit test for hidden, overlap, backoff, abort, terminal stop | observe one real run through a terminal state |
| Electron IPC/native action | unit test with mocked Electron and argument validation | Electron smoke for folder/save/reveal/log action |
| Runtime/process code | fake process/HTTP branches including timeout and wrong identity | actual start, crash, restart, shutdown; prove unrelated process survives |
| Packaging/staging | manifest, containment, exclusion, hash, idempotent rerun tests | unpacked and installed isolated-profile run |
| User workflow | component integration for state variants | Playwright browser plus Electron for native/runtime portions |

Coverage percentage alone is not acceptance. Tests must prove the risk-bearing branches listed in each task. Any skipped test needs a named owner, reason, and release impact.

### 15.3 Stable verification commands

From the repository root, KB runs backend compatibility tests without modifying backend code:

```powershell
python -m pytest
```

From `apps/desktop`, KB runs:

```powershell
npm ci
npm run api:check
npm run typecheck
npm run lint
npm test
npm run test:e2e
npm run build
npm run package:dir
npm run verify:package
npm run package:win
```

KB adds explicit `test:electron` and `test:package` scripts once their harnesses exist and includes both in `build` or release CI. Record exact Python, Node, npm, Electron, and Windows versions in the final evidence bundle.

### 15.4 What KB sends at the final integration point

The final handoff is one release-candidate commit plus:

- the frozen OpenAPI hash and generated-contract check result;
- every packet handoff and known limitation;
- unit, component, browser E2E, Electron, backend compatibility, staging, unpacked, and installed results;
- design-contract comparison screenshots at 1280x820, 1024x680, narrow/200% zoom, and repair mode;
- CML provenance/notice ledger;
- package manifest, helper hashes, build receipt, installer checksum, and isolated `userData` location;
- sanitized logs for first start, backend restart, persistence restart, repair, and uninstall;
- backend defect reproductions still open and the exact UI features held unavailable because of them.

SD then independently verifies the candidate and updates shared context/coordination documents. KB does not mark the release approved on its own.

## 16. Release-blocking acceptance matrix

| Area | Required proof |
| --- | --- |
| Contracts | Live OpenAPI, snapshot, and generated TypeScript agree |
| Authentication | Token remains out of renderer storage/logs and wrong token is rejected |
| Identity | Desktop accepts only the expected Change Assurance backend/API identity |
| Persistence | Change, Contract, evidence, actors, outcomes, recovery, journal, tools, and Passport survive restart as specified |
| Evidence | Committed and uncommitted test fixtures yield truthful, fresh comparisons |
| Authority | Expiry, revocation, use limits, wrong Change, wrong repository, and wrong scope are denied |
| Execution | Top-level launch/attach/stop is bounded and never claims descendant control |
| Assurance | Required, optional, failed, skipped, stale, truncated, and coverage-gap states render distinctly |
| Delivery | PR and CI state is tied to exact repository/head and latest applicable observation |
| Journal/replay | Sequence/hash break is detected; limitations deny re-execution/process/filesystem claims |
| Tool trust | Explicit denial cannot be weakened by observation, Passport generation, or drift |
| Recovery | Preview/approval freshness, conflict safety, idempotency, and post-verification are demonstrated |
| Exports | Passport/replay exports are exact, bounded, redacted server payloads |
| Accessibility | Keyboard, focus, names, announcements, contrast, zoom, reduced motion pass |
| Performance | Large event/run/change/tool datasets remain responsive and paginated |
| Packaging | Unpacked and installed artifacts start cleanly with isolated state and verified helpers |
| Uninstall | Only install-owned processes are stopped; user state is preserved by default |

## 17. Risks and mitigations

### Risk: copying CML complexity instead of its lessons

Mitigation: extraction manifest, adopt/adapt/reject review, and explicit exclusion of model/OCR/tunnel/vault subsystems.

### Risk: UI solidifies broken backend semantics

Mitigation: Gate 0 backend readiness suite and disabled privileged surfaces until their acceptance evidence passes.

### Risk: Electron becomes a privileged generic bridge

Mitigation: narrow typed IPC, main-process validation, no raw token, no arbitrary file or command primitives.

### Risk: generated types create false runtime safety

Mitigation: backend contract tests, safe error parsing, boundary validation for desktop IPC, and fixtures from real API responses.

### Risk: route/component monoliths repeat CML's maintenance burden

Mitigation: feature packages, query modules, behavior primitives, route size review, and component-level tests.

### Risk: local runtime appears healthy when connected to the wrong database/service

Mitigation: authenticated identity contract and expected-instance verification before renderer ready.

### Risk: renderer timeout duplicates mutations

Mitigation: intent-stable idempotency keys and status reconciliation before retry.

### Risk: packaged build passes on the developer machine only

Mitigation: isolated `userData`, unpacked/installed lifecycle tests, helper audit, and healthy clean-VM gate.

### Risk: desktop shell is mistaken for process supervision

Mitigation: manage only the exact runtime child the desktop launched and keep user copy scoped to backend runtime status.

## 18. Definition of done

The frontend/Electron phase is complete only when:

1. The complete retained workflow works through the installed desktop application using real backend data.
2. Every visible capability claim matches the bounded backend contract.
3. Empty, loading, partial, stale, denied, failed, timeout, conflict, unsupported, offline, and repair states are deliberately implemented.
4. Renderer contracts are generated from a current frozen OpenAPI snapshot.
5. The renderer never receives the production API token or direct Node access.
6. Privileged mutations use authority, idempotency, preview/confirmation, and reconciliation appropriate to their risk.
7. The UI remains usable at the required viewports, zoom, keyboard, reduced-motion, and high-DPI conditions.
8. Frontend, Electron, backend-contract, Playwright, packaging, and installed-app suites pass.
9. Accepted design concepts and final screenshots receive a documented fidelity comparison with no material mismatch.
10. Package contents, helper hashes, logs, startup, restart, repair, install, and uninstall are verified in an isolated environment.
11. No CML/Vault secrets, data, branding, generated state, or unrelated runtime dependencies are included.
12. `OVERALL_CONTEXT.md`, `PROJECT_CONTEXT.md`, `AGENT_COORDINATION.md`, and the OpenAPI release record are synchronized in a clean `[SD]` integration window.

## 19. Immediate next actions

1. Finish and commit or hand off the active uncommitted backend/context work.
2. Run Gate 0 backend correctness verification and refresh `openapi.json`.
3. Have `[SD]` record `[KB]` ownership of `apps/desktop/**`; no AC/SD renderer split remains.
4. `[KB]` creates KB-FE-00 and records the CML extraction/provenance manifest.
5. `[KB]` generates the eight-screen design contract and asks SD to review product claims.
6. `[KB]` bootstraps KB-FE-02 and KB-EL-00 only after the contract and ownership gates pass.
7. `[KB]` delivers the real first vertical slice in section 9.9 before implementing privileged actions.

This order preserves the core CML lesson: establish truthful state, durable boundaries, and recovery behavior first; visual polish and broader workflows build on that foundation rather than compensating for its absence.
