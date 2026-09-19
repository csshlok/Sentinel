---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
# Testing Patterns

**Analysis Date:** 2026-09-19

## Test Framework

**Runner:**

- `pytest` 8.3.x, configured in `pyproject.toml` (`[tool.pytest.ini_options]`)
- Config: `pyproject.toml` — `addopts = "-q"`, `pythonpath = ["."]`, `testpaths = ["backend/tests"]`

**Assertion Library:**

- Plain `assert` statements (pytest-native), no third-party assertion library.

**Coverage:**

- `pytest-cov` 6.x listed as an optional test dependency (`[project.optional-dependencies].test` in `pyproject.toml`); no coverage threshold enforced in config.

**Run Commands:**

```bash
pip install -e ".[test]"      # install app + test deps
pytest                         # run all tests (uses addopts -q, testpaths from pyproject.toml)
pytest backend/tests/policy    # run one domain's suite
pytest --cov=backend           # run with coverage
```

## Test File Organization

**Location:**

- Tests live in a separate top-level tree, `backend/tests/`, mirroring the `backend/app/` package structure one-to-one: `backend/tests/policy/`, `backend/tests/identity/`, `backend/tests/credentials/`, `backend/tests/providers/`, `backend/tests/recovery/`, `backend/tests/passport/`, `backend/tests/execution/`, `backend/tests/verification/`, `backend/tests/outcomes/`, `backend/tests/git/`, `backend/tests/core/`.
- Plus two cross-cutting directories: `backend/tests/integration/` (multi-module flows, e.g. `test_change_flow.py`) and `backend/tests/acceptance/` (contract/lifecycle/migration-level checks: `test_contract_boundaries.py`, `test_lifecycle.py`, `test_migrations.py`).

**Naming:**

- Test files: `test_<module_under_test>.py`, e.g. `test_engine.py`, `test_service.py`, `test_github.py`, `test_git_recovery.py`.
- Test functions: `test_<behavior_being_verified>`, written as a full sentence describing the expectation, e.g. `test_authority_denied_overrides_everything`, `test_forbidden_path_prefix_denies`, `test_similarly_named_sibling_path_is_not_forbidden` (`backend/tests/policy/test_engine.py`).
- Every package (app and test) has an `__init__.py`, including test subpackages.

**Structure:**

```
backend/tests/
├── <domain>/
│   ├── __init__.py
│   └── test_<module>.py
├── integration/
│   └── test_change_flow.py
└── acceptance/
    ├── test_contract_boundaries.py
    ├── test_lifecycle.py
    └── test_migrations.py
```

## Test Structure

**Suite Organization:**

```python
"""Policy module tests."""
import pytest

from backend.app.identity.models import AuthorizationDecision
from backend.app.policy.engine import evaluate
from backend.app.policy.models import PolicyDenialReason, PolicyOperation, RiskLevel

ALLOWED = AuthorizationDecision(allowed=True)
DENIED = AuthorizationDecision(allowed=False)

def test_authority_denied_overrides_everything() -> None:
    decision = evaluate(operation=PolicyOperation.PROVIDER_REPO_READ, authorization=DENIED)
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.AUTHORITY_DENIED
```

(`backend/tests/policy/test_engine.py`)

**Patterns:**

- No `pytest.fixture`/`conftest.py` in this codebase (none found anywhere under `backend/tests/`) — setup is done via plain module-level constants (`ALLOWED = AuthorizationDecision(allowed=True)`) or small local helper functions defined at the top of the test file.
- For stateful/service-level tests, a local `_engine(tmp_path, now)` helper builds a fresh `Database`, repository, and service per test using pytest's built-in `tmp_path` fixture (no custom fixtures) — see `backend/tests/policy/test_service.py`. This is the standard pattern for anything needing a SQLite-backed database: create a throwaway file under `tmp_path`, call `database.initialize()`, then construct repositories/services around it.
- Similarly, local `_change(...)`, `_delegate(...)` helper functions build domain objects with sensible defaults and accept `**overrides` for the field(s) under test, avoiding factory libraries.
- Type-annotated test functions: `-> None` return type on every test function.
- `pytest.mark.parametrize` used for testing multiple inputs against the same assertion shape, e.g. iterating both `PROVIDER_FORCE_PUSH` and `PROVIDER_SECRET_READ` through `test_default_denied_operations` (`backend/tests/policy/test_engine.py`).

## Mocking

