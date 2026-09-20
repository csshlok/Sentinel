# Frontend plan addendum (local draft, not committed)

Primary plan: `FRONTEND_ELECTRON_IMPLEMENTATION_PLAN.md` at commit `9852057` ("[SD] frontend plan"). It is not edited.
This addendum records what is built and verified, the contracts in force, deviations, and what remains.
Branch `frontend`, uncommitted. Project: `apps/desktop` (self-contained). Run/test/package instructions are in `README.md`.

## 1. Status

| Area | State |
| --- | --- |
| Design system (Tailwind v4 + shadcn/ui, CML-style flat warm palette) | Built |
| Frameless window with auto-hiding drag bar and window controls | Built, verified in real Electron |
| Pages: Home (stats, needs attention, recent, service), Changes (paged list, filter, create), Change workspace (Overview, Contract, Evidence, Timeline), Tools, Settings | Built; read-only except creating a Change |
| Command palette (Ctrl/Cmd+K), deep-linkable `?new=1`, managed-backend startup/repair state | Built |
| Typed service layer + generated OpenAPI types | Built |
| `app://` protocol, unpacked package with **bundled Python + backend** | Built and verified |
| Desktop-managed backend with crash recovery (stale-process reaper) | Built and verified |
| Tests: 11 renderer + 82 Electron unit, 23 Playwright (8 real-backend smoke + 15 resilience) | Passing |
| NSIS installer, signing, `openapi` freeze, ownership sign-off | Not done |

## 2. What changed this round

1. **Design follows CML/Vault**: light warm-neutral palette (`#FAFAF8` canvas, `#7C6E5A` accent), hairline borders, no shadows, dot-style status labels,
   220px sidebar with search/⌘K, flat bordered panels with a header row, 5px scrollbars, body never scrolls (regions do). This replaces my earlier dark theme.
2. **Frameless window**: no title bar. A 6px hover zone at the top edge reveals a 32px drag bar with minimize / maximize-restore / close after a short delay;
   it hides again when the pointer leaves. The sidebar background is also a drag region. Controls act on the sending window only.
3. **Tailwind v4 + shadcn/ui** via the official CLI (`components.json`, `@/` alias). Added: button, dialog, command, input, textarea, label. Button restyled flat.
4. **CORS solved without touching the backend**: Vite proxies `/api` to the backend, so the renderer is same-origin and the CORS allow-list is irrelevant.
5. **Python is bundled**: `npm run stage:backend` downloads the embeddable CPython 3.12.10 (SHA-256 pinned; `python.exe` must carry a valid PSF Authenticode
   signature), installs `fastapi`, `pydantic`, `uvicorn[standard]` for `win_amd64` into the stage only, copies `backend/` without tests, smoke-tests imports with an
   empty `PATH`, then **audits the stage** (no tokens, databases, env files, tests, caches). Packaged builds run the backend from `resources/backend`.
6. **Self-quit investigation**: not reproducible in three 45-second managed runs; a desktop log (`userData/logs/desktop.log`) now records start, ready, before-quit,
   window-all-closed, second-instance, child-process-gone, renderer-gone and exit code, so any recurrence has a recorded reason.
7. **Backend crash recovery** (found while testing): force-killing Electron left the managed backend running (and a Python launcher shim or venv `python.exe` starts the
   real interpreter as a child, so killing only the parent orphans it). Now a non-secret descriptor (`pid`, `port`, marker) is written after spawn; on next launch the
   stale backend is killed with its process tree only if its PID, `backend.app.main:app`, and port all match; escalation on stop also kills the owned child's tree.
8. **Git preflight**: the shell detects `git` once and Settings shows `Found · <version>` or a plain "install Git" message.

## 3. Architecture decisions

- Server state: TanStack Query (`queryOptions` per service). Health polls 8 s (2 s while failing); the runtime-status poll runs in the background too so a starting backend is never stale.
- Routing: TanStack Router, code-based, path history. `?new=1` opens the create dialog.
- UI copy is derived only from backend facts. "Needs attention" lists real findings (missing evidence, failed verification, truncated output, off-path lifecycle).
- Relative times ("2 hours ago") with the exact time in `title`; long paths/hashes wrap; tables scroll horizontally.
- Accessibility: skip link, focus moved to `<main>` on navigation, icon+label nav with `aria-current`, labelled form fields with inline errors, status always text + dot,
  reduced-motion respected, dialogs via Radix (focus trap, Escape).
- Managed vs external backend: development defaults to **external** so a manual Uvicorn is never disturbed; packaged builds default to **managed**.

## 4. Contracts

**Service layer** (`src/lib/api`): `Transport.request<T>(ApiRequest, AbortSignal?)`; methods `GET|POST|PUT|DELETE`; `assertApiPath` rejects anything but plain `/api/v1/...`;
`ApiError.kind` in `auth | offline | timeout | not_found | conflict | validation | server | bridge | aborted | unknown`; browser transport is same-origin.

