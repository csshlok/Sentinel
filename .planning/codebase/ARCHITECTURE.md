---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
<!-- refreshed: 2026-09-19 -->

# Architecture

**Analysis Date:** 2026-09-19

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                    HTTP Transport Layer                      │
│              `backend/app/core/router.py` (FastAPI)          │
└──────────────────────────┬────────────────────────────────────┘
                            │ calls
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               Use-Case / Service Layer                       │
│  `backend/app/core/change_service.py`                        │
│  `backend/app/core/review_service.py`                        │
│  `backend/app/core/lifecycle.py`                              │
│  `backend/app/core/capabilities.py`                           │
└───────┬───────────────┬───────────────┬───────────────┬──────┘
        │ depends on Protocol ports (contracts/ports.py)
        ▼               ▼               ▼               ▼
┌───────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────────────┐
│ Git Adapter    │ │ Verification│ │ Policy /    │ │ Providers /     │
│ `app/git/`     │ │ `app/       │ │ Credentials │ │ Outcomes/       │
│                │ │ verification│ │ `app/policy`│ │ Recovery/       │
│                │ │ /`          │ │ `app/       │ │ Passport        │
│                │ │             │ │ credentials`│ │ `app/providers` │
│                │ │             │ │ `app/       │ │ `app/outcomes`  │
│                │ │             │ │ identity`   │ │ `app/recovery`  │
│                │ │             │ │             │ │ `app/passport`  │
└────────┬───────┘ └──────┬──────┘ └──────┬──────┘ └────────┬────────┘
         │                │               │                 │
         ▼                ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│         Persistence / External Boundary                      │
│  SQLite via `backend/app/core/database.py`                   │
│  Windows Credential Store via `app/credentials/windows_store.py` │
│  Local Git working tree, subprocess execution                │
│  `app/execution/_process.py`, `app/execution/runner.py`      │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| HTTP router | Thin transport mapping HTTP requests to service calls | `backend/app/core/router.py` |
| App composition root | Wires adapters, middleware, exception handlers, FastAPI app | `backend/app/main.py` |
| ChangeService | Core "Change" use cases: create/list/get/update/transition/cancel | `backend/app/core/change_service.py` |
| ChangeRepository | SQLite-backed persistence for Change aggregate, idempotency replay | `backend/app/core/change_repository.py` |
| Lifecycle rules | Pure state-machine transition validation for Change lifecycle | `backend/app/core/lifecycle.py` |
| Review service | Determines review state given verification/lifecycle facts | `backend/app/core/review_service.py` |
| Capabilities | Reports which optional backend capabilities are configured/enabled | `backend/app/core/capabilities.py` |
| Contracts (models) | Pydantic data contracts shared across all modules | `backend/app/contracts/models.py` |
| Contracts (ports) | Frozen `Protocol` interfaces between core and adapters | `backend/app/contracts/ports.py` |
| Git adapter | Read-only Git working-tree inspection, checkpoint capture | `backend/app/git/adapter.py`, `backend/app/git/classifier.py` |
| Git recovery | Constrained, non-destructive Git recovery/compensation engine | `backend/app/recovery/git_recovery.py`, `backend/app/recovery/checkpoints.py` |
| Verification runner | Executes bounded verification commands as subprocesses | `backend/app/verification/runner.py`, `backend/app/verification/validation.py` |
| Execution primitives | Low-level subprocess execution helpers used by verification/providers | `backend/app/execution/_process.py`, `backend/app/execution/runner.py` |
| Identity | Actor/delegation model and authorization decisions | `backend/app/identity/service.py`, `backend/app/identity/models.py` |
| Policy engine | Pure, deterministic, default-deny policy evaluation | `backend/app/policy/engine.py`, `backend/app/policy/service.py` |
| Credential broker | Issues short-lived internal grants; sole boundary exposing durable secrets | `backend/app/credentials/broker.py` |
| Credential stores | Durable secret storage (Windows Credential Manager, in-memory for tests) | `backend/app/credentials/windows_store.py`, `backend/app/credentials/memory_store.py` |
| Providers | External provider (e.g. GitHub) operation execution via brokered grants | `backend/app/providers/github.py`, `backend/app/providers/http_transport.py` |
| Outcomes | Tracks provider outcomes tied to exact commit identities | `backend/app/outcomes/tracker.py`, `backend/app/outcomes/outcome_port.py` |
| Passport builder | Builds deterministic "Change Passport" from retained evidence | `backend/app/passport/builder.py` |
| Config | Environment-derived settings (DB path, UI origin, limits) | `backend/app/core/config.py` |
| Errors | Application error types mapped to HTTP error envelopes | `backend/app/core/errors.py` |
| Migrations | Ordered SQLite schema migrations | `backend/migrations/` |

