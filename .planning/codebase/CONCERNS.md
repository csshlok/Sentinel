---
last_mapped_commit: 34557df5e0978870b12b05db5a89512104f42267
last_mapped_at: 2026-09-19
---
# Codebase Concerns

**Analysis Date:** 2026-09-19

## Tech Debt

**Policy/Identity/Credentials/Providers/Recovery/Passport not wired into the composition root:**

- Issue: `backend/app/main.py` (`create_app`) only constructs `ChangeRepository`, `ChangeService`, `GitRepositoryInspector`, and `SubprocessVerificationRunner`. It never instantiates `DelegationPolicyEngine` (`backend/app/policy/service.py`), `CredentialBroker` (`backend/app/credentials/broker.py`), `DelegationRepository`/identity service (`backend/app/identity/repository.py`, `backend/app/identity/service.py`), `GitHubProvider` (`backend/app/providers/github.py`), the recovery engine (`backend/app/recovery/git_recovery.py`), or the Passport builder (`backend/app/passport/builder.py`). `backend/app/core/change_service.py` and `backend/app/core/router.py` likewise never import these modules.
- Files: `backend/app/main.py`, `backend/app/core/change_service.py`, `backend/app/core/router.py`
- Impact: These recently implemented subsystems (per recent commits: AC-2 through AC-5) are unreachable from the running API. Policy enforcement, credential resolution, GitHub outcomes, Git recovery, and Change Passport generation exist only in isolated unit/contract tests — no HTTP endpoint exercises them end-to-end. A user running the API today gets none of this behavior.
- Fix approach: `[SD]` (owner of `core/` and `main.py` per `AGENT_COORDINATION.md`) needs to lead an integration pass that wires these ports into `ChangeService`/`build_router`, guided by the contracts in `backend/app/contracts/ports.py`. Until then, track this explicitly as an open integration milestone rather than assuming feature completeness from module presence.

**Credential store selection is unresolved at runtime:**

- Issue: Two `CredentialStorePort` implementations exist — `InMemoryCredentialStore` (`backend/app/credentials/memory_store.py`, non-persistent, test/dev only) and `WindowsCredentialStore` (`backend/app/credentials/windows_store.py`, ctypes-based DPAPI-backed, Windows-only). Neither is referenced from `main.py` or any factory/config code outside tests.
- Files: `backend/app/credentials/memory_store.py`, `backend/app/credentials/windows_store.py`, `backend/app/main.py`
- Impact: No documented or coded decision point for which store backs a real deployment. If `InMemoryCredentialStore` is ever wired in as a default without a deliberate override, provider tokens (GitHub PATs, etc.) will not survive process restarts and are held in plain Python memory (no `mlock`, no zeroing on drop). The Windows-only store also means the app cannot run on macOS/Linux without a third implementation.
- Fix approach: Add an explicit store-selection path in `Settings`/`create_app` (e.g., env var or OS-detection), and treat `InMemoryCredentialStore` as fallback-only. If cross-platform support is required, budget for a Keychain/libsecret-backed store.

**SQLite as sole persistence layer with `BEGIN`/`BEGIN IMMEDIATE` manual transaction management:**

- Files: `backend/app/core/database.py`
- Issue: `Database.connection()` opens a new `sqlite3.connect(...)` per call (no pooling), wraps every use in an explicit transaction, and relies on `PRAGMA busy_timeout = 5000` to arbitrate concurrent writers. `initialize()` also guards against downgrade (`applied > LATEST_SCHEMA_VERSION` raises), but there is no rollback/downgrade path if a migration partially applies before crashing (each migration + its `schema_migrations` insert happens inside one `BEGIN`, so this is likely atomic per-migration — verify `migration.apply` never manages its own transaction).
- Impact: Under concurrent request load from multiple API workers/processes, `SQLITE_BUSY` beyond 5s will surface as raw `sqlite3.OperationalError`, not translated into an `AppError`/HTTP response — this path is not visibly handled in `backend/app/core/database.py` or `change_repository.py`.
- Fix approach: Confirm single-process/single-writer deployment assumption is documented (it's implied by "local-only Change Assurance API" in `main.py:73`); if multi-worker deployment is ever considered, add explicit `OperationalError` → `AppError` translation and/or move to WAL + a single writer queue.

**`# type: ignore` on every field of `identity/repository.py` row-mapping:**

- Files: `backend/app/identity/repository.py:56-167`
- Issue: Every `sqlite3.Row` field access is suppressed with `# type: ignore[index]` because `sqlite3.Row.__getitem__` isn't typed for static analysis. This is a broad, repeated suppression rather than a single typed helper.
- Impact: Type errors in row shape (e.g., a renamed column, a `NULL` where a value is expected) will not be caught by mypy/pyright; only runtime `KeyError`/`TypeError` will surface, and only when that code path is exercised in a test.
- Fix approach: Introduce a small typed `Row` protocol or `TypedDict`-based mapping helper (`_row_to_actor(row: sqlite3.Row) -> Actor`) once, and drop the per-line ignores.

## Known Bugs

No reproducible bugs identified from static review; the full backend test suite passes (`python -m pytest -q` under `backend/`: 189 passed, 1 skipped, 0 failed as of this analysis). The skipped test is `backend/tests/credentials/test_windows_store.py` (opt-in, requires `RUN_WINDOWS_CREDENTIAL_SMOKE_TEST=1`), so the real Windows Credential Manager code path (`backend/app/credentials/windows_store.py`) is not exercised in ordinary CI runs — regressions there would not be caught automatically.

## Security Considerations

**Bare `except Exception` swallows all errors at the database transaction boundary:**

- Risk: `backend/app/core/database.py:74` catches `Exception` broadly (to trigger rollback) then re-raises, which is correct behavior for a transaction guard, but combined with `main.py`'s catch-all `handle_unexpected_error` (`backend/app/main.py:113-120`), any unexpected exception anywhere in the stack becomes a generic 500 `INTERNAL_ERROR` with `LOGGER.exception` writing full tracebacks to logs.
- Files: `backend/app/core/database.py:74`, `backend/app/main.py:113-120`
- Current mitigation: The HTTP response itself never leaks internals (message is generic, no traceback in the JSON body) — this is good practice.
- Recommendations: Confirm the logging sink for `LOGGER.exception` doesn't end up in a location readable by lower-trust processes, since tracebacks can include SQL parameters or file paths. No evidence of log redaction for secrets was found; combined with the "Credential store selection" concern above, verify no code path ever logs a resolved token (a `git grep` for `logger.*token` found none, which is good, but `providers/github.py`'s docstring promise "never logs a token" should be enforced with a lint rule or test, not just a comment).