**Bridge** (`window.changeAssuranceDesktop`, frozen): `api.request`; `runtime.getStatus` (`{packaged, backend:{mode,state,url,detail}, hasToken, git:{available,version}}`),
`runtime.restartBackend`; `repositories.selectFolder`; `windowControls.getState/minimize/toggleMaximize/close/onStateChanged` (one fixed state channel; callback gets only the state object).

**Protocol**: `app://app/`, serves only `dist/`, rejects traversal in every encoding, dotfiles, foreign hosts/schemes, symlink escapes; SPA fallback for extension-less paths; CSP with `connect-src 'none'`.

**Backend lifecycle**: `external` probes only; `managed` = free loopback port, per-session token (memory only), isolated data dir, authenticated readiness, redacted logs,
descriptor + reaper, tree-kill escalation, `restart()`. States: `idle, starting, ready, failed, exited, stopping`.

## 5. Verification

- `api:check`, `typecheck`, `build`: pass. `npm test`: 6 + 58 pass. Playwright: 7 pass (throwaway backend + Git repo under the OS temp dir; token never in the repo).
- Real Electron via the debug port (dev, `app://`, managed, packaged): chrome hidden at rest / revealed on hover / hides again; maximize toggle reports state over IPC;
  palette and dialog open; `require`/`process` undefined; bridge shape exact; no console problems; token absent from DOM, storage and bridge returns.
- Packaged app with **no Python on PATH and no manual backend**: one process, the bundled interpreter; Connected; validate 200, create 201, idempotent replay returns the same Change;
  graceful close leaves no processes. Force-kill + relaunch: stale backend reaped, single backend, clean shutdown.
- Package audit: asar = built renderer + 12 Electron modules + `package.json`; bundled backend has no tokens/DBs/tests/caches (the audit caught, and I fixed, a token file
  created by my own staging smoke test).

## 6. Findings for SD / backend

1. Without `git` on `PATH` the backend returns an opaque **500** for `/repositories/validate` and `POST /changes`. A clear 4xx would let the UI say what is wrong (the desktop now shows a Git indicator in Settings).
2. `GET /api/v1/system/backend-identity` (plan 6.3) still does not exist; identity is only "health + authenticated call".
3. Upstream `master` moved after this branch (3 SD commits). `openapi.json` gained `providers/github/pulls/close` and `tools/declare`; **no schema used by the current screens changed**,
   so merging needs only `npm run api:generate`.
4. Idempotency keys shorter than 8 characters get a 422 (the UI always sends UUIDs).
5. Ownership (plan says `[KB]` owns `apps/desktop/**`) and Gate 0 / OpenAPI freeze are unresolved; nothing here should be committed before SD decides.

## 7. Deviations from SD's plan

Same as before plus: plain-token CSS replaced by Tailwind v4 + shadcn/ui (closer to the plan); light theme instead of my earlier dark theme (follows CML); Vite `localhost` host and same-origin proxy;
TypeScript 5.9; `"type": "module"`; managed backend, `app://` and packaging built before the design-spec gate; `repositories.selectFolder`, `runtime.restartBackend`, window controls and Git detection
added to the bridge/status now. Design-spec gate (plan 3.2) still not run: screens were reviewed against CML and in Chrome/Electron screenshots only.

## 8. Known limitations

- Read-only apart from Change creation: no contract editing, transitions, evidence capture, agents, assurance, delivery, recovery, Passport, or trust decisions.
- No pagination beyond the first 50 Changes / 100 events; no chain verification view; Passport tab absent.
- Windows x64 only; unsigned; no installer; `author`/icon metadata missing; fonts are system fonts (Segoe UI); no dark theme.
- The packaged app is ~404 MB unpacked (Electron itself dominates); the bundled backend is 34 MB.
- Real-window Electron checks were scripted over the debug port outside the repo; they should become a committed `test:electron:smoke`. No React component tests.
- Backend `git` is a machine dependency, not bundled.
- One scripted check of a freshly built package reported the connection chip as not Connected after 30 s even though the runtime was `ready` and capabilities returned 200. I could not reproduce it: 5 later fresh launches all showed Connected at 14 s and 30 s (window visibility was ruled out). Cause unknown; the desktop log and the recovery path (health error -> success invalidates all queries) are in place if it recurs.

## 9. Remaining tasks (priority order)

