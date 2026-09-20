# Desktop frontend: handoff for backend integration (SD / AC)

State: `apps/desktop`, built on upstream `master`. Run/test/package instructions: `README.md`. Decisions and history: `FRONTEND_PLAN_ADDENDUM.md`. Comparison with the CML reference: `CML_REFERENCE_STUDY.md`.

## 1. Verified (final heavy run, uncommitted working tree)

| Check | Result |
| --- | --- |
| `api:check`, `typecheck`, `npm run build` | pass |
| `npm test` | **50 renderer + 98 Electron** pass |
| Playwright (`npm run test:e2e`) | **93 of 93 pass** (4.5 min), including the real-backend workflow, the real-repo test on a clone of `github.com/csshlok/vthacks14`, resilience and accessibility audits, 130-Change paging and the 60-second soak |
| `npm run package:dir` then `npm run test:electron:smoke` | **12 of 12 pass** on `release/win-unpacked/Sentinel.exe` |
| Large real repository (`django/django`, 7,091 files, 73 MB) driven through the real backend | Create, baseline, current, refresh, compare, assurance plan and trace verification all correct. Baseline capture, current capture, refresh, listing checkpoints and reading assurance facts each take about 9 to 10 seconds at this size (backend speed; the UI shows loading skeletons). |

Not run for real (external setup): GitHub connect and pull requests, agent launch (needs an installed adapter), recovery execute, tool trust decisions. Their forms and request shapes are covered by typed forms and the scripted backend.

Housekeeping: run one Playwright run at a time with port 8000 free; an interrupted run leaves its throwaway backend behind.

## 2. What the UI does (every backend operation has a screen; no generic record views remain)

Home, Changes (paging, filter, create), Change workspace: Overview (guarded state changes that offer only backend-allowed moves and name each guard, verification, cancel, delete), Contract (revision-aware edit), Evidence (capture, checkpoints, compare, environment and drift, dependencies, tools seen, declare tool, fork from a checkpoint, forks), Assurance (facts, plan, run, evaluation, deviations, coverage gaps), Agents (adapters, launch, attach, pause, resume, stop, bounded output), Delivery (GitHub connection, grants, pull request preview/create/close, outcomes tied to the exact head commit, newer failure supersedes older pass), Authority (actors, delegations with active/expired/exhausted/revoked, revoke), Recovery (preview, staleness check, approval bound to the plan id, recovered vs verified), Passport (build, view, native export), Timeline (auto chain verification, event inspector with effects, trace export). Tools list and tool detail with trust decisions. Settings (service, auth, GitHub, appearance with dark theme, diagnostics summary, capabilities).

Native (Electron): exports go through a save dialog the user controls (the renderer only suggests a file name), and the logs folder opens from a fixed path. Bridge is now `api`, `runtime`, `repositories`, `exports`, `diagnostics`, `windowControls`.

## 2a. Changes this session

- **Uses the new backend surface** (`d0f1301`): `ChangeView.allowed_next_states` (the mirrored table in `lib/lifecycle.ts` is now only a fallback for an older backend, and `lifecycle.test.ts` still guards it), `ChangeListResponse.total` (paging stops exactly at the total; Home and the list show real counts), `GET /actors` (pickers list every registered actor and gain a filter box past 8; older backends fall back to delegation-resolved actors plus locally created ones), `GET /system/backend-identity` (Settings shows service, instance and start time), and `GIT_EXECUTABLE_NOT_FOUND` (plain "install Git" message).
- **Bugs fixed:** a fast double click could send two submissions (React state was stale within the tick; `useFormAction` now locks synchronously); dialogs opened from plain buttons dropped focus on the page body after Escape (`useReturnFocus`); the light theme's warning color was 2.9:1 as text, and the success color was below 4.5:1, so both were darkened.
- **New guards:** `styles/contrast.test.ts` reads the real tokens of both themes and checks WCAG ratios; the accessible-name audit runs over all 15 screens.
- **Polish:** the Change tab strip no longer draws a heavy scrollbar and keeps the current tab in view at narrow widths.
- **Shared pieces added:** `components/useReturnFocus.ts`, `ActorSelect` filter in `components/pickers.tsx`, `identityQuery`/`actorListQuery` services, `KNOWN_CODE_MESSAGES` in `lib/api/client.ts`.

## 2b. Shell hardening and performance (later in the same session)

Test-hygiene notes: a Playwright run that is interrupted leaves its throwaway backend on port 8000, and two overlapping runs kill each other's Vite and backend. Run one at a time, and stop a stray `uvicorn ... --port 8000` before rerunning. `smoke.spec.ts` (serial, shares one real backend) now waits for the Tools heading before pressing Ctrl+K; the lazy-loaded route exposed a race where the shortcut listener was not yet attached.


- **Deny-all web permissions:** the main process refuses every permission request and check (camera, microphone, location, notifications, clipboard read, and so on). Covered by a main-process behavior test.
- **Backend identity enforced:** the supervisor only treats a service as ready if `GET /system/backend-identity` names `change-assurance…` (a 404 from an older backend is accepted), so another program on the port is never mistaken for the backend. Three supervisor tests.
- **Repair page:** if the renderer fails to load, or its process dies, the window shows a self-contained page (no script, locked-down CSP, escaped text) that retries every 3 seconds, at most 10 times, instead of a blank window. `electron/repair-page.cjs`; 4 unit tests and 1 behavior test.
- **Code splitting:** every screen after first paint is its own chunk; the main bundle went from 583 kB to 388 kB.

## 2c. Sentinel overhaul (uncommitted, later session)

