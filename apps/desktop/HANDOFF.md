# Desktop frontend: handoff for backend integration (SD / AC)

State: `apps/desktop`, built on upstream `master`. Run/test/package instructions: `README.md`. Decisions and history: `FRONTEND_PLAN_ADDENDUM.md`. Comparison with the CML reference: `CML_REFERENCE_STUDY.md`.

## 1. Verified (this session, against upstream `d0f1301`)

| Check | Result |
| --- | --- |
| `api:check` (after `api:generate`), `typecheck`, `npm run build` | pass |
| `npm test` | **46 renderer + 98 Electron** pass (was 44 + 89 at the start of the session) |
| Playwright (`npm run test:e2e`) | **Last complete run: 85 of 85 pass** (before code-splitting, the repair page and the permission/identity changes). After those, a full run had 81 pass; its only failures were the `smoke.spec.ts` Ctrl+K test racing the lazy-loaded route (fixed by waiting for the heading) and the knock-on from its serial retry. After the fix, `smoke.spec.ts` passes 7 of 7 with retries off. **A final full run after the fix was started but was not confirmed before this push, so rerun `npm run test:e2e` once (one run at a time, port 8000 free) to reconfirm.** |
| `npm run package:dir` then `npm run test:electron:smoke` | 12/12 on the earlier package; **not rerun** after code-splitting, the repair page and the permission handlers, so repackage and rerun it too |

The 14 new Playwright tests cover: server-provided next states and the fallback, list `total` paging (including an exact page-size multiple), Home totals, the actor list with a filter and the manual-id fallback, duplicate-submit, backend identity in Settings, the missing-Git message, fork lineage without a repository summary, an accessible-name audit of every screen with a console-error check, keyboard focus return, and the tab strip at 1024x680.

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
