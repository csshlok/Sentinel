# Sentinel desktop

The Windows desktop app (Electron + React) for the Sentinel Runtime. The renderer also runs in a plain browser for development.
It talks to the FastAPI backend over the authenticated `/api/v1` API and never sees the API token.

> Status: local, uncommitted work on the `frontend` branch. See `FRONTEND_PLAN_ADDENDUM.md` for decisions, limits and what is left,
> and SD's `FRONTEND_ELECTRON_IMPLEMENTATION_PLAN.md` for the overall plan.

## Run it

Requires Node 24, npm 11, Python 3.12+ with the backend dependencies (`pip install -e .` at the repo root), and Git on `PATH`.

```powershell
cd apps/desktop
npm ci

# 1. Backend (terminal A, from the repo root). The API token is written to .change-assurance/api_token on first start.
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 2a. Desktop app against that backend (terminal B). The main process reads the token file itself.
npm run dev:electron

# 2b. ...or the renderer in a browser at http://localhost:5173 (Vite proxies /api to :8000; paste the token in Settings).
npm run dev
```

Let the desktop app run its own backend instead: `npm run electron -- --manage-backend` (uses your `python`; data under Electron `userData/state`).

## Scripts

| Command | What it does |
| --- | --- |
| `npm run api:generate` / `api:check` | Generate `src/lib/api/generated/schema.ts` from the root `openapi.json`; `check` fails on drift |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Renderer unit tests + Electron module tests, including main-process behaviour, fuzz and stress (Node's built-in runner) |
| `npm run test:e2e` | Playwright: real-backend smoke plus a mocked-backend resilience suite (needs port 8000 free and Chrome). Fake backend: `e2e/fake-api.ts`, keep it faithful to `openapi.json` |
| `npm run build` | `api:check` + typecheck + Vite build |
| `npm run stage:backend` | Download Python 3.12 (embeddable), install runtime wheels, copy `backend/`, then audit the stage |
| `npm run package:dir` | Build + stage + `electron-builder --dir` into `release/win-unpacked` (unsigned, local) |

## Layout

```
src/
  app/            router (TanStack Router, code-based)
  components/     AppShell, WindowChrome, CommandPalette, product primitives, shadcn `ui/`
  features/       changes/, tools/, settings/
  services/       one file per API area: query options + mutations (components never call the transport)
  lib/api/        transport interface, Electron + browser transports, typed errors, generated schema
  lib/status.ts   lifecycle/review/risk/trust -> label + tone, time formatting
  styles/app.css  Tailwind v4 + design tokens + frameless-window chrome
electron/         main, preload, api-proxy, app-protocol, backend-runtime, runtime-descriptor, window-controls, logging, ...
electron/tests/   node:test suites for every module
e2e/              Playwright
scripts/          api generation, backend staging
```

## Adding a screen against a new endpoint

1. `npm run api:generate` after SD updates `openapi.json`.
2. Add a `queryOptions`/mutation in `src/services/<area>.ts` using `http.get/post/put` (paths are validated to `/api/v1/...`).
3. Build the screen from `components/product.tsx` (`Section`, `Facts`, `StatusLabel`, `EmptyState`, `Skeleton`, `DataTable`) and `ErrorState`.
   Always handle loading, empty, error (`ErrorState` maps auth/offline/timeout/server), and unsupported states. Never invent data.
4. Mutations send an `Idempotency-Key` (`newIdempotencyKey()`), one per unique submission; the backend requires at least 8 characters.

## Security model

- `contextIsolation`, `sandbox`, no `nodeIntegration`; popups and navigation denied; CSP on every `app://` response with `connect-src 'none'`.
- The main process owns the token. The renderer reaches the backend only through `api.request`, which allows `GET/POST/PUT/DELETE` on `/api/v1/` paths,
  ignores renderer headers, caps sizes, refuses redirects, and only talks to a loopback `http` URL.
- Bridge surface (`window.changeAssuranceDesktop`): `api.request`, `runtime.getStatus/restartBackend`, `repositories.selectFolder`,
  `windowControls.getState/minimize/toggleMaximize/close/onStateChanged`. Nothing else.
- Managed backend: random per-session token in memory, isolated data dir, loopback port, output redacted to `userData/logs/backend.log`.
  A crashed run's backend is reaped on next launch only when its PID, module and port all match. Logs: `userData/logs/desktop.log`.

## Environment variables

| Variable | Use |
| --- | --- |
| `CHANGE_ASSURANCE_API_URL` | External backend URL (default `http://127.0.0.1:8000`) |
| `CHANGE_ASSURANCE_DB_PATH` | Where the dev token file is looked up (`<dir>/api_token`) |
| `CHANGE_ASSURANCE_USER_DATA_DIR` | Isolated Electron profile for tests and smoke runs |
| `CHANGE_ASSURANCE_MANAGE_BACKEND=1` | Same as `--manage-backend` |
| `CHANGE_ASSURANCE_PYTHON` | Python used for a managed backend in development and for staging |

## Known limits

Windows x64 only; unsigned; no installer; read-only except for creating a Change. Full list in `FRONTEND_PLAN_ADDENDUM.md`.