## Pattern Overview

**Overall:** Ports-and-adapters (hexagonal) architecture with a FastAPI transport shell over a central `ChangeService` use-case layer. Cross-cutting subsystems (Git, verification, policy, credentials, providers, outcomes, recovery, passport) are independently owned modules that communicate with the core only through frozen `Protocol` interfaces defined in `backend/app/contracts/ports.py`.

**Key Characteristics:**

- Frozen contracts: `contracts/models.py` (Pydantic data) and `contracts/ports.py` (Protocol interfaces) form a stable boundary that lets modules (`git`, `policy`, `credentials`, `providers`, `recovery`, `passport`, `outcomes`, `verification`) be implemented independently against the same contract, evidenced by commit history (`AC: reconcile identity/policy/credentials/providers with frozen contracts`).
- Local-first, single-process app: SQLite database on local disk, no external services required to run; explicit "local-only" language in `main.py` docstring.
- Default-deny security posture: policy engine (`backend/app/policy/engine.py`) denies unless explicitly authorized; credential broker (`backend/app/credentials/broker.py`) is the sole boundary that can reveal a durable secret.
- Non-destructive Git operations: Git inspection and recovery modules are explicitly read-only / non-history-rewriting (see `recovery/git_recovery.py` docstring intent and `GitInspectionPort.inspect` "without mutating it").
- Idempotency-first mutation API: `ChangeService.create` and other mutating methods use an `Idempotency-Key` header and request-hash based replay via `ChangeRepository.replay`.

## Layers

**Transport (HTTP):**

- Purpose: Translate HTTP requests/responses to/from service calls; no business logic.
- Location: `backend/app/core/router.py`, `backend/app/main.py`
- Contains: FastAPI route handlers, exception handlers, CORS/middleware setup.
- Depends on: `ChangeService` (core layer) and `contracts/models.py` DTOs.
- Used by: External HTTP clients / local UI.

**Core / Use-Case:**

- Purpose: Orchestrate Change lifecycle, review state, capabilities, and idempotent request handling.
- Location: `backend/app/core/`
- Contains: `change_service.py`, `change_repository.py`, `lifecycle.py`, `review_service.py`, `capabilities.py`, `config.py`, `database.py`, `errors.py`, `unavailable_adapters.py`.
- Depends on: `contracts/ports.py` Protocols (injected adapters), `contracts/models.py`.
- Used by: Transport layer (`router.py`), tests.

**Contracts (Shared Kernel):**

- Purpose: Define the frozen data models and Protocol interfaces every module programs against.
- Location: `backend/app/contracts/`
- Contains: `models.py` (Pydantic request/response/domain models), `ports.py` (Protocol definitions: `GitInspectionPort`, `VerificationPort`, `PolicyPort`, `CredentialBrokerPort`, `ProviderPort`, `OutcomePort`, `RecoveryPort`, `PassportPort`, etc.).
- Depends on: Nothing internal (pure data/interfaces).
- Used by: Every other module.

**Domain Adapters (independently owned modules):**

- Purpose: Each implements one or more ports against a specific domain concern.
- Location: `backend/app/git/`, `backend/app/verification/`, `backend/app/policy/`, `backend/app/identity/`, `backend/app/credentials/`, `backend/app/providers/`, `backend/app/outcomes/`, `backend/app/recovery/`, `backend/app/passport/`, `backend/app/execution/`.
- Depends on: `contracts/`, `execution/` (for subprocess-based adapters), each module's own `models.py`/`errors.py`.
- Used by: `core/change_service.py` (via injected ports) and `main.py` composition root.

**Persistence:**

- Purpose: Durable storage for Change aggregates and schema versioning.
- Location: `backend/app/core/database.py`, `backend/migrations/`
- Contains: SQLite connection management, migration runner.
- Depends on: `sqlite3` stdlib.
- Used by: `ChangeRepository`.

## Data Flow

### Primary Request Path (Change lifecycle)

