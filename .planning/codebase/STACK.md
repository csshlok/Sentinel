---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
# Technology Stack

**Analysis Date:** 2026-09-19

## Languages

**Primary:**

- Python 3.12+ - Entire backend (`backend/app/`), `requires-python = ">=3.12"` in `pyproject.toml`. Uses modern syntax throughout (`from __future__ import annotations`, `dataclass(slots=True)`, `X | None` unions, `match`-free structural code).

**Secondary:**

- None detected — no frontend/UI source tree exists yet in this repo (no `frontend/`, `ui/`, `package.json`, or `.tsx`/`.jsx` files found). The default CORS origin `http://localhost:5173` (`backend/app/core/config.py:13`) implies a planned Vite-based frontend that has not landed in this checkout yet.

## Runtime

**Environment:**

- CPython 3.12+ (no interpreter pin file such as `.python-version` found)
- Windows-targeted: `backend/app/credentials/windows_store.py` binds directly to `advapi32.dll` via `ctypes` for Windows Credential Manager — this codebase is Windows-only for credential storage.

**Package Manager:**

- `pip` / `setuptools` via `pyproject.toml` (setuptools build backend, `setuptools>=75`)
- Lockfile: missing (no `requirements.txt`, `poetry.lock`, or `uv.lock` — dependencies pinned only by range in `pyproject.toml`)
- Editable install artifacts present: `change_assurance.egg-info/`

## Frameworks

**Core:**

- FastAPI `>=0.115,<1` - HTTP API framework, composition root in `backend/app/main.py`
- Pydantic `>=2.10,<3` - request/response models and validation, `backend/app/contracts/models.py`
- Uvicorn `[standard] >=0.34,<1` - ASGI server (dev/run target, referenced as extra dependency; no explicit `uvicorn.run()` call found in this checkout — likely invoked via CLI)

**Testing:**

- pytest `>=8.3,<9` - test runner, config in `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]`)
- pytest-cov `>=6,<8` - coverage reporting
- httpx `>=0.28,<1` - test HTTP client for FastAPI (used with `TestClient`/`ASGITransport` patterns in `backend/tests/`)

**Build/Dev:**

- `setuptools` (`build-backend = "setuptools.build_meta"`) - packaging, packages discovered via `[tool.setuptools.packages.find] include = ["backend*"]`

## Key Dependencies

**Critical:**

- `fastapi` - all HTTP routing (`backend/app/core/router.py`), exception handling, CORS middleware (`backend/app/main.py`)
- `pydantic` - typed contracts for every API request/response (`backend/app/contracts/models.py`), and frozen dataclasses elsewhere use plain `dataclasses` (not Pydantic) for internal domain models

**Infrastructure:**

- `sqlite3` (Python stdlib) - sole persistence layer, no ORM. `backend/app/core/database.py` manages WAL mode, foreign keys, ordered migrations (`backend/migrations/versions.py`)
- `urllib` (stdlib) - sole HTTP client for outbound calls, no `requests`/`httpx` runtime dependency. `backend/app/providers/http_transport.py` implements `UrllibHttpTransport` behind an `HttpTransport` Protocol seam so tests substitute a fake transport
- `ctypes` (stdlib) - direct Win32 API bindings for credential storage, `backend/app/credentials/windows_store.py` (explicitly avoids adding `keyring`/`pywin32` per `AGENT_COORDINATION.md`)
- `subprocess` (stdlib, inferred) - process execution for verification/Git commands via `backend/app/execution/_process.py`, `backend/app/execution/runner.py`, `backend/app/verification/runner.py` (`SubprocessVerificationRunner`)

## Configuration

**Environment:**

- `backend/app/core/config.py` — frozen `Settings` dataclass loaded via `Settings.from_environment()`
- Env vars:
  - `CHANGE_ASSURANCE_DB_PATH` - SQLite file location (default `.change-assurance/change_assurance.sqlite3` under cwd)
  - `CHANGE_ASSURANCE_UI_ORIGIN` - single allowed CORS origin (default `http://localhost:5173`)
- Other settings are compile-time defaults on `Settings` (not env-driven): `patch_limit_bytes` (1 MiB), `verification_output_limit_bytes` (256 KiB), `list_limit` (100)
- No `.env` file present in this checkout; no secrets committed (`.gitignore` excludes `.change-assurance/`, `*.sqlite3`, `.venv/`, caches)

**Build:**

- `pyproject.toml` - single source of truth for dependencies, pytest config, and packaging
- No linter/formatter config file present in this checkout (`.ruff_cache/` is gitignored, implying `ruff` is used locally but has no committed config found)

## Platform Requirements

**Development:**

- Python 3.12+
- Windows OS (credential storage implementation is Windows-only via `advapi32.dll`; `backend/app/credentials/memory_store.py` provides an in-memory fallback used in tests/non-Windows contexts)
- Git installed and on PATH (backend shells out to Git via `backend/app/git/adapter.py` and `backend/app/recovery/git_recovery.py`)

**Production:**

- Local-first desktop/companion service — FastAPI app is explicitly documented as "local-only" (`backend/app/main.py:1` docstring: "FastAPI composition root for the local-only Change Assurance API")
- SQLite as the only datastore (file-based, no external DB server)
- No containerization files (no `Dockerfile`/`docker-compose.yml`) or cloud deployment manifests found

---

*Stack analysis: 2026-09-19*