- **Renamed to Sentinel** everywhere a user sees it (window title, sidebar, repair page, installer product name, README). Internal identifiers (`CHANGE_ASSURANCE_*` environment variables, `com.changeassurance.desktop` app id, `ca.*` storage keys) are unchanged so nothing breaks. Because `productName` changed, the packaged executable is now `Sentinel.exe` and Electron's per-user data folder name follows it; an existing install's data would not be picked up automatically.
- **Sidebar groups:** Workspace (Home, Changes, the five most recent Changes with a status dot), Control (Agents, Actors, Tools), Integrations (GitHub), System (Settings). Defined once in `src/lib/nav.ts`.
- **New global screens** that surface backend features which previously lived only inside a Change: `/agents` (adapters, live runs across recent Changes, jump to launch), `/actors` (registered actors, register one), `/github` (connection, pull requests and CI across Changes).
- **Home** gained a Control center: five tiles that each open a real screen.
- **Settings capabilities** now link each available capability to where it is used (`CAPABILITY_LINKS`), with a "Used in" line. Capabilities the backend reports as unsupported show no link.
- **Tests added** in `e2e/contract.spec.ts` (sidebar groups and recent Changes, Home links, Actors, Agents, GitHub, Settings links; the accessible-name audit now covers the three new routes). **Not yet run**: the Playwright suite needs port 8000 free, and a demo backend was running for the live preview when this was written. Typecheck and unit tests pass.
- Limits of the new pages: the API lists agent runs and outcomes per Change, so the cross-Change views gather the eight most recently updated Changes.

## 2d. Logo, walkthrough, terminal connect, capability guidance (uncommitted)

- **Logo:** `components/SentinelMark.tsx` (a shield with an eye, theme-aware) in the sidebar, and `public/favicon.svg`. **Not done:** the Windows app/installer icon (`.ico`) still needs generating from the mark.
- **Walkthrough:** `/walkthrough`, eight steps in working order, each with why, where and a button; steps tick themselves off when the API can tell (Change exists, actors exist, GitHub connected). Home shows a one-time prompt.
- **Terminal (TUI) card** in Settings: `python -m pip install -e ".[tui]"`, load the token from its file into `CHANGE_ASSURANCE_API_TOKEN`, then `python -m backend.app.tui.app --api-url <url> [--actor-id <id>]`. The token value is never shown; non-loopback addresses produce no command. When the app runs its own private service its token is in memory only, so the card says to start the service yourself for terminal use.
- **Capability guidance:** every capability now says what it is for and what it works with (`lib/capabilityInfo.ts`); the two unsupported ones say why.
- **Real-life test:** `e2e/reallife.spec.ts` clones `github.com/csshlok/vthacks14` and drives create Change, evidence capture and compare, timeline verification, the walkthrough and the terminal card. It skips (not fails) offline.

## 3. Facts learned from the real backend this round

- The backend rejects self-delegation (`SELF_DELEGATION_NOT_PERMITTED`); the form blocks it up front.
- The assurance evaluation endpoint returns status `MISSING` before any check has run; the UI shows that rather than "not evaluated".
- Recovery's "approval token" is any non-empty string. The UI binds it to the plan by requiring the operator to type the plan's short id.
- Fork copies the contract, uses the checkpoint as its baseline, records lineage, and does not copy delegations.
- Scope names the policy layer checks: `agent.launch`, `agent.attach`, `agent.stop`, `assurance.run`, `change.fork`, `change.legacy_verify`, `github.repo.read`, `github.pr.create`, `github.pr.close`, `recovery.execute`.
- `src/lib/lifecycle.ts` mirrors `backend/app/core/lifecycle.py`; `lifecycle.test.ts` parses the Python file and fails if transitions or guards drift.

## 4. Backend and decisions still needed (status after `d0f1301`)

Delivered upstream and now used: backend identity, missing-Git error, allowed next states (graph membership only; a listed move can still 409 with `missing_requirements`), list totals, actor list.

Still open:
1. **Ownership** of `apps/desktop/**` (plan says `[KB]`; `AGENT_COORDINATION.md` records no claim). *Decision-blocked.*
2. **Gate 0 / OpenAPI freeze hash** to pin `OPENAPI_SHA256`. *Decision-blocked.*
3. **Credential grants list** (`GET .../providers/github/grants`): the UI only remembers grants created on this install. *Backend-blocked.*
4. **Tool decision history** endpoint. *Backend-blocked.*
5. **Total on other lists** (events, outcomes, tools) if they can exceed a page. *Backend-blocked.*
6. **Product-copy sign-off**, signing identity, icon, NSIS, update policy. *Decision-blocked / credential-blocked.*
7. Whether the frontend should stop mirroring the guard table and read guards from the server. *Backend-blocked.*

## 5. Still open (frontend)

1. **Startup hash check of the bundled Python** (helper manifest generated at staging and verified before spawn, as CML does). Not done.
2. **Installer:** the build target is still `dir`. NSIS, an uninstall hook that stops only install-owned processes, signing and installed-app lifecycle proof. Not needed for a demo; needed for a Windows release. *Decision/credential-blocked.*
3. **Not exercised end to end** because they need external setup: GitHub connect/PR/close, agent launch (needs an installed adapter), recovery execute (needs a previewed plan on a repo with commits), tool trust decisions against a real observed tool. Their request shapes are covered by typed forms and the fake backend. *Credential/adapter-blocked.*
4. React component tests (behavior is covered by Playwright instead).

## 6. Housekeeping

- `npm run test:e2e` needs port 8000 free. An interrupted run can leave its throwaway backend behind; stop that `uvicorn` before rerunning.
- Windows x64 only; Git must be on PATH; package is about 400 MB (Electron dominates).