1. SD: ownership, Gate 0, OpenAPI freeze; decide on backend-identity and the missing-git error.
2. Merge upstream `master`, `npm run api:generate`, re-run all suites.
3. Commit a `test:electron:smoke` script (dev, `app://`, managed, packaged, force-kill/reap) and add React component tests.
4. Contract editing with revision conflicts; actors/delegations; guarded lifecycle transitions.
5. Evidence capture, agent launch/attach, assurance plan/run/evaluation.
6. Delivery (GitHub), tool trust decisions, recovery preview/approval, Passport build/export.
7. Pagination, chain verification, accessibility pass (zoom, screen reader), optional dark theme.
8. NSIS installer, app icon and metadata, signing, installed-app lifecycle proof, update policy.

## 10. Testing strategy and what it found (this round)

Base taken from CML: Electron **main-process behaviour tests against an Electron stub** (`main.behavior.test.cjs`), and Playwright **with the backend mocked via `page.route`**
(deterministic offline, 401, slow, paged and huge states) plus geometry assertions at the 1024x680 minimum, large text and reduced motion. I did not copy their source-text
"presentation" tests (they assert on source strings, which the plan says to avoid).

| Layer | What is covered |
| --- | --- |
| `electron/tests/main.behavior` (18) | scheme registered before ready; frameless/sandboxed window options; prod vs dev URL; pop-up and navigation rules; title lock; exact IPC channel set; every handler rejects untrusted senders with zero network/dialog effects; token only in main; safe errors; quit ordering; single-instance; log has no token |
| `electron/tests/stress` (6) | 4,000 fuzzed API paths (only plain `/api/v1` reach the network); 6,000 fuzzed asset URLs never escape the root; 200 concurrent proxied requests; slow/failing backend never wedges later calls; 60 rapid restart cycles leave exactly one live child; concurrent `start()` spawns once |
| `src/lib/status.test` | every backend enum value has a label; denied/failed are never a success tone; relative-time boundaries incl. future and null |
| `e2e/resilience` (15, fake backend) | hostile/huge/unicode titles at 4 viewports (no overflow, no injection); offline then auto-recovery; wrong token; 40 rapid navigations under a slow backend; filtering; **paging Changes (130) and events (250)**; 500-row table; **stale repository check race**; **Enter-mash double submit**; failed create keeps form and retries with the same idempotency key; keyboard and focus return; unknown routes; 200% zoom + reduced motion; 40 open/close cycles (no DOM growth); **even spacing** (one 24px vertical rhythm, one left edge, table inset = panel padding) |
| `e2e/smoke` (8, real backend) | end-to-end through the real API |

**Bugs the tests found and I fixed:** (1) a slow repository check could overwrite the result for a newer path; (2) the create form could submit repeatedly via Enter;
(3) focus was not restored to "New Change" after closing the dialog; (4) only the first 50 Changes / 100 events were reachable (now "Load more" with de-duplication);
(5) the events cursor was wrong for the real backend (`since_seq` is inclusive and starts at 1). **The fake had hidden (5), which the real-backend smoke test caught, so the fake now mirrors that contract**;
(6) on Change pages the back link sat 4px left of everything else. Also: the e2e teardown left a stranded Python child (same launcher-shim issue as the app), now tree-killed.

**Still not covered:** real-window Electron checks are scripted outside the repo (should become `test:electron:smoke`); no React component tests; no visual-regression snapshots; no sustained-duration soak test;
Windows only. A 10,000-item list was not tried because the backend caps pages at 50 here.

**"Feels empty" changes:** a Home page (stats, needs-attention, recent, service, and a 3-step guide when there are no Changes), Overview now shows Changed files and Recent activity, rows show changed-file counts,
a filter and paging on long lists. Everything shown comes from real endpoints.


## 11. Update (later session): implementation details that changed

The sections above describe the first, read-only build; the current state is in `HANDOFF.md`. Architecture notes that changed since:

- Forms share `components/FormDialog.tsx` (`FormDialog`, `useFormAction`, `Field`, `Select`) and `ConfirmDialog.tsx`; `useFormAction` owns the idempotency key, a synchronous in-flight lock and cache invalidation. The generic `features/ops` dialog and `RecordView` were removed.
- Feature folders (`authority`, `agents`, `assurance`, `delivery`, `evidence`, `recovery`, `timeline`, `passport`, `tools`) hold bespoke screens; pure rules live beside them (`recovery/rules.ts`, `delivery/outcomes.ts`, `timeline/payload.ts`) so Node's test runner can cover them.
- `lib/lifecycle.ts` prefers `ChangeView.allowed_next_states` from the backend and mirrors `core/lifecycle.py` only as a fallback (parity test kept).
- Theme: `lib/theme.ts` sets `<html data-theme>`; both palettes are checked by `styles/contrast.test.ts`.
- Bridge additions: `exports.saveJson` (user-chosen path via native dialog) and `diagnostics.openLogs` (fixed path). Both validated in main and covered by tests.
- Shell: `electron/repair-page.cjs` (renderer failure page), deny-all permission handlers, and a backend-identity check in `backend-runtime.cjs`. Routes are lazy-loaded (`lazyRouteComponent`).