**Framework:** No `unittest.mock`/`pytest-mock` usage detected. The codebase uses **hand-written fakes** implementing the same `ports.py` protocol as the real adapter, rather than mocking libraries.

**Patterns:**

```python
class FakeHttpTransport:
    def __init__(self, queue: list[HttpResponse | Exception]) -> None:
        self._queue = list(queue)
        self.calls: list[dict[str, object]] = []

    def request(self, method, url, *, headers, body, timeout_seconds) -> HttpResponse:
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        if not self._queue:
            raise AssertionError("FakeHttpTransport queue exhausted")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
```

(`backend/tests/providers/fakes.py`) — a scriptable fake queues canned `HttpResponse`s or `Exception`s to return per call, and records every call made for later assertion (`transport.calls`).

**What to Mock:**

- Only true I/O boundaries: HTTP transport (`FakeHttpTransport` for the GitHub provider in `backend/tests/providers/test_github.py`), OS-level credential stores, external processes.
- Databases are NOT mocked — real `Database`/SQLite is instantiated against a `tmp_path` file per test for realistic integration coverage of repositories/services.

**What NOT to Mock:**

- Domain/pure-logic modules (e.g. `policy/engine.py`) are exercised directly with real inputs — no mocking needed since they have no I/O.
- Repositories and services are tested against a real (temp-file) SQLite database rather than a mocked persistence layer.

## Fixtures and Factories

**Test Data:**

```python
def _change(database: Database, **contract_overrides: object) -> ChangeView:
    now = datetime.now(UTC)
    view = ChangeView(
        id=uuid4(),
        title="Test change",
        intent="Exercise policy",
        repository_path=REPO_PATH,
        created_at=now,
        updated_at=now,
        review_state=ReviewState.NO_CHANGES,
        contract=ChangeContract(**contract_overrides),
    )
    ChangeRepository(database).create(StoredChange(...))
    return view
```

(`backend/tests/policy/test_service.py`) — locally-defined builder functions with defaults, not shared fixture files or factory libraries (e.g. `factory_boy`).

**Location:**

- Builder/helper functions live at the top of the specific test file that needs them (no shared `factories.py` or `conftest.py` found); duplicate small helpers across files are acceptable in this codebase's style.

## Coverage

**Requirements:** No enforced minimum; `pytest-cov` is available as an opt-in dependency.

**View Coverage:**

```bash
pytest --cov=backend --cov-report=term-missing
```

## Test Types

**Unit Tests:**

- Per-module tests under `backend/tests/<domain>/` exercising a single engine/service/repository in isolation (real SQLite via `tmp_path`, fakes for external I/O).

**Integration Tests:**

- `backend/tests/integration/test_change_flow.py` exercises multi-module flows (e.g. full Change lifecycle across policy, identity, and core).

**Acceptance Tests:**

- `backend/tests/acceptance/` verifies cross-cutting contracts: `test_contract_boundaries.py` (pydantic contract shape/`extra=forbid` guarantees), `test_lifecycle.py` (state machine transition rules), `test_migrations.py` (schema migration correctness).

**E2E Tests:**

- Not used; no browser/HTTP end-to-end test tooling detected (FastAPI's `TestClient`/`httpx` is available as a dependency but no dedicated e2e directory exists — API-level testing appears folded into integration/acceptance suites).

## Common Patterns

**Parametrized negative-case testing:**

```python
@pytest.mark.parametrize(
    "operation",
    [PolicyOperation.PROVIDER_FORCE_PUSH, PolicyOperation.PROVIDER_SECRET_READ],
)
def test_default_denied_operations(operation: PolicyOperation) -> None:
    decision = evaluate(operation=operation, authorization=ALLOWED)
    assert decision.allowed is False
    assert decision.denial_reason is PolicyDenialReason.OPERATION_NOT_PERMITTED
    assert decision.risk is RiskLevel.HIGH
```

**Exhausted-fake assertion pattern:**

- Fakes raise `AssertionError` when called more times than scripted (`FakeHttpTransport`), turning "unexpected extra call" into an immediate, clear test failure rather than a silent `None`/default response.

**Deterministic time control:**

- Services accept an injectable `clock` callable (e.g. `DelegationPolicyEngine(repository, clock=lambda: now)`) so tests can pin "now" to a fixed `datetime` instead of relying on `datetime.now()` inside the code under test — see `backend/tests/policy/test_service.py`.

---

*Testing analysis: 2026-09-19*
