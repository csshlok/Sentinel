---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
# Codebase Structure

**Analysis Date:** 2026-09-19

## Directory Layout

```
vthacks14/
├── backend/                      # Python backend application (all runtime code)
│   ├── app/                      # Application source ("change_assurance" package root)
│   │   ├── contracts/            # Frozen shared models + Protocol ports
│   │   ├── core/                 # Composition root, use cases, HTTP router, DB, config
│   │   ├── credentials/          # Credential broker + secret stores (Windows/memory)
│   │   ├── execution/            # Low-level subprocess execution helpers
│   │   ├── git/                  # Read-only Git working-tree inspection/classification
│   │   ├── identity/             # Actor/delegation identity + authorization model
│   │   ├── outcomes/             # Provider outcome tracking tied to commit identity
│   │   ├── passport/             # Change Passport (evidence bundle) builder
│   │   ├── policy/                # Pure, default-deny policy evaluation engine
│   │   ├── providers/            # External provider integrations (e.g. GitHub)
│   │   ├── recovery/             # Constrained, non-destructive Git recovery engine
│   │   ├── verification/         # Bounded subprocess-based verification runner
│   │   ├── __init__.py
│   │   └── main.py               # FastAPI composition root / app entry point
│   ├── migrations/                # Ordered SQLite schema migrations
│   └── tests/                     # Pytest suite, mirrors `app/` module layout + acceptance/integration
│       ├── acceptance/            # AC-* acceptance criteria tests
│       ├── integration/           # Cross-module integration tests
│       └── <module>/              # One test subdir per app module (core, git, policy, ...)
├── .change-assurance/             # Runtime/tooling data directory for this project's own tool (local state)
├── .planning/                     # GSD planning artifacts (this document lives here)
├── .playwright-cli/                # Playwright CLI local state (likely UI/browser testing tooling)
├── .pytest_cache/                  # Pytest cache (generated, not committed content of interest)
├── change_assurance.egg-info/     # Generated Python packaging metadata (setuptools editable install)
├── pyproject.toml                  # Python project/build config, dependencies, pytest config
├── AGENT_COORDINATION.md           # Multi-agent build coordination notes
├── BACKEND_IMPLEMENTATION_PLAN.md  # Backend implementation plan document
├── OVERALL_CONTEXT.md              # Project-wide context document
├── PROJECT_CONTEXT.md              # Project context document
└── Change_Assurance_Runtime_Project_Proposal (2).pdf  # Original project proposal
```

Note: No separate frontend/UI source directory was found under the repo root at time of analysis; the app currently exposes only the `backend/` FastAPI service. `Settings.ui_origin` (see `backend/app/core/config.py`) implies a UI is expected to consume this API from a configured origin, but its source is not present in this repo.

## Directory Purposes

**`backend/app/contracts/`:**

- Purpose: Single source of truth for cross-module data shapes and interface boundaries.
- Contains: `models.py` (Pydantic DTOs/domain models: `ChangeView`, `GitSummary`, `PolicyDecision`, `CredentialGrant`, etc.), `ports.py` (Protocol interfaces every adapter implements).
- Key files: `backend/app/contracts/models.py`, `backend/app/contracts/ports.py`

**`backend/app/core/`:**

- Purpose: Application composition root and Change use-case orchestration.
- Contains: FastAPI app factory, HTTP router, SQLite database wrapper, settings, lifecycle rules, error types.
- Key files: `backend/app/main.py`, `backend/app/core/router.py`, `backend/app/core/change_service.py`, `backend/app/core/change_repository.py`, `backend/app/core/database.py`, `backend/app/core/config.py`, `backend/app/core/lifecycle.py`, `backend/app/core/review_service.py`, `backend/app/core/capabilities.py`, `backend/app/core/errors.py`, `backend/app/core/unavailable_adapters.py`

**`backend/app/git/`:**

- Purpose: Read-only inspection of the local Git working tree; classifies changes without mutating repo state.
- Contains: `adapter.py` (implements `GitInspectionPort`), `classifier.py`, `errors.py`, `KB_HANDOFF.md` (module-specific knowledge-base handoff notes).
- Key files: `backend/app/git/adapter.py`, `backend/app/git/classifier.py`