1. HTTP request hits a route in `build_router` (`backend/app/core/router.py:36`), e.g. `POST /api/v1/changes`.
2. Route handler calls `ChangeService.create` (`backend/app/core/change_service.py:71`), passing the optional `Idempotency-Key`.
3. `ChangeService` checks for a replayed request via `ChangeRepository.replay` (`backend/app/core/change_repository.py`), then calls the injected `GitInspectionPort.validate_repository` (`backend/app/git/adapter.py`) to resolve the canonical repo root.
4. `ChangeService` persists a `StoredChange` via `ChangeRepository.create`, converts it to a `ChangeView` DTO (`_to_view`), and returns it up through the router as the HTTP response.

### Verification / Policy-Gated Operation Flow

1. A transition or operation request enters via `ChangeService` (`backend/app/core/change_service.py`).
2. Policy is evaluated through `PolicyPort.evaluate` (`backend/app/policy/engine.py`), which is pure and default-deny, checking `identity`'s `AuthorizationDecision` first.
3. If authorized, a short-lived grant is issued by `CredentialBrokerPort.issue_grant` (`backend/app/credentials/broker.py`), scoped and time-boxed.
4. The `ProviderPort.execute` implementation (`backend/app/providers/github.py`) performs the external operation using only the grant, never the raw secret.
5. Results are recorded and reconciled via `OutcomePort.refresh` (`backend/app/outcomes/tracker.py`), tied to exact commit identities.

**State Management:**

- Change lifecycle state is persisted in SQLite (`backend/app/core/database.py`) and mutated only through `ChangeRepository`/`ChangeService`, validated by pure functions in `backend/app/core/lifecycle.py`.
- No in-memory global mutable state for Change data; each service call reads/writes through the repository.
- Credential grants carry their own state (issued/expired/revoked) managed entirely inside `backend/app/credentials/broker.py`.

## Key Abstractions

**Port (Protocol):**

- Purpose: Frozen interface boundary allowing independent module implementation and test substitution.
- Examples: `backend/app/contracts/ports.py` (`GitInspectionPort`, `VerificationPort`, `PolicyPort`, `CredentialBrokerPort`, `ProviderPort`, `RecoveryPort`, `PassportPort`, `OutcomePort`, `AssurancePort`, `EnvironmentPort`, `DependencyPort`, `AgentLauncherPort`, `LifecycleFactsPort`, `GitStatePort`, `CredentialStorePort`).
- Pattern: `typing.Protocol` with `@runtime_checkable`, implemented by concrete adapters and swappable via constructor injection in `create_app` (`backend/app/main.py:47`).

**ChangeView / StoredChange:**

- Purpose: Separate wire-facing DTO (`ChangeView`, Pydantic, in `contracts/models.py`) from persistence-facing internal record (`StoredChange`, in `change_repository.py`).
- Examples: `backend/app/core/change_repository.py`, `backend/app/core/change_service.py` (`_to_view`).
- Pattern: Repository returns internal dataclass; service maps to public contract model before returning to transport.

**Idempotency Replay:**

- Purpose: Safe retries of mutating operations using client-supplied `Idempotency-Key` plus a hash of the request body.
- Examples: `backend/app/core/change_repository.py` (`replay`), `backend/app/core/change_service.py` (`_request_hash`, `create`).
- Pattern: Look up prior stored result by key+hash before performing a new write.

## Entry Points

**FastAPI app / HTTP server:**

- Location: `backend/app/main.py` (`create_app()`, module-level `app`)
- Triggers: `uvicorn backend.app.main:app` (or equivalent process manager)
- Responsibilities: Wire adapters (Git, verification, lifecycle facts) behind ports, register exception handlers and CORS, mount router, initialize SQLite on lifespan startup.

**HTTP Router:**

- Location: `backend/app/core/router.py` (`build_router(service)`)
- Triggers: Called once from `create_app`
- Responsibilities: Define all `/api/v1/*` routes (`capabilities`, `repositories/validate`, `changes` CRUD/lifecycle).

**Test Suite:**

- Location: `backend/tests/` (acceptance, core, credentials, execution, git, identity, integration, outcomes, passport, policy, providers, recovery, verification subdirectories)
- Triggers: `pytest` (configured via `pyproject.toml`, `testpaths = ["backend/tests"]`)
- Responsibilities: Verify each module against frozen contracts, including acceptance-criteria (`AC-*`) tests matching the module set (git recovery, passport builder, policy engine, credential broker, providers, outcomes).