**`CredentialBroker.resolve_secret` is the sole boundary for exposing raw secrets — verify all call sites respect it:**

- Files: `backend/app/credentials/broker.py:87-99`, `backend/app/providers/github.py`, `backend/app/providers/provider_port.py`
- Risk: The design intent (per broker.py docstring) is that no code outside `resolve_secret` ever handles the raw secret. This is a convention enforced by code review, not by the type system (the return type is a plain `str`, indistinguishable from any other string).
- Current mitigation: `GitHubProvider` methods (`backend/app/providers/github.py:80-147`) do accept `token: str` as a parameter rather than resolving it themselves, which matches the intended boundary.
- Recommendations: Consider a `NewType` or wrapper (e.g., `SecretStr` from Pydantic) for resolved secrets to make accidental logging/serialization structurally harder, especially since `ChangeView.model_dump(mode="json")` patterns are used elsewhere (`change_service.py:258`) and could accidentally serialize a secret-bearing object if one is ever added to a response model.

**Git recovery engine invokes `git` via subprocess without shell, but constructs refs/branch names from Change/provider data:**

- Files: `backend/app/recovery/git_recovery.py:194-353`
- Risk: `subprocess.run` calls throughout `git_recovery.py` pass `argv` lists (not shell strings), which avoids shell injection. However, if any argument (e.g., a branch name or SHA derived from a `ChangeView`) is attacker-influenced and passed to `git` as an option-like string (e.g., starting with `--`), it could be interpreted as a flag rather than a positional argument (a classic "argument injection" rather than shell injection).
- Current mitigation: Not confirmed from this review whether all git argv construction validates/prefixes ref names against option-injection (e.g., using `--` separators before revision arguments).
- Recommendations: Audit `git_recovery.py` and `git/adapter.py` for `--` separators before user/Change-derived positional arguments to `git` subcommands.

## Performance Bottlenecks

**Per-call SQLite connection open/close with no pooling:**

- Files: `backend/app/core/database.py:64-78`
- Problem: Every `Database.connection()` call opens a brand-new `sqlite3.connect()` (with `PRAGMA` setup) and closes it at the end of the `with` block. For hot paths (e.g., `list changes`), this adds connection-setup overhead per request.
- Cause: Simplicity of implementation for a local, low-throughput desktop-style tool; acceptable given the "local-only Change Assurance API" framing in `main.py`.
- Improvement path: Not urgent given local-only, single-user scope. If request volume grows, switch to a single long-lived connection guarded by a lock, or a small connection pool.

## Fragile Areas

**`change_service.py` and `change_repository.py` are the largest, most central files and are `[SD]`-exclusive:**

- Files: `backend/app/core/change_service.py` (288 lines), `backend/app/core/change_repository.py` (581 lines)
- Why fragile: `change_repository.py` is the single largest implementation file in the backend, meaning schema/query changes concentrate risk in one place. Per `AGENT_COORDINATION.md`, this path is exclusively owned by `[SD]`, so any contributor touching Change persistence must coordinate through the claim process rather than editing directly.
- Safe modification: Follow the claim-before-edit protocol in `AGENT_COORDINATION.md` (post a `[TAG] CLAIM` before editing `backend/app/core/`). Do not modify contracts (`backend/app/contracts/models.py`, `backend/app/contracts/ports.py`) without independent verification, since they are the frozen shared surface multiple owners depend on (see recent commit "AC: reconcile identity/policy/credentials/providers with frozen contracts").
- Test coverage: `backend/tests/integration/test_change_flow.py` (157 lines) exercises the flow end-to-end at the service layer, but since policy/credentials/providers are not wired into `ChangeService` (see Tech Debt above), this integration test cannot currently catch regressions in the cross-cutting behavior those modules are meant to add.