**`backend/app/recovery/`:**

- Purpose: Constrained recovery/compensation engine for Git state, explicitly non-destructive (no history rewriting).
- Contains: `git_recovery.py`, `checkpoints.py`, `errors.py`.
- Key files: `backend/app/recovery/git_recovery.py`, `backend/app/recovery/checkpoints.py`

**`backend/app/verification/`:**

- Purpose: Runs bounded, allowlisted verification commands (e.g. test/lint commands) as subprocesses and captures results.
- Contains: `runner.py` (implements `VerificationPort`), `validation.py`, `errors.py`.
- Key files: `backend/app/verification/runner.py`, `backend/app/verification/validation.py`

**`backend/app/execution/`:**

- Purpose: Shared low-level subprocess execution primitives reused by verification and provider modules.
- Contains: `_process.py` (private process-spawning helper), `runner.py`.
- Key files: `backend/app/execution/_process.py`, `backend/app/execution/runner.py`

**`backend/app/identity/`:**

- Purpose: Actor and delegation model; produces `AuthorizationDecision`s consumed first by the policy engine.
- Contains: `service.py`, `repository.py`, `models.py`, `errors.py`.
- Key files: `backend/app/identity/service.py`, `backend/app/identity/models.py`

**`backend/app/policy/`:**

- Purpose: Pure, deterministic, default-deny policy evaluation over identity authorization + operation parameters.
- Contains: `engine.py` (pure evaluation logic, no I/O), `service.py`, `models.py`.
- Key files: `backend/app/policy/engine.py`, `backend/app/policy/models.py`

**`backend/app/credentials/`:**

- Purpose: Issues short-lived internal capability grants; sole boundary through which a durable secret may be resolved.
- Contains: `broker.py` (implements `CredentialBrokerPort`), `windows_store.py` (Windows Credential Manager-backed `CredentialStorePort`), `memory_store.py` (in-memory store for tests), `models.py`, `errors.py`.
- Key files: `backend/app/credentials/broker.py`, `backend/app/credentials/windows_store.py`

**`backend/app/providers/`:**

- Purpose: Executes brokered operations against external providers (currently GitHub).
- Contains: `github.py` (implements `ProviderPort`), `http_transport.py`, `repository_slug.py`, `models.py`, `errors.py`.
- Key files: `backend/app/providers/github.py`, `backend/app/providers/http_transport.py`

**`backend/app/outcomes/`:**

- Purpose: Tracks and refreshes provider outcomes tied to exact commit identities.
- Contains: `tracker.py` (implements `OutcomePort`), `outcome_port.py`.
- Key files: `backend/app/outcomes/tracker.py`

**`backend/app/passport/`:**

- Purpose: Builds a deterministic "Change Passport" evidence bundle from retained evidence across other modules.
- Contains: `builder.py` (implements `PassportPort`).
- Key files: `backend/app/passport/builder.py`

**`backend/migrations/`:**

- Purpose: Ordered SQLite schema migrations applied at app startup.
- Contains: Migration definitions and `LATEST_SCHEMA_VERSION`/`MIGRATIONS` exports consumed by `backend/app/core/database.py`.

**`backend/tests/`:**

- Purpose: Pytest suite mirroring the `app/` module structure, plus dedicated `acceptance/` and `integration/` suites.
- Contains: One subdirectory per domain module (`core`, `credentials`, `execution`, `git`, `identity`, `outcomes`, `passport`, `policy`, `providers`, `recovery`, `verification`), `acceptance/` for AC-numbered criteria tests, `integration/` for cross-module flows.

**`.change-assurance/`:**

- Purpose: Local runtime/tooling state directory for this project's own change-assurance tool (self-hosting/dogfooding artifact), not application source.

## Key File Locations

**Entry Points:**

- `backend/app/main.py`: FastAPI app factory (`create_app`) and module-level `app` instance for ASGI servers.

**Configuration:**

- `backend/app/core/config.py`: `Settings` class — database path, UI origin, byte/size limits, environment-derived config.
- `pyproject.toml`: Build system, dependencies (`fastapi`, `pydantic`, `uvicorn`), test dependencies, pytest configuration (`testpaths = ["backend/tests"]`).