## Architectural Constraints

- **Threading:** Single-process ASGI app (FastAPI/uvicorn); verification and provider calls run as subprocesses via `backend/app/execution/_process.py` rather than threads — no shared-memory concurrency model in the core.
- **Global state:** Module-level `app = create_app()` singleton in `backend/app/main.py:133`; SQLite `Database` instance is held on `app.state.database` per process rather than as an ambient global.
- **Circular imports:** None observed; dependency direction is strictly transport → core → contracts ← domain adapters, with domain adapters never importing `core`.
- **Non-destructive Git:** Recovery and inspection modules are constrained to avoid Git history rewriting — enforced by design/docstrings in `backend/app/recovery/git_recovery.py` and `backend/app/git/adapter.py`, not by a runtime guard; violating this in new code would break a core project invariant.
- **Secret boundary:** Only `backend/app/credentials/broker.py` may read a durable secret from a `CredentialStorePort`; no other module should call `CredentialStorePort.get` directly.

## Anti-Patterns

### Bypassing the port/contract boundary

**What happens:** A domain module (e.g. `providers`) importing directly from another domain module (e.g. `git` or `credentials` internals) instead of going through `contracts/ports.py`.
**Why it's wrong:** Breaks the "frozen contracts" design that lets modules be implemented and tested independently (see commit `AC: reconcile identity/policy/credentials/providers with frozen contracts`), and creates hidden coupling that ports were introduced to prevent.
**Do this instead:** New cross-module calls should be added as a `Protocol` method in `backend/app/contracts/ports.py` and consumed via constructor-injected dependencies in `backend/app/core/change_service.py` / `backend/app/main.py`.

### Reading secrets outside the credential broker

**What happens:** Calling a `CredentialStorePort` implementation (e.g. `windows_store.py`) directly from a provider or use-case instead of going through `CredentialBrokerPort.issue_grant`/`resolve_secret`.
**Why it's wrong:** Violates the explicit single-boundary secret exposure guarantee documented in `backend/app/credentials/broker.py`, undermining the security model.
**Do this instead:** Always obtain a scoped, time-boxed `CredentialGrant` from `CredentialBrokerPort` and pass that grant into `ProviderPort.execute`, never the raw secret.

## Error Handling

**Strategy:** Centralized exception handling at the FastAPI app level converts domain errors into a consistent JSON error envelope.

**Patterns:**

- Domain/application errors raise `AppError` subclasses (`backend/app/core/errors.py`) carrying `code`, `message`, `status_code`, `details`; caught globally by `handle_app_error` in `backend/app/main.py:85`.
- Request validation errors (`RequestValidationError`) are caught and reshaped into a redacted `errors` list (`backend/app/main.py:94`) to avoid leaking raw Pydantic internals.
- Unhandled exceptions are caught by a catch-all handler (`backend/app/main.py:113`), logged via `LOGGER.exception`, and returned as a generic `INTERNAL_ERROR` 500 without leaking details.
- Module-specific error factories exist per domain (`backend/app/git/errors.py`, `backend/app/policy` uses `PolicyDenialReason`, `backend/app/credentials/errors.py`, `backend/app/providers/errors.py`, `backend/app/recovery/errors.py`, `backend/app/verification/errors.py`, `backend/app/identity/errors.py`) so each adapter raises typed errors mapped back to `AppError`.

## Cross-Cutting Concerns

**Logging:** Standard library `logging` module, one logger per file via `logging.getLogger(__name__)` (see `backend/app/main.py:31`); unexpected errors logged with full traceback via `LOGGER.exception`.
**Validation:** Pydantic v2 models in `backend/app/contracts/models.py` validate all request/response shapes at the FastAPI boundary; domain-specific validation (e.g. policy forbidden paths, verification command allowlists) lives in each module (`backend/app/policy/engine.py`, `backend/app/verification/validation.py`).
**Authentication/Authorization:** Handled via the `identity` module's `AuthorizationDecision` model plus the `policy` engine's default-deny evaluation (`backend/app/policy/engine.py`); the app itself is local-first and does not implement network-facing user auth (CORS locked to a single `ui_origin` from `Settings`).

---

*Architecture analysis: 2026-09-19*