**Three-person exclusive-path ownership model risks silent drift if not actively maintained:**

- Files: `AGENT_COORDINATION.md`
- Why fragile: The repo enforces per-directory ownership (`[SD]`, `[KB]`, `[AC]`) via a documented convention, not tooling (no CODEOWNERS file or CI check was found enforcing this). A future contributor unaware of the document could edit outside their lane without any automated warning.
- Safe modification: Add a lightweight CI check (e.g., a script diffing changed paths against `AGENT_COORDINATION.md`'s ownership table) if this project continues with multiple contributors, so violations are caught at PR time rather than by convention alone.

## Scaling Limits

**Single SQLite file, single machine, "local-only" by design:**

- Current capacity: Sized for one local user (see `main.py:73` docstring "local-only Change Assurance API" and default DB path under `.change-assurance/` in the current working directory).
- Limit: Not designed for multi-tenant or networked multi-writer use; `ui_origin` CORS defaults to `http://localhost:5173`, reinforcing the single-machine, single-user assumption.
- Scaling path: Out of scope unless product direction changes to a hosted/multi-user service — would require a real database (Postgres), connection pooling, and multi-tenant credential isolation (the current `WindowsCredentialStore` OS-keychain approach would need to be replaced entirely).

## Dependencies at Risk

**`WindowsCredentialStore` hand-rolls Win32 API bindings via `ctypes` instead of a maintained library:**

- Files: `backend/app/credentials/windows_store.py`
- Risk: The docstring explains this is deliberate (avoiding a new dependency requires an `[SD]`-owned handoff per `AGENT_COORDINATION.md`), but it means the team owns and must maintain correctness of low-level Win32 struct layouts (`_CREDENTIAL`) and error handling (`ctypes.get_last_error()`) themselves, with only an opt-in, non-default-run smoke test (`RUN_WINDOWS_CREDENTIAL_SMOKE_TEST=1`) covering the real OS calls.
- Impact: A subtle struct-layout bug (e.g., wrong field order/alignment for `_CREDENTIAL`) could corrupt writes to Windows Credential Manager or crash with an access violation, and would not be caught by the default test run.
- Migration plan: If the dependency-handoff process allows it later, moving to `pywin32` or `keyring` would reduce this maintenance burden; until then, prioritize running the opt-in smoke test in a dedicated Windows CI job.

## Missing Critical Features

**No frontend / UI beyond the (also incomplete) terminal UI:**

- Problem: `AGENT_COORDINATION.md` states `frontend/` (browser UI) is "reserved... and unassigned/frozen." No `frontend/`, `*.tsx`, `*.jsx`, or any `package.json` exists anywhere in the repo. A terminal UI (`backend/app/tui/`) is nominally owned by `[AC]` but no `backend/app/tui/` directory exists yet either.
- Blocks: There is currently no way for an end user to interact with the system except direct HTTP calls to the FastAPI backend (`backend/app/main.py`) — no CLI (`backend/app/cli/`, also referenced in ownership table but not present) and no TUI exist yet.

## Test Coverage Gaps

**No test exercises the fully wired system (policy + credentials + providers + recovery + passport together via the API):**

- What's not tested: End-to-end behavior of a Change going through policy evaluation, credential resolution, a GitHub provider call, and Passport generation, all through `backend/app/main.py`'s `create_app()` — because that composition does not exist yet (see Tech Debt).
- Files: `backend/tests/integration/test_change_flow.py` (only covers what's wired today); component-level tests exist per-module (`backend/tests/policy/test_service.py`, `backend/tests/credentials/` implied, `backend/tests/providers/test_github.py`, `backend/tests/recovery/test_git_recovery.py`, `backend/tests/passport/test_builder.py`) but do not integrate.
- Risk: Interface mismatches between these modules and `ChangeService`/`router.py` could go undetected until manual integration, since each module is tested in isolation against contracts in `backend/app/contracts/ports.py` rather than against the real composition root.
- Priority: High — this is the natural next validation step once `[SD]` performs the wiring pass.

**`WindowsCredentialStore` real-OS-call path is opt-in only:**

- What's not tested: Actual `CredWriteW`/`CredReadW`/`CredDeleteW` behavior against the live Windows Credential Manager in normal test runs.
- Files: `backend/tests/credentials/test_windows_store.py`
- Risk: Regressions in the ctypes struct/bindings would only be caught by a contributor manually setting `RUN_WINDOWS_CREDENTIAL_SMOKE_TEST=1`.
- Priority: Medium — add this as a required job in a Windows-hosted CI runner if one exists, rather than leaving it fully opt-in.

---

*Concerns audit: 2026-09-19*