**Core Logic:**

- `backend/app/core/change_service.py`: Central Change use-case orchestration (create/list/get/update/transition/cancel, idempotency).
- `backend/app/contracts/ports.py`: All Protocol interface definitions — the architectural contract boundary.
- `backend/app/contracts/models.py`: All shared Pydantic data models.

**Testing:**

- `backend/tests/`: Full pytest suite; run via `pytest` from repo root (uses `pythonpath = ["."]`).
- `backend/tests/acceptance/`: Acceptance-criteria-driven tests (AC-1 through AC-5+, matching commit history like "AC: implement Change Passport builder (AC-5)").

## Naming Conventions

**Files:**

- One module per concern, named for its responsibility (`adapter.py`, `builder.py`, `broker.py`, `engine.py`, `tracker.py`, `runner.py`).
- Error types isolated in a dedicated `errors.py` per module (consistent across `git`, `credentials`, `providers`, `recovery`, `verification`, `identity`, `policy`... note `policy` and `outcomes` keep errors inline or in `models.py`/omit if unneeded).
- Domain data models isolated in `models.py` per module when the module has adapter-specific types beyond the shared `contracts/models.py`.
- Private/internal-only helper modules prefixed with underscore (e.g. `backend/app/execution/_process.py`).

**Directories:**

- Each top-level directory under `backend/app/` corresponds to exactly one bounded domain/module aligned with a Protocol port group in `contracts/ports.py` (e.g. `git/` ↔ `GitInspectionPort`/`GitStatePort`, `credentials/` ↔ `CredentialBrokerPort`/`CredentialStorePort`).
- Test directories under `backend/tests/` mirror `backend/app/` module names 1:1, plus two cross-cutting additions: `acceptance/` and `integration/`.

## Where to Add New Code

**New Feature (new bounded domain/module, e.g. a new provider or analysis capability):**

- Define any new cross-module interface as a `Protocol` in `backend/app/contracts/ports.py` and any new shared DTOs in `backend/app/contracts/models.py` first.
- Implementation: New directory under `backend/app/<module_name>/` following the existing per-module pattern (`models.py` for module-local types, `errors.py` for module-local errors, one primary implementation file implementing the port).
- Wire the new adapter into `backend/app/main.py` (`create_app`) as an injectable dependency, and into `backend/app/core/change_service.py` if it participates in Change use cases.
- Tests: `backend/tests/<module_name>/`, plus an `acceptance/` test if the feature maps to a numbered acceptance criterion (`AC-N`).

**New HTTP endpoint:**

- Add the route inside `build_router` in `backend/app/core/router.py`, delegating immediately to a method on `ChangeService` (or a new service) — keep the router free of business logic.
- Add/extend request/response models in `backend/app/contracts/models.py`.

**New Change use case:**

- Add a method to `backend/app/core/change_service.py`, following the existing pattern of idempotency-aware, repository-backed operations.

**Utilities:**

- Shared subprocess execution helpers: `backend/app/execution/`.
- Module-local helpers stay inside that module's directory; avoid a generic catch-all `utils/` directory (none currently exists — keep it that way to preserve module boundaries).

## Special Directories

**`.change-assurance/`:**

- Purpose: Local runtime data for the project's own self-hosted change-assurance tooling.
- Generated: Yes
- Committed: Unknown — treat as local state; verify against `.gitignore` before assuming it is tracked.

**`.pytest_cache/`:**

- Purpose: Pytest's internal cache directory.
- Generated: Yes
- Committed: No (standard pytest cache, typically gitignored)

**`change_assurance.egg-info/`:**

- Purpose: Generated Python packaging metadata from an editable/setuptools install.
- Generated: Yes
- Committed: No (build artifact)

**`.playwright-cli/`:**

- Purpose: Local state for the Playwright CLI, suggesting browser-based UI testing tooling is used or planned.
- Generated: Yes
- Committed: No (local tool state)

**`backend/migrations/`:**

- Purpose: Ordered, versioned SQLite schema migrations.
- Generated: No (hand-authored)
- Committed: Yes

---

*Structure analysis: 2026-09-19*
