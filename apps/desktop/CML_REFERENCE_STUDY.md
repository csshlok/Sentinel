# CML / Vault reference study

Studied at `C:\Users\krish\Downloads\reference\CML` (shallow clone of `https://github.com/csshlok/CML`, commit `4183ad4`, v0.1.15, 2026-08-14). Nothing in that clone was modified. This document records concepts only; **no CML code, assets or branding were copied**, so `CML_REUSE.md` needs no new rows.

## 1. License

`LICENSE` is **MIT, © 2026 Vault contributors**. Reuse, modification and redistribution are allowed provided the copyright line and permission notice stay with any copied or substantially adapted code. Rule for this repo: reimplement ideas freely; if code is ever copied, add a row to `CML_REUSE.md` and ship the MIT notice. The Vault name, logo (`public/brand`), help content and product copy are not adopted regardless of license.

## 2. What CML is

A monorepo: Python backend (`backend/`), a Windows Electron + React desktop app (`apps/desktop`, ~126 source files), a browser extension, and PowerShell packaging scripts. The desktop app is the reference for this project.

| Area | CML choice |
| --- | --- |
| Framework / build | React 19, Vite 7, TanStack Start + Router (file routes, generated `routeTree.gen.ts`), TanStack Query, Tailwind v4, Radix primitives, shadcn-style `ui/`, cmdk, zustand, Cloudflare Vite plugin |
| Layout | `src/{components,hooks,lib,routes,types}`; `components/{ui,product,layout}`; routes `_app.*.tsx` under a pathless `_app` layout, plus `onboarding` and `__root` |
| Electron | one 2,183-line `electron/main.cjs` plus small helpers (`preload`, `window-controls`, `setup-state`, `token-store`, `runtime-descriptor`, `helper-integrity`, `ipc-errors`, `dropped-files`, `tunnel-manager`, `odin-launcher`), static `startup.html` and `repair.html/js/css` |
| Backend link | `lib/backend.ts` (3,914 lines): URL discovery over a port range, token fetch, generation counters, health publishing |
| Settings | one 3,733-line route |
| Tests | Node test runner over Electron modules, many of which assert on source text; one Playwright shell spec |
| Packaging | `scripts/packaging/package-windows.ps1` (generates electron-builder config, NSIS, 3 isolated build attempts, robocopy publish), `generate-helper-manifest.cjs`, `audit-package-layout.cjs`, `installer.nsh` uninstall hook, packaged-startup benchmark |

## 3. Frontend concepts

- **Design system.** Flat warm-neutral tokens, hairline borders, Radix + Tailwind, `class-variance-authority` variants, a `product/` layer (`Feedback`, `Layout`, `Notifications`) above raw `ui/`. Already mirrored here (`components/product.tsx`, tokens in `styles/app.css`).
- **Polling.** `useVisiblePolling`: no overlapping runs, re-run requested while busy, AbortController, exponential backoff capped at 8×, 4× slower when hidden, refresh on focus/visibility. Our plan section 8.4 asks for the same; the hook is worth writing when a screen needs a timer beyond TanStack Query's `refetchInterval` (used today for running agents).
- **Loading / empty / error.** Root `errorComponent` and `notFoundComponent`, dedicated error page, `HealthStatusPanel`, feedback components. Ours: `ErrorState`, `EmptyState`, `Skeleton`, `NotFound`, per-panel failure isolation.
- **Persistence.** Only `localStorage`/`sessionStorage` for view preferences (home layout, dismissed items, popup position), each read wrapped in try/catch and parsed defensively; `homePreferences.ts` takes an injectable `Storage`. Same approach as our `lib/known.ts` and `lib/theme.ts`.
- **Accessibility.** ARIA attributes appear on most routes (about 150 across the app) but form-level `aria-invalid` / `aria-describedby` is sparse (14 uses); status announcements exist in `Notifications`. Ours is stricter: every field has a described-by hint or error, dialogs trap focus, statuses are text plus dot.
- **Logging.** `error-capture.ts` records the last window error for the server error page. Desktop side logs renderer `console-message`, `did-fail-load`, `render-process-gone`.
- **Weaknesses to avoid.** Three files above 2,000 lines, a token handed to the renderer, source-string tests, port-scanning URL discovery.

## 4. Electron concepts

