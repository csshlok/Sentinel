---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
# External Integrations

**Analysis Date:** 2026-09-19

## APIs & External Services

**Source Control Hosting:**

- GitHub REST API (`https://api.github.com`) - `backend/app/providers/github.py`
  - Client: hand-rolled `GitHubProvider` class using stdlib `urllib` via `UrllibHttpTransport` (`backend/app/providers/http_transport.py`), no `PyGithub`/`octokit` SDK
  - Auth: Bearer token passed per-call, never read from storage by this module (see Authentication section) — header `Authorization: Bearer {token}` set in `GitHubProvider._request`
  - Endpoints used:
    - `POST /repos/{repository}/pulls` - create/refresh a draft pull request (`create_or_refresh_pull_request`)
    - `GET /repos/{repository}/commits/{head_sha}/check-runs` - paginated (`per_page=50`) check-run polling (`list_check_runs_for_sha`)
  - Resilience: retries on timeout, 429 (honors `Retry-After` header), and 5xx with exponential backoff (`_backoff_seconds`, capped at 30s, `max_retries=3` default); maps 401/403 → auth failed, 404 → not found, 409 → conflict, 422 → validation failed
  - Idempotency: in-memory `_pr_cache` keyed by caller-supplied `idempotency_key` to avoid duplicate PR creation

## Data Storage

**Databases:**

- SQLite (file-based, embedded) - `backend/app/core/database.py`
  - Connection: path resolved from `CHANGE_ASSURANCE_DB_PATH` env var (default `.change-assurance/change_assurance.sqlite3` relative to cwd), configured in `backend/app/core/config.py`
  - Client: stdlib `sqlite3` directly, no ORM/query builder
  - Pragmas: `foreign_keys = ON`, `busy_timeout = 5000`, `journal_mode = WAL`
  - Transactions: explicit `BEGIN` / `BEGIN IMMEDIATE`, commit/rollback wrapped in `Database.connection()` context manager
  - Migrations: ordered, versioned migrations applied at startup via `backend/migrations/versions.py`, tracked in a `schema_migrations` table; refuses to start if DB schema version exceeds `LATEST_SCHEMA_VERSION`

**File Storage:**

- Local filesystem only — no object storage/cloud storage integration detected. Git repository working trees are inspected/mutated directly on disk via `backend/app/git/adapter.py`.

**Caching:**

- None as a distinct service. In-process caching only: `GitHubProvider._pr_cache` (dict, per-process, per-idempotency-key) in `backend/app/providers/github.py`.

## Authentication & Identity

**Auth Provider:**

- No end-user auth/OIDC/SSO provider — this is a local-only backend (see `backend/app/main.py` docstring), not exposed beyond `localhost`.
- Credential broker pattern for outbound provider secrets (e.g., GitHub tokens):
  - `backend/app/credentials/broker.py` - `CredentialBroker`, resolves secrets from a pluggable `CredentialStorePort`
  - `backend/app/credentials/windows_store.py` - `WindowsCredentialStore`, production implementation backed by Windows Credential Manager (`advapi32.dll` via `ctypes`), namespaced under target prefix `ChangeAssuranceRuntime`
  - `backend/app/credentials/memory_store.py` - in-memory implementation (tests / non-Windows fallback)
  - Design constraint: provider adapters (e.g. `GitHubProvider`) never read the credential store or log tokens directly — tokens are resolved by the broker and passed in as call arguments (documented in `backend/app/providers/github.py:1-6`)

## Monitoring & Observability

**Error Tracking:**

- None (no Sentry/Bugsnag/etc.). Errors are caught by FastAPI exception handlers in `backend/app/main.py` and returned as a structured `ErrorEnvelope` JSON body; unexpected exceptions are logged via stdlib `logging` (`LOGGER.exception(...)`) but not shipped anywhere external.

**Logs:**

- Python stdlib `logging` module only, local process logs (`logging.getLogger(__name__)` in `backend/app/main.py`). No log aggregation/shipping integration detected.

## CI/CD & Deployment

**Hosting:**

- None detected — local-first application, no deployment target/manifest files (no `Dockerfile`, `docker-compose.yml`, `Procfile`, cloud IaC, or CI workflow files found in this checkout).

**CI Pipeline:**

- None detected — no `.github/workflows/`, `.gitlab-ci.yml`, or equivalent CI config found in this repository.

## Environment Configuration

**Required env vars:**

- `CHANGE_ASSURANCE_DB_PATH` - optional, overrides SQLite file path (`backend/app/core/config.py`)
- `CHANGE_ASSURANCE_UI_ORIGIN` - optional, overrides the single allowed CORS origin for the (not-yet-present) frontend (default `http://localhost:5173`)
- No API keys/tokens are read directly from environment variables in the code inspected — provider tokens (e.g. GitHub) flow exclusively through the Windows Credential Manager-backed `CredentialBroker`, not env vars.

**Secrets location:**

- Windows Credential Manager, namespaced `ChangeAssuranceRuntime:{key}` (`backend/app/credentials/windows_store.py`) — not `.env` files, not committed config. No secrets are present in this repository.

## Webhooks & Callbacks

**Incoming:**

- None — the FastAPI app exposes only `changes`, `repositories`, `capabilities`, and `health` REST endpoints under `/api/v1` (`backend/app/core/router.py`); no webhook receiver endpoints found.

**Outgoing:**

- None — GitHub integration is poll-based (creates PRs, then polls check-run status via `list_check_runs_for_sha`); no outbound webhook dispatch found.

---

*Integration audit: 2026-09-19*
