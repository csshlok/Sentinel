---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
# Coding Conventions

**Analysis Date:** 2026-09-19

## Naming Patterns

**Files:**

- Lowercase snake_case module names, one primary responsibility per file: `engine.py` (pure evaluation logic), `models.py` (pydantic domain models), `service.py` (I/O-bound orchestration), `repository.py` (persistence), `router.py` (FastAPI routes), `ports.py` (interfaces/protocols), `errors.py` (error factory functions).
- Example: `backend/app/policy/{engine,models,service}.py`, `backend/app/core/{change_repository,change_service,lifecycle,errors,database}.py`

**Functions:**

- snake_case, verb-first: `evaluate()`, `_path_is_forbidden()`, `change_not_found()`, `revision_conflict()`.
- Private/internal helpers prefixed with a single leading underscore: `_path_is_forbidden`, `_engine`, `_change`, `_delegate` (also used in tests for local builder helpers).
- Error-factory functions return an `AppError` instance rather than raising directly, named after the condition they represent (`change_not_found`, `adapter_unavailable`, `revision_conflict`, `idempotency_conflict`, `invalid_transition`, `transition_guard_failed`) — see `backend/app/core/errors.py`.

**Variables:**

- snake_case throughout; short-lived locals (`decision`, `view`, `now`) favored over abbreviations.

**Types:**

- PascalCase for classes and Pydantic models: `PolicyDecision`, `ChangeContract`, `ChangeView`, `AuthorizationDecision`, `DelegationPolicyEngine`.
- Enums use `StrEnum` with SCREAMING_SNAKE_CASE members: `PolicyOperation.PROVIDER_FORCE_PUSH`, `RiskLevel.HIGH`, `PolicyDenialReason.AUTHORITY_DENIED` — see `backend/app/policy/models.py`.

## Code Style

**Formatting:**

- No formatter config detected (no `.prettierrc`, no `ruff.toml`/`pyproject` `[tool.ruff]` section, no `.flake8`). Style is consistent by convention rather than enforced tooling: 4-space indent, double quotes, trailing commas in multi-line calls.

**Linting:**

- No lint tool config found in `pyproject.toml` or repo root. Rely on type hints and pydantic validation instead of a linter.

**Type hints:**

- `from __future__ import annotations` at the top of nearly every module.
- Full type annotations on all function signatures, including keyword-only arguments (`*,`) for anything beyond 1-2 positional params: see `evaluate(*, operation, authorization, risk=..., ...)` in `backend/app/policy/engine.py`.
- Modern union syntax (`X | None`) rather than `Optional[X]`.

## Import Organization

**Order:**

1. `from __future__ import annotations`
2. stdlib imports (`from collections.abc import Iterable`, `from posixpath import normpath`, `from datetime import UTC, datetime, timedelta`, `from uuid import uuid4`)
3. third-party (`pydantic`)
4. internal absolute imports rooted at `backend.app...` (never relative imports)

**Path Aliases:**

- None; all internal imports use fully-qualified `backend.app.<module>.<file>` paths (e.g. `from backend.app.identity.models import AuthorizationDecision`).

## Error Handling

**Patterns:**

- Central `AppError` exception class in `backend/app/core/errors.py` carries a stable `code` (SCREAMING_SNAKE_CASE), human `message`, HTTP `status_code`, and a `details` dict — designed to map directly onto an API `ErrorEnvelope`/`ErrorDetail` contract (`backend/app/contracts/models.py:643-649`).
- Call sites raise pre-built errors via factory functions rather than constructing `AppError` inline: `raise change_not_found(str(change_id))`, `raise revision_conflict(expected=expected, actual=actual)` (`backend/app/core/change_service.py`, `backend/app/core/change_repository.py`).
- Domain/pure modules (e.g. `backend/app/policy/engine.py`) avoid raising altogether — they return explainable result objects (`PolicyDecision` with `allowed`/`denial_reason`) instead of throwing, keeping evaluation pure and deterministic with "every branch defaults to deny."
- Pydantic validators raise plain `ValueError` for input-shape violations (`backend/app/contracts/models.py:275,385,387,456,458,558`) — these surface through pydantic's own validation error path rather than `AppError`.
- Low-level adapters (e.g. Windows credential store) raise stdlib `OSError` with the platform error code: `backend/app/credentials/windows_store.py:86,97,115`.
- Unimplemented/not-yet-wired capabilities raise `AppError` via `adapter_unavailable(...)` (503) rather than silently no-op-ing — see `backend/app/core/unavailable_adapters.py`.

## Comments

**When to Comment:**

- Every module has a one-line docstring summarizing its role and, where relevant, its invariants (e.g. `backend/app/policy/engine.py` docstring explains the deny-by-default philosophy and the authority-vs-policy ordering).
- Inline comments are sparse; code favors self-documenting names and docstrings over inline explanation.

**Docstrings:**

- Module-level docstring is standard. Function/class-level docstrings appear where behavior is non-obvious (e.g. explaining ordering guarantees), otherwise omitted in favor of type hints and naming.

## Function Design

**Size:** Small, single-purpose functions; `evaluate()` in the policy engine is ~40 lines and is considered large for this codebase — most helpers are under 15 lines.

**Parameters:** Keyword-only (`*`) for any function with more than one or two optional parameters, to keep call sites self-describing (see `evaluate(...)`, `DelegationPolicyEngine` constructors, error factories).

**Return Values:** Prefer returning explainable, typed result objects (pydantic models like `PolicyDecision`) over booleans or exceptions when representing business decisions; reserve exceptions (`AppError`) for actual failure/not-found/conflict conditions.

## Module Design

**Domain-per-package layout:** Each bounded concept gets its own package under `backend/app/` (`policy/`, `identity/`, `credentials/`, `providers/`, `recovery/`, `passport/`, `execution/`, `verification/`, `outcomes/`, `contracts/`, `core/`), each typically containing `models.py` (pydantic schema), an `engine.py` or `service.py` (logic/orchestration), and sometimes `ports.py` (interfaces for pluggable adapters) and `repository.py` (persistence).

**Pydantic base models:** Each domain defines its own base model subclass with `model_config = ConfigDict(extra="forbid")` (e.g. `PolicyModel` in `backend/app/policy/models.py`) to reject unexpected fields strictly — apply this pattern when adding new domain models.

**Exports:** No barrel files (`__init__.py` files are empty/minimal markers, e.g. `backend/app/__init__.py` just holds a docstring); consumers import directly from the specific submodule.

**Ports/adapters:** External or optional integrations are abstracted behind a `ports.py` protocol/interface per domain (e.g. `backend/app/contracts/ports.py::PolicyPort`, `backend/app/providers/provider_port.py`), with concrete implementations (`github.py`, `windows_store.py`) and fakes for tests (`backend/tests/providers/fakes.py`).

---

*Convention analysis: 2026-09-19*