### Worth adopting or already adopted
| Concept | CML | Status here |
| --- | --- | --- |
| `contextIsolation`, no `nodeIntegration`, `sandbox` | yes | yes (`webSecurity` also set) |
| Frameless window, sender-scoped window controls, one fixed state channel, callback receives only state | `window-controls.cjs` | yes |
| Popup denied, external opening through `shell.openExternal` | yes (allows `http`, `https`, `mailto`) | yes, stricter: `https` only |
| Title lock, hidden until ready, single-instance lock | yes | yes |
| Process-level `uncaughtException` / `unhandledRejection` logging | yes | yes |
| Runtime descriptor + loopback-only URL check | `runtime-descriptor.cjs` | yes (descriptor with PID, port, marker; stale-process reaper) |
| Backend child logs redacted to `userData/logs` | yes | yes |
| Isolated `userData` for tests | env var | yes (`CHANGE_ASSURANCE_USER_DATA_DIR`) |

### Not yet here; worth building
1. **Helper integrity at launch.** `helper-integrity.cjs` verifies every entry of a `helper-manifest.json` (SHA-256, regular file, not a symlink) before starting the bundled runtime; `generate-helper-manifest.cjs` builds it. We audit the stage at build time but do not verify at startup.
2. **Startup and repair pages that exist before React.** `startup.html` and `repair.html/js` are static, CSP-locked (`script-src 'self'`), show real phase text, and offer retry / open logs. We render repair state inside the renderer, so a renderer crash leaves a blank window.
3. **Versioned setup state.** `setup-state.cjs`: schema version, monotonically increasing `revision`, `expected_revision` compare-and-set, lock file with stale-lock expiry, atomic temp-write-and-rename, corrupt file quarantined as `*.corrupt-<ts>`. Our only persisted preference state is the renderer's theme, so this only becomes necessary if onboarding or a last-opened Change is added.
4. **Token at rest.** `token-store.cjs` keeps the token with `safeStorage` (`safe:v1:` prefix, 0600 file) or memory-only when encryption is unavailable. Our managed backend uses a per-session in-memory token, which is stricter; adopt only if a persistent token is ever needed.
5. **Uninstall hygiene.** `installer.nsh` runs `stop-installed-runtimes.ps1` on uninstall so only processes under the install root are stopped, and `smoke-windows-installer-recovery.ps1` tests reinstall while `app.asar` is locked. Needed for our NSIS target (plan 11.3).
6. **Packaging discipline.** Generated builder config in a temp dir, isolated output per attempt, retries, layout audit, published-artifact verification.
7. **Error-message cleanup.** `ipc-errors.cjs` strips Electron's `Error invoking remote method '...'` prefix so the user sees the real message. Ours returns structured `{ok:false,error}` instead, which already avoids it.

### CML practices we deliberately do not follow
| CML | Why not |
| --- | --- |
| `cml:get-backend-token` returns the API token to the renderer | Plan section 10 forbids it; ours keeps the token in main and proxies |
| No sender validation on IPC handlers | Ours checks `senderFrame.url` on every handler and tests it |
| Renderer-supplied paths accepted by `open-path`, `list-supported-files`, `read-local-image`, and `open-external` allows `http` | Ours takes no path or URL from the renderer except the exports dialog's suggested file name, which is reduced to a basename |
| Packaged renderer served by a random-port HTTP server | Ours uses a registered, containment-checked `app://` protocol |
| CSP `script-src 'self' 'unsafe-inline'`, `connect-src` to any loopback port | Ours: `script-src 'self'`, `connect-src 'none'` in the packaged origin |
| No permission handler | See gap below |
| No explicit application menu (menu bar only auto-hidden) | Same as ours; acceptable while frameless |
| Port-range scanning to find the backend | Ours allocates one free loopback port and verifies the process it started |

### Gaps in our own Electron layer found during this comparison
- ~~No permission handlers~~ **Done:** deny-all request and check handlers in `main.cjs`.
- ~~No page outside React when the renderer fails~~ **Done** (`electron/repair-page.cjs`, a script-free data page with bounded retries). A richer static startup page with phase text is still open.
- No startup helper hash verification (item 1).
- `target: dir` only; no NSIS target or uninstall helper yet (item 5).

## 5. Recommended order of adoption

1. Deny-all permission handlers (small, security).
2. Startup/repair static pages with the same CSP as `repair.html`.
3. Helper manifest generation in `stage-backend.mjs` plus verification in `backend-runtime.cjs` before spawn.
4. NSIS target with an uninstall hook scoped to the install root, and an installed-app lifecycle smoke.
5. Revisioned setup state, only when first-run onboarding is added.
6. Keep every source file small: none of our source files exceeds about 350 lines; CML's three 2,000+ line files are the main maintenance cost to avoid.
