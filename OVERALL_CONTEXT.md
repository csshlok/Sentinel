# Change Assurance - Overall Context

## Document role

This is the stable, product-level context for the repository. It explains why the product exists, the long-term system boundary, the language we use, and the engineering principles that should survive individual implementation phases.

`PROJECT_CONTEXT.md` is the operational context for the active proposal implementation. It records the approved subsystem cuts and may refine this document without silently contradicting it. `BACKEND_IMPLEMENTATION_PLAN.md` contains the full three-person execution plan. `AGENT_COORDINATION.md` governs exclusive ownership and collaboration.

## Context hierarchy

Agents and contributors read repository context in this order:

1. `OVERALL_CONTEXT.md` - stable product purpose and invariants.
2. `PROJECT_CONTEXT.md` - current scope, cuts, and definition of done.
3. The implementation plan for the assigned workstream.
4. `AGENT_COORDINATION.md` - file ownership, claims, handoffs, and Git rules.
5. Existing code and tests in the assigned ownership area.

When documents disagree, stop and report the conflict. Do not choose whichever document makes the task easier.

## Product thesis

AI coding tools can make useful changes quickly, but developers still need a trustworthy way to connect intended work with actual repository changes and verification evidence. The broader Change Assurance vision is to make software changes attributable, bounded, observable, verifiable, and recoverable where technically possible.

The root object is a **Change**: a persistent record connecting intent, actors, scoped authority, observable evidence, decisions, and outcomes.

## Product direction

The repository now targets the retained Change Assurance Runtime from the project proposal:

- Change lifecycle, contracts, and evidence freshness.
- Scoped actor/agent identity, delegation, policy, and credential brokering.
- Top-level agent launch/attach with bounded aggregate results.
- Git, environment, and dependency checkpoints.
- Evidence-selected assurance and contract-deviation analysis.
- Pull-request, CI, artifact, and deployment continuity where real adapters exist.
- Approved Git/provider compensation and a final Change Passport.

Event journaling, process supervision, filesystem tracking, and the tool registry are deliberately excluded. Capabilities that require those primitives are not future-sounding claims in this product plan; they are explicit unsupported boundaries unless scope is separately changed.

## Current product scope

The current build implements the proposal without a time-box, except for these four approved cuts:

- Event/effect journal.
- Process supervision and descendant attribution.
- Filesystem tracking, snapshots, local-file recovery, and undo.
- Tool registry and tool trust.

Replay is also unavailable because it depends on the removed event journal. Descendant attribution and cleanup depend on the removed process supervisor. Uncommitted local recovery depends on filesystem tracking. Tool trust depends on the tool registry. These consequences must remain visible in APIs, UI copy, Passport limitations, and recovery previews.

The already implemented Git review backend is the migration foundation, not the final scope. The active phase adds the retained lifecycle, authority, evidence, assurance, outcomes, recovery, scriptable CLI, and interactive terminal UI around it. Browser web UI implementation is deferred until the backend contracts and acceptance suite are stable.

## Product invariants

### Evidence must be real

User-visible status comes from the backend or is labeled unavailable. Do not hardcode healthy, safe, verified, complete, or ready states. A demo fixture may create real state, but the UI must still obtain that state through the same API used in normal operation.

### Observation must not be described as enforcement

Reading a Git diff is not filesystem attribution. Running a command is not process supervision. A passing test is not proof of correctness. The product must state what it observed and what remains unknown.

### Local-first behavior

The runtime operates against a user-selected repository and exposes a loopback-only authenticated API by default. Local lifecycle/evidence/assurance remains useful without a hosted database or provider account; GitHub features require an explicit provider connection.

### Selected repositories are user data

Evidence collectors are read-only. The backend must not reset, clean, checkout, stage, commit, or otherwise mutate a selected repository during observation. The only runtime-owned mutation is a separately previewed and explicitly approved recovery action on a dedicated Change branch, performed conflict-first in a temporary worktree and recorded as a new commit. User-requested agent/assurance commands may independently modify the repository; that risk must be visible.

### Contracts are authoritative

Shared request, response, and error contracts are versioned coordination points. Implementations conform to contracts; they do not invent private variations. A contract change requires an explicit handoff and consumer review.

### No safety theater

Unsupported capability is shown as unsupported. Missing evidence is shown as missing. Errors are not converted into optimistic statuses. The system must not imply assurance it did not establish.

### Deterministic decision logic

Given the same Change Contract, authority, checkpoints, assurance, and outcomes, the backend returns the same classifications, findings, and permitted lifecycle transitions. Policy, freshness, classification, and transition rules belong in pure tested functions wherever possible.

## CML working standard

This project must use the same context discipline and implementation standard expected from CML:

- Stable overall context is separated from the current implementation slice.
- Scope cuts and their dependent limitations are explicit and enforced in code review.
- User-visible states are backed by real application data, not placeholder success values.
- Interfaces are defined before parallel implementation.
- Each subsystem has one owner and an explicit handoff contract.
- Integration happens at planned gates, not through overlapping edits.
- Tests verify behavior at module boundaries and through the real end-to-end path.
- Empty, loading, failure, and unsupported states are first-class behavior.
- Product copy reflects actual capability and avoids aspirational claims.
- A feature is complete only when implementation, tests, error handling, and user-visible state agree.

The available local CML export contains application UI and an audit, but not the canonical CML project-context or overall-context documents. If those canonical documents are added to the workspace, `[SD]` must compare their structure and update this context system after `[KB]` and `[AC]` review, without weakening the project-specific scope decisions above.

## Core vocabulary

- **Change**: the durable root joining intent, actors, authority, evidence, decisions, and outcomes.
- **Change Contract**: expected paths/outcomes/checks and maximum delegated authority.
- **Actor / Delegation**: identity and a scoped, expiring, revocable grant.
- **Git checkpoint**: repository state captured at a named lifecycle boundary.
- **Environment passport**: redacted, comparable host/toolchain/repository facts.
- **Assurance**: selected checks and evidence coverage; never proof of correctness.
- **Outcome**: provider-observed PR, CI, artifact, or deployment state.
- **Recovery**: supported Git/provider compensation after preview and approval; not general rollback.
- **Change Passport**: versioned export of retained evidence, decisions, gaps, outcomes, and recovery status.

## Architecture boundary

```text
Terminal UI / CLI / API clients -> Authenticated local API -> Change lifecycle and policy
                                      -> Identity and credential broker -> GitHub
                                      -> Top-level Agent Launcher
                                      -> Git/environment/dependency evidence
                                      -> Assurance engine
                                      -> Outcome tracker
                                      -> Constrained recovery
                                      -> Change Passport
```

The Agent Launcher invokes or references only the top-level agent. No component supervises the descendant process tree, intercepts filesystem operations, or records a causal event stream.

The interactive terminal UI is the current human interface. A browser web UI is a later consumer of this boundary and is not part of the active implementation phase.

## Quality bar

Product work is acceptable only when:

- Inputs are validated at the boundary.
- Errors have stable codes and safe messages.
- Paths with spaces and Windows path behavior are tested.
- Subprocesses use argument arrays and do not invoke a shell.
- Output and execution time are bounded.
- Persistence survives restart.
- Tests cover success, empty, failure, timeout, and malformed-input states.
- End-to-end acceptance uses a real temporary Git repository, real API calls, and contract-faithful provider fakes where external mutation is unsafe.
- No release screen depends on mock data.
- Documentation matches actual behavior.

## Decision authority

- This file owns stable product principles and vocabulary.
- `PROJECT_CONTEXT.md` owns the active release scope.
- An implementation plan owns task sequencing but cannot expand scope.
- API contracts own integration behavior once frozen.
- Tests own demonstrated acceptance behavior.

Changing a stable product invariant requires an explicit decision recorded by `[SD]` and acknowledged by `[KB]` and `[AC]`. Scope changes require synchronized revisions to `PROJECT_CONTEXT.md`, the implementation plan, and the ownership map before implementation.

## Completion principle

The product is not complete because a happy-path screen renders. It is complete when real state flows through the actual backend, boundaries are honest, failures are legible, tests demonstrate the promised behavior, and every visible claim is supported by evidence.

## Implementation record

Implementation records describe completed work without changing the stable product principles above.

### `[KB]` - 2026-09-19 01:55 -04:00 - Person 2 evidence/execution/assurance stream complete

`[KB]` implemented every remaining Person 2 item (KB-1 through KB-6) against the ports `[SD]` froze: `GitStateTracker`, `AgentLauncher`, `EnvironmentTracker`, `DependencyTracker` and `AssuranceEngine`, in `backend/app/{git,execution,environment,dependencies,assurance}/` with matching tests under `backend/tests/`. No shared contract, migration, composition or other owner's module was edited; nothing is wired into the application yet. The earlier blocked status in the `[KB]` entries below is superseded.

What is now real: deterministic Git checkpoints with untracked-content digests and freshness checks; a top-level-only agent launcher (allowlisted environment, redacted output, direct-child cancel/timeout, attach as metadata); redacted, fingerprinted environment passports with drift; Python and Node dependency comparison that reports unsupported and malformed files instead of guessing; and an assurance engine that selects checks from the Change Contract and changed-path/dependency evidence, refuses stale evidence, and reports coverage gaps and contract deviations.

Verification: whole repository **473 passed, 1 skipped**; `[KB]` suites **328 passed** with **98%** statement+branch coverage on the five owned packages; `python -m compileall -q backend` passed. Real Git repositories, subprocesses, `pytest`, Node `node --test` and SQLite round trips were used, and owner-local end-to-end flows cover baseline -> agent edit -> comparison -> dependencies -> assurance -> staleness.

Honest limits: no descendant control/attribution, replay, local-file undo or tool trust (the four cuts); Git reads are not an atomic snapshot; passing checks are not proof of correctness; checks use the runtime's interpreter, not a repository virtual environment; Windows and Python 3.14 only. Contract gaps and the `[SD]` integration steps are in `backend/app/git/KB_HANDOFF.md`. This is self-verification and awaits independent `[SD]` review.

### `[SD]` - 2026-09-19 01:49:29 -04:00 - Hardening tests for `[SD]`'s own composition, plus formal Gate 2 review of the `[AC]` stream

Two things in one record: (1) the four remaining unblocked `[SD]` items from the prior two records' punch list, all of which are test/verification work against `[SD]`'s own `backend/app/core/` composition, not new capability; (2) the formal `[AC]` stream-complete review `BACKEND_IMPLEMENTATION_PLAN.md` §14's post-handoff protocol calls for, which had been done in substance (adversarial acceptance tests, full read of every module) but never written up as a disposition.

#### 1. Real app-restart persistence (`test_state_persists_across_a_real_app_restart`)

Every existing acceptance test built a fresh DB per test, which already proved "clean clone" and (`test_migrations.py`) "upgrade," but nothing tore down one `create_app()` instance and built a second one against the same on-disk database — the actual shape of a process restart. New test in `test_runtime_routes.py` does exactly that: creates a Change/Actor/Delegation/recovery-plan-preview through app instance 1, discards it, builds app instance 2 from the same `Settings.database_path`, and confirms all four are still retrievable through the real API. Required adding an optional `settings` override to the existing `_build_client` test helper so both instances point at the same file.

#### 2. Forbidden/expected route-family assertions (`test_contract_boundaries.py`)

`[SD]` had checked "no `/events`/`/effects`/`/replay`/`/tools` path" manually with a one-off script after wiring routes each time; it was never a committed test, so a future regression would go unnoticed. Added `test_no_removed_subsystem_endpoints_are_exposed` (also covers `/processes`, `/snapshots`) and `test_expected_route_families_are_present` (the inverse check — a route family silently disappearing is just as much a contract break), both built from `create_app().openapi()["paths"]` directly rather than a hardcoded list, so they track the real app.

#### 3. Failure-injection through the new provider routes — found and fixed a real idempotency defect

Three new tests in `test_runtime_routes.py` drive `FakeHttpTransport` failure scenarios through `/changes/{id}/providers/github/pulls`:

- Exhausted retries (four queued `503`s, matching `GitHubProvider`'s `max_retries=3`): the route returns **HTTP 200** with `ProviderOperation.status == "FAILED"` and `safe_metadata.error_code == "PROVIDER_UNAVAILABLE"` — `GitHubProviderAdapter` already catches the provider's `AppError` and records it as a normal (failed) operation rather than crashing the request, which is the correct design, not a bug.
- Immediate non-retryable failure (one `404`): same FAILED-recording pattern, exactly one HTTP call made (404 is not in `RETRYABLE_CODES`).
- No resolvable GitHub remote on the local repository: this *is* a request-level `[SD]`-raised error (`provider_repository_unresolved`, before any GitHub call), and correctly surfaces as the documented `{"error": {"code": "PROVIDER_REPOSITORY_UNRESOLVED"}}` envelope at HTTP 409 — the one case that should look like a normal API error rather than a recorded operation, and it does.

Writing the exhausted-retries test surfaced a real defect in last record's `ProviderOperationService.create_pull_request` (`backend/app/core/runtime_service.py`, `[SD]`'s own code): it called `self.provider.execute(...)` unconditionally on every request, before checking whether that idempotency key had already been recorded. For a *successful* first call this was invisible, because `GitHubProvider`'s own internal `_pr_cache` happens to short-circuit replays — but that cache is success-only. Replaying a **failed** operation's idempotency key silently re-ran the entire request (and all its retries) against GitHub a second time, which is exactly the kind of duplicate-side-effect bug idempotency keys exist to prevent. Fixed by checking `ProviderOperationRepository.get_by_idempotency_key` first and returning the stored result unconditionally (success or failure) before calling the provider at all. Confirmed by the exhausted-retries test's second assertion: replaying the same idempotency key after a recorded `FAILED` result makes **zero** additional transport calls.

#### 4. Formal Gate 2 review disposition for the `[AC]` stream (AC-0..AC-7)

Following §14's seven-step post-handoff sequence:

1. **Intake integrity**: `[AC]`'s commits (`d84829a`..`c1d5075`) touch only `backend/app/{identity,policy,credentials,providers,outcomes,recovery,passport,cli,tui}/` and matching test paths, plus its own context-document entries. No shared contract, migration, or another owner's concrete module was edited. Working tree was clean before this review.
2. **Proposal/scope trace**: every AC-0..AC-5 class maps to a retained proposal capability listed in `PROJECT_CONTEXT.md` §"Required scope" (identity/delegation, policy, credential broker, GitHub provider/outcomes, recovery, Passport); AC-6/AC-7 map to the required CLI/terminal UI. No removed-subsystem capability (event journal, process supervision, filesystem tracking, tool registry, replay) is implemented or implied anywhere in the stream — confirmed by the new forbidden-route test above and by reading every module's docstrings, which are explicit about the boundary.
3. **Static review**: read every file under `backend/app/{identity,policy,credentials,providers,outcomes,recovery,passport}/` in full while building the Gate 3 composition two records ago. Grant/secret handling is sound (`resolve_secret` is the only path a durable secret ever leaves `CredentialStorePort`; grep audit found zero `print`/`logging` of secret material anywhere in these paths). Subprocess usage (`GitRecoveryEngine`, `repository_slug.py`) uses argument arrays and `shell=False` throughout. `GitRecoveryEngine`'s conflict-first temporary-worktree pattern for both preview and execute matches the "never mutate the target repository except via a new commit on a dedicated branch" invariant.
4. **Reproduction**: `python -m pytest` on the full suite (including AC's own `backend/tests/{identity,policy,credentials,providers,outcomes,recovery,passport,cli,tui}/`): reproduced clean, matching AC's own reported counts at each stage.
5. **Independent probes** (adversarial cases `[AC]`'s own tests do not cover, since they test each module in isolation against fakes for the *other* modules): default-deny policy when a credential grant exists but no delegation does (`test_policy_denies_operation_without_matching_delegation`); a credential grant issued for one Change used against a different Change (`test_grant_bound_to_different_change_is_rejected`); the three failure-injection cases in item 3 above, which exercise `GitHubProvider`'s retry/error-mapping logic through the full route stack rather than calling it directly; the app-restart test in item 1, which is the first test to prove `identity`/`credentials`/`recovery` state survives outside one process's memory.
6. **Findings** (none blocking; none require `[AC]` to change owned code — three are pre-existing, already-documented contract gaps that `[AC]` itself flagged, one is the `[SD]`-side defect already fixed in item 3 above):
   - **Low, informational** — `CredentialBrokerPort.issue_grant` has no `provider` parameter (`[AC]`-flagged, worked around via scope-prefix inference; no functional defect found).
   - **Low, informational** — `OutcomePort.refresh(change)` has no actor/grant parameter (`[AC]`-flagged; `[SD]` worked around per-request in `OutcomeService`, see the Gate 3 record above).
   - **Low, informational** — `GitHubProviderAdapter.execute` implements only the `github.pr.create` operation; any other `operation` string returns `DENIED` with `safe_metadata.reason` rather than a distinct not-implemented error code. Explicit and honest (no fabricated support), just worth remembering if `merge`/`close`/`comment` operations are added later.
   - **Low, informational** — `RecoveryPort.execute` conflates "approve" and "execute" into one call; `RecoveryStatus.APPROVED`/`EXECUTING` are declared in the contract but never actually produced by `GitRecoveryEngine`. `RuntimeLifecycleFacts.recovery_plan_approved` was built to match this real behavior (`approved_at is not None`, set exactly when `execute` is called) rather than the contract's implied three-step flow.
   - **Medium, non-blocking, already documented** — `CredentialBroker`'s in-process-only grant cache (see the Gate 3 record above).
   - **Fixed, not just found** — the `ProviderOperationService` idempotency-replay defect in item 3 above. This was `[SD]`'s own code, not `[AC]`'s, so it was corrected directly rather than returned to an owner.
7. **Disposition: ACCEPT WITH NON-BLOCKING FINDINGS.** The `[AC]` stream (AC-0..AC-7) is eligible for continued integration. No finding blocks further work; all are either informational contract-gap notes `[AC]` already surfaced, or already fixed. AC-7 is explicitly a partial vertical slice per `[AC]`'s own `2026-09-19 01:30 -04:00` record (one dashboard screen; detail/lifecycle-stepper/evidence/recovery-confirmation screens not yet built) — that is `[AC]`'s stated scope, not a defect found here.

**Verification**: `python -m pytest`: **286 passed, 1 skipped**, no regressions (includes `[AC]`'s own new `backend/tests/{cli,tui}/` suites, installed via `pip install -e ".[test,tui]"` to pull in `textual` for the first time in this environment). `python -m compileall -q backend`: passed. Grep audit of every file touched or read in this record for `print`/`logging`: only the pre-existing unhandled-exception logger in `main.py`.

### `[SD]` - 2026-09-19 01:38:38 -04:00 - Real `LifecycleFactsPort`, activating evidence already wired

Following the Gate 3 composition below, `[SD]` did the one remaining unblocked P1 item: `ChangeService` was still defaulting to `UnavailableLifecycleFacts` (a hard 503 for every transition), so none of the now-real identity/outcome/recovery evidence could actually gate a lifecycle transition through the API. New `backend/app/core/lifecycle_facts_service.py` (`RuntimeLifecycleFacts`) implements the frozen `LifecycleFactsPort` for real:

- `repository_valid`/`contract_present`: always `True` — structurally guaranteed once a `ChangeView` exists (repository canonicalization and a `ChangeContract` default both happen at Change-creation time), not a fabricated default.
- `authority_valid`: `True` iff at least one non-revoked, unexpired delegation exists for the Change (existence-based, since `LifecycleFactsPort.get_facts(change, target_state)` carries no caller-actor parameter — a contract gap similar to the ones `[AC]` already flagged for `OutcomePort`/`CredentialBrokerPort`; noted here rather than changing the frozen port).
- `pull_request_recorded`: `True` iff a `SUCCEEDED` `provider_operations` row exists for `github.pr.create` (added `ProviderOperationRepository.has_succeeded_operation`).
- `ci_passed_for_current_head`: `True` iff a `PASSED` CI `Outcome` exists whose `head_sha` matches the Change's *current* `git_summary.head_sha` — a stale outcome for an old commit does not count.
- `recovery_plan_approved`/`recovery_verified`/`recovery_conflict`/`recovery_failed`/`unresolved_recovery_actions`: derived from the latest persisted `RecoveryPlan`'s `status`/`approved_at`.
- `required_assurance_passed`, `assurance_fresh`, `deviations_resolved`, `required_evidence_complete`, `artifact_recorded`, `deployment_recorded`, `observation_criteria_met`: left at the `LifecycleFacts` default of `False` and documented as such in the module docstring — these depend on `[KB]`'s still-unimplemented environment/dependency/assurance stream, so `LOCALLY_VERIFIED`, `REVIEW_READY`, `ARTIFACT_BUILT`, `DEPLOYED`, `OBSERVING`, and `STABLE` stay honestly unreachable through the real API. Because `ALLOWED_TRANSITIONS` only reaches `PR_OPEN`/`CI_VERIFIED` via `REVIEW_READY`, those two states remain unreachable through the FSM too, even though their own guards now compute correctly — confirmed by direct unit coverage of the fact computation, and left as a known, correctly-behaving limitation rather than something to route around.

`create_app` now builds `RuntimeLifecycleFacts` from the same `DelegationRepository`/`ProviderOperationRepository`/`OutcomeRepository`/`RecoveryRepository` instances used elsewhere, before constructing `ChangeService`, and passes it as the default `lifecycle_facts` (still overridable, e.g. by tests). `UnavailableLifecycleFacts` remains defined in `backend/app/core/unavailable_adapters.py` for explicit injection but is no longer the default.

**What this activates end-to-end through the real API**: `DRAFT -> ACTIVE` now genuinely requires a live delegation instead of always failing; `ACTIVE -> RECOVERY_PENDING -> RECOVERING -> RECOVERED_VERIFIED` (and the `RECOVERY_CONFLICT`/`RECOVERY_FAILED` branches) now work end-to-end against a real recovery plan/execution.

**Verification**: `python -m pytest`: **265 passed, 1 skipped**, no regressions — 6 new unit tests in `backend/tests/core/test_lifecycle_facts_service.py` (one per fact family, including the stale-SHA and conflict-vs-failed distinctions) plus one new acceptance test in `backend/tests/acceptance/test_runtime_routes.py` driving the full `ACTIVE`-then-recovery transition sequence through the real HTTP API against a real disposable Git repository. `python -m compileall -q backend`: passed. OpenAPI still generates cleanly with 28 routes (27 `/api/v1/*` plus health). Grep audit found no new `print`/`logging` calls.

### `[SD]` - 2026-09-19 01:12:33 -04:00 - Gate 3 composition for the `[AC]` stream; AC-6/AC-7 blockers cleared

`[SD]` reviewed `backend/app/cli/AC_REMAINING_WORK.md` and performed the two blockers it named as `[SD]`-owned work, plus the Gate 3 backend composition needed to make AC-0..AC-5 reachable from the real API. Work was limited to `backend/app/contracts/models.py`, `backend/app/core/` (new `runtime_repositories.py` and `runtime_service.py`, plus `router.py`, `errors.py`, `capabilities.py` usage, and `main.py`), `pyproject.toml`, `backend/tests/acceptance/`, and this document/`PROJECT_CONTEXT.md`. No file under `backend/app/{identity,policy,credentials,providers,outcomes,recovery,passport}/` was edited; every AC-0..AC-5 concrete class is used exactly as `[AC]` implemented and tested it.

**Blocker 1 (dependencies) resolved**: added `typer>=0.15,<1` and `rich>=13,<15` to `[project.dependencies]`, and a new `[project.optional-dependencies.tui]` group with `textual>=0.85,<1`, in `pyproject.toml`, exactly as requested in `[AC]`'s `CONTRACT CHANGE REQUEST`.

**Blocker 2 (missing routes) resolved**: `backend/app/core/router.py` now exposes, backed by real composed services in the new `backend/app/core/runtime_service.py` (`IdentityAdminService`, `CredentialAdminService`, `ProviderOperationService`, `OutcomeService`, `RecoveryService`, `PassportService`) and persistence in the new `backend/app/core/runtime_repositories.py`:

- `POST/GET /api/v1/actors`, `POST/GET /api/v1/delegations`, `POST /api/v1/delegations/{id}/revoke`, `GET /api/v1/changes/{id}/delegations`.
- `POST /api/v1/providers/github/{connect,disconnect}`, `GET /api/v1/providers/github/status`.
- `POST /api/v1/changes/{id}/providers/github/grants`, `.../grants/{id}/revoke`, `.../pulls`.
- `POST /api/v1/changes/{id}/outcomes/refresh`, `GET /api/v1/changes/{id}/outcomes`.
- `POST /api/v1/changes/{id}/recovery/preview`, `POST .../recovery/{plan_id}/execute`, `GET /api/v1/changes/{id}/recovery`.
- `POST/GET /api/v1/changes/{id}/passport`.

Every mutating route now runs `DelegationPolicyEngine.evaluate` (the frozen `PolicyPort`) before a privileged operation (`github.pr.create`, `recovery.execute`) and returns the stable `POLICY_DENIED` error on refusal; a credential grant is additionally checked for exact actor/Change binding (`CREDENTIAL_GRANT_BINDING_INVALID`) before it can be used, independent of policy. `credential_grants`, `provider_operations`, `outcomes`, `recovery_plans`/`recovery_actions`, and `change_passports` — all previously-migrated but previously-unwritten tables from `[SD]`'s own `migration_002_change_runtime_core` — are now populated by the new repositories in `runtime_repositories.py`, following the same payload-JSON-plus-indexed-columns pattern as the existing `git_checkpoints` reader in `backend/app/recovery/checkpoints.py`. `provider_operations` idempotency reuses the table's existing `UNIQUE(change_id, idempotency_key)` constraint: a replayed key returns the originally stored `ProviderOperation` instead of a second GitHub call.

**Two contract gaps `[AC]` flagged were resolved at the composition layer, not by changing the frozen ports**: `OutcomePort.refresh(change)` takes no grant, so `OutcomeService.refresh` builds a fresh `GitHubOutcomeTracker(tracker, broker, read_grant_id=<caller-supplied grant>)` per request instead of a single app-wide instance; `CredentialBrokerPort.issue_grant` takes no `provider`, which `[AC]`'s own `_provider_from_scopes` already infers from the scope prefix, so no port change was needed there either.

**Composition choices**: `create_app` gained `credential_store` (defaults to `WindowsCredentialStore()`, matching this product's Windows-only credential-storage claim) and `http_transport` (defaults to `UrllibHttpTransport()`) parameters, following the existing `git_inspection`/`verification`/`lifecycle_facts` injection pattern, so tests can supply `InMemoryCredentialStore` and a local `FakeHttpTransport` — never a real network call or real credential — exactly as `backend/tests/providers/fakes.py` already does for `[AC]`'s own tests. `ChangeService`'s default `configured_capabilities` now includes `identity_and_policy`, `credential_broker`, `provider_outcomes`, `recovery`, and `change_passport` (all now genuinely connected); `git_checkpoints`, `agent_launcher`, `environment_passports`, `dependency_tracking`, `assurance`, and `cli_and_terminal_ui` remain honestly `UNCONFIGURED` because `[KB]`'s stream and `[AC]`'s CLI/TUI are not implemented yet — `/api/v1/capabilities` was manually checked to confirm this exact split.

**Known, inherited limitation (not introduced by this work)**: `CredentialBroker` keeps issued grants only in an in-process dict (`[AC]`'s design, already covered by `[AC]`'s own tests). A grant is durably visible through the new `credential_grants` table and `GET`-style lookups even after a process restart, but `CredentialBroker.resolve_secret` — and therefore any operation that needs the actual bearer token — will report the grant as not found after a restart until it is re-issued. This fails safe (denies rather than leaks) and does not block AC-6/AC-7; it is a candidate contract-change request (a durable-grant persistence hook on `CredentialBrokerPort`) for a later `[AC]`/`[SD]` cycle, not fixed here since it would mean editing `[AC]`'s owned `backend/app/credentials/broker.py`.

**Verification**: `python -m pytest`: **258 passed, 1 skipped** (the pre-existing opt-in Windows Credential Manager smoke test), including 3 new `[SD]` acceptance tests in `backend/tests/acceptance/test_runtime_routes.py` that exercise actor/delegation creation, GitHub connect, credential-grant issuance, PR creation (with idempotent replay), CI outcome refresh, a real Git-checkpoint-seeded recovery preview/execute against a real disposable repository (reaching `RECOVERED`), and Passport build/retrieve — plus default-deny policy and cross-Change grant-binding adversarial cases. `python -m compileall -q backend`: passed. Generated OpenAPI listed all 27 routes with no forbidden `/events`, `/effects`, `/replay`, or `/tools` path. A grep audit of every new/changed file for `print`/`logging` found only the pre-existing unhandled-exception logger in `main.py`.

**What is still not done**: AC-6 (scriptable CLI) and AC-7 (interactive terminal UI) themselves are `[AC]`'s exclusive `backend/app/cli/` and `backend/app/tui/` paths and were not touched by this record — only their two named blockers were cleared. `[KB]`'s `GitStatePort`/`AgentLauncherPort`/`EnvironmentPort`/`DependencyPort`/`AssurancePort` streams remain unimplemented, so environment passports, dependency reports, and assurance runs stay genuinely absent from the Passport's evidence and are correctly reported as `limitations`, not fabricated.

### `[AC]` - 2026-09-19 01:30 -04:00 - AC-6 complete; AC-7 first vertical slice

After `[SD]`'s `c616f37` added `typer`/`rich`/`textual` to `pyproject.toml` and wired Gate 3 routes for every AC domain, both prior blockers were resolved. `[AC]` implemented **AC-6 in full**: `backend/app/cli/` — `ApiClient` (thin JSON client over the existing generic `HttpTransport` seam, no new HTTP dependency) plus a Typer app covering every Gate-3 route across `change`/`actor`/`delegation`/`github`/`outcome`/`recovery`/`passport` command groups, stable exit codes (0/1/2), `--json` machine-readable output, and `NO_COLOR`/`--no-color`/non-TTY handling from the start. Tested with fake-transport unit tests for every error path plus one real end-to-end test against a live `uvicorn` server on an ephemeral port with a real temporary Git repository — not a fake.

**AC-7 has a real first screen**, not the full spec: `backend/app/tui/app.py`'s `ChangeDashboard` lists Changes through the same `ApiClient`, with lifecycle state shown as a colour-plus-symbol pair (never colour alone) and honest empty/error/connection-failure states. The detail view, lifecycle stepper, evidence tables, assurance/outcome panels, contract/delegation forms, and — highest priority — the recovery preview/confirmation screen are not yet built. Textual `Pilot`-based interaction testing is also not yet possible: this project has no async pytest runner configured. All of this is itemized with exact next steps in `backend/app/cli/AC_REMAINING_WORK.md`.

Verification: full repository suite passed with no regressions after both additions (exact count in `PROJECT_CONTEXT.md`).

### `[AC]` - 2026-09-19 00:50:26 -04:00 - Person 3 identity/policy/broker/outcomes/recovery/passport stream (AC-0..AC-5)

`[AC]` completed AC-0 through AC-5 of the Person 3 track against the frozen contracts introduced in `[SD]`'s Phase 1 commit. Work was limited to `backend/app/{identity,policy,credentials,providers,outcomes,recovery,passport}/` and matching test paths; no shared contract, migration, or another owner's concrete module was edited.

- **AC-1 identity**: `ActorRepository`/`DelegationRepository` persist through the canonical `actors`/`delegations` tables from `[SD]`'s `migration_002_change_runtime_core` (an earlier draft mistakenly created parallel `identity_actors`/`identity_delegations` tables; this was found and corrected once the real migration landed). `IdentityService`/`evaluate_delegation` implement default-deny authorization with full decision-table coverage (not-found, revoked, expired, wrong-Change, wrong-repository, scope-not-granted, exhausted, exact-boundary timestamps).
- **AC-2 policy and broker**: `DelegationPolicyEngine` implements the frozen `PolicyPort` (delegation authority, then default-denied operations, `ChangeContract.forbidden_paths`, `authority_ceiling`, `max_risk`). `CredentialBroker` implements `CredentialBrokerPort`/short-lived internal grants; durable secrets live only behind `CredentialStorePort`, with `WindowsCredentialStore` implemented directly via `ctypes` bindings to `advapi32.dll` (no new dependency) and live-verified against the real Windows Credential Manager (create/read/update/delete a uniquely named test credential, confirmed removed via `cmdkey /list`).
- **AC-3 GitHub provider/outcomes**: `GitHubProvider` implements the HTTP/retry/idempotency boundary behind a swappable `HttpTransport` (production: stdlib `urllib`; tests: a local fake, no network or real credential). `GitHubProviderAdapter`/`GitHubOutcomeTracker` implement the frozen `ProviderPort`/`OutcomePort`. `OutcomeTracker` discards any check-run whose `head_sha` doesn't match the requested commit, so CI for one SHA can never verify another.
- **AC-4 recovery**: `GitRecoveryEngine` implements `RecoveryPort`. Recovery is Git-native revert-commit only, on a dedicated branch, conflict-checked in a temporary worktree before any mutation of the target repository, and never resets or rewrites history. Approval is a strict precondition (empty token raises). Tested against real disposable repositories, including a genuine merge-commit conflict (revert of a merge commit without `-m` fails deterministically) with proof the target repository's HEAD/branches are untouched on preview and on conflict.
- **AC-5 Passport**: `PassportBuilder` implements `PassportPort`, built only from real persisted evidence rows (`git_checkpoints`, `environment_passports`, `dependency_reports`, `assurance_runs`, `outcomes`, `delegations`, `recovery_plans`). Genuinely absent evidence becomes a `limitations` sentence, never a fabricated `EvidenceReference` with an invented ID. The canonical digest is computed over evidence content only (excluding the Passport's own `id`/`generated_at`), so identical underlying state always produces the same digest.

Two contract gaps were found and worked around rather than blocking on them: `CredentialBrokerPort.issue_grant` has no `provider` parameter even though `CredentialGrant.provider` is required (inferred from the scope prefix), and `OutcomePort.refresh(change)` takes no actor/grant even though GitHub access needs a resolved token (worked around with a constructor-supplied `read_grant_id`); `ChangeView` also has no GitHub repository slug, resolved read-only via `git remote get-url origin` (`backend.app.providers.repository_slug`). Both are flagged in code comments and in the AC-8 handoff for `[SD]` reconciliation.

**AC-6 (scriptable CLI) and AC-7 (interactive terminal UI) are blocked**, not merely unstarted: `typer`, `rich`, and `textual` are not in `pyproject.toml` (a `[SD]`-owned dependency decision), and most of the routes those commands would call (`assure`/`outcome`/`recovery`/`passport`) do not exist yet because Gate 3 API wiring has not happened. Detailed remaining work is in `backend/app/cli/AC_REMAINING_WORK.md`.

Verification: `python -m pytest` on AC-owned paths: **90 passed, 1 skipped** (opt-in Windows Credential Manager test, run separately and confirmed against the real OS credential store). Full repository-wide suite: **255 passed, 1 skipped**, no regressions. `python -m compileall -q backend`: passed. A grep audit of every AC-owned module confirmed no `print`/`logging` call exists anywhere that could leak a secret.

Commits: `2672bc2`, `9a33210`, `d0ff17d`, `f062414`, `30babfe`, `34557df` — all pushed to `origin/master`.

### `[kb]` - 2026-09-19 00:01 -04:00 - Reviewed Person 2 milestones

All KB-0 through KB-6 assignments were checked against the implementation. The Git and execution foundation is verified; the missing shared contracts still prevent a complete checkpoint/launcher/environment/dependency/assurance stream. The owner handoff now gives an explicit per-assignment status table rather than treating test coverage as whole-product completion.

The recheck corrected invalid numeric-bound handling and passed **150 tests** with **100% statement/branch coverage** for Git and execution. At the user's request, the untracked `.vscode/settings.json` was removed and work was organized into three commits: execution (`5bf01cb`), Git (`47ea584`), and the documentation commit containing this record.

For subsequent Person 2 work, the user requests `[kb]` tags, timestamps and milestone updates, including in commit messages. This reporting preference does not transfer ownership or bypass independent verification.

### `[KB]` - 2026-09-18 23:57 -04:00 - Git and execution foundations hardened

Person 2 continued the owned implementation using the existing `GitInspectionPort` and `VerificationPort`. Git observation now has bounded capture, command-hook suppression, read-only regression coverage, stable malformed-evidence errors and best-effort movement detection. A new bounded verification runner under `backend/app/execution/` strips inherited credential/injection variables and enforces pipe deadlines without descendant supervision. Its API integration is demonstrated through test-time dependency injection; production composition remains Person 1's responsibility.

The full suite passes **139 tests**, with **100% statement and branch coverage** across the Git and execution packages. Real Windows repository, subprocess, API and SQLite-restart boundaries are covered. Detailed commands, risks and limitations are in `backend/app/git/KB_HANDOFF.md` and `PROJECT_CONTEXT.md`.

The five planned shared Person 2 ports are still missing, so this is foundation hardening rather than a completed evidence/execution/assurance stream. No private replacement domain contracts, new causal observation, sandboxing or replay capabilities were introduced. Active Git content filters and submodules are explicitly unsupported in the legacy inspector; repeated reads do not prove an atomic checkpoint.

### `[KB]` - 2026-09-18 23:41 -04:00 - Evidence stream compatibility audit

The full proposal, active plan, coordination rules, repository source and tests were reviewed for the Person 2 assignment. The baseline suite passes with **49 tests** (`python -m pytest`, 7.31 seconds), including existing uncommitted Git adapter work that this audit preserved. This establishes the older Git review foundation only; it does not establish the retained proposal's end-to-end acceptance.

The planned `GitStatePort`, `AgentLauncherPort`, `EnvironmentPort`, `DependencyPort`, and `AssurancePort` are not present in the shared contracts. Only `GitInspectionPort` and `VerificationPort` currently exist. Person 2 implementation remains blocked on the versioned models/ports and `[SD]` comprehension acknowledgement required by the coordination rules. The detailed comprehension statement, contract-change request, test matrix and review findings are recorded in `PROJECT_CONTEXT.md`.

Review reproduced parent-environment inheritance into verification output with a synthetic secret canary and a raw error for malformed Git numstat. Static review identified post-capture output truncation, missing Git text-conversion suppression, and missing checkpoint-bound freshness. These are unresolved implementation findings, not new product capabilities. The older runner must not be treated as satisfying the new launcher's secret or bounded-capture requirements.

Both context updates were explicitly requested by the user. They do not constitute independent `[SD]` acceptance, contract freeze, permission to overwrite another owner's work, or completion of KB-1 through KB-6. No runtime implementation was changed by this audit.

### `[SD]` - 2026-09-18 23:27:01 -04:00 - Contributor execution and verification standard

`[KB]` and `[AC]` now have detailed, parallel, end-to-end work packets that finish their respective streams against frozen ports and conforming fakes before `[SD]` integrates them. Direct comprehension of the full proposal PDF is mandatory; each contributor must connect its work to proposal principles and pages while honoring the four approved cuts and their dependent limitations.

Testing is required at unit, port-contract, real-boundary, adversarial, security/privacy, owner-local flow, and terminal/manual layers as appropriate. Handoffs include exact commands, pass counts, coverage, real-versus-fake boundaries, manual evidence, limitations, security review, and integration instructions. `[SD]` independently reviews both complete streams, returns defects to their owners, and only then performs migrations, composition, full-system verification, and release acceptance.

### `[SD]` - 2026-09-18 23:24:10 -04:00 - Terminal UI clarified as active scope

Only the browser web UI is deferred. `[AC]` owns both scriptable CLI commands and a polished interactive terminal UI using Typer, Rich, and Textual. The terminal experience must provide visual hierarchy, semantic colours, panels, tables, progress, guided forms, recovery confirmation, and Passport export while sourcing all decisions from the API.

Terminal accessibility and automation are mandatory: statuses pair colour with text/symbols; keyboard navigation, resize/small-terminal behavior, `NO_COLOR`/`--no-color`, plain non-TTY output, and JSON output are acceptance requirements. `[SD]` independently verifies these behaviors before integration.

### `[SD]` - 2026-09-18 23:20:58 -04:00 - Backend verification ownership

The active phase defers browser UI work. `[SD]` owns shared contracts/core, migrations, application composition, independent acceptance tests, review decisions, and final backend integration. `[KB]` implements the evidence/execution/assurance stream; `[AC]` implements identity/authority, broker/provider outcomes, recovery, Passport, CLI, and the interactive terminal UI.

Every `[KB]` and `[AC]` handoff must pass an independent `[SD]` review before integration. `[SD]` adds black-box/adversarial tests and returns defects to the owning contributor rather than modifying feature-owned paths. The browser frontend remains unassigned until a later scope update.

### `[SD]` - 2026-09-18 23:13:27 -04:00 - Proposal implementation scope reset

The proposal is now the active product baseline and the two-day prototype limit has been removed. The retained architecture includes Change lifecycle/contracts, identity and scoped authority, credential brokering, a top-level Agent Launcher, Git/environment/dependency evidence, assurance, GitHub outcomes, constrained Git/provider recovery, Passport, UI, and CLI.

Only the event journal, process supervisor, filesystem tracker, and tool registry are cut. Replay, descendant attribution, local-file/environment rollback, and tool trust are explicitly unsupported because the removed primitives are prerequisites. The detailed work is divided across `[SD]`, `[KB]`, and `[AC]` with exclusive paths and gated integration in `BACKEND_IMPLEMENTATION_PLAN.md` and `AGENT_COORDINATION.md`.

Earlier records below describe the completed Git review foundation at the time it was built. They remain historical evidence and do not define the new final product scope.

### `[SD]` - 2026-09-18 22:22:49 -04:00 - Person 1 CORE foundation

#### Assignment and ownership

`[SD]` accepted the Person 1 assignment covering the `[INTEGRATION]` bootstrap and `[CORE]` backend areas. Work was limited to root Python configuration, `backend/app/main.py`, `backend/app/contracts/`, `backend/app/core/`, and `backend/tests/core/`. No files owned by `[GIT]`, `[VERIFY]`, `[QA]`, or `[UI]` were created or edited.

The required context was read before implementation in this order: `OVERALL_CONTEXT.md`, `PROJECT_CONTEXT.md`, `BACKEND_IMPLEMENTATION_PLAN.md`, and `AGENT_COORDINATION.md`.

#### Runtime and project bootstrap

- Added `pyproject.toml` for Python 3.12 or newer.
- Selected FastAPI, Pydantic v2, standard-library SQLite, Uvicorn, pytest, and HTTPX.
- Configured editable installation and backend test discovery.
- Added `.gitignore` entries for Python caches, local virtual environments, coverage data, SQLite files, local Change Assurance data, and editable-install metadata.
- Confirmed installation under Python 3.14.2 using `python -m pip install -e ".[test]"`.

#### Frozen shared contracts

Added strict Pydantic contracts in `backend/app/contracts/models.py` and adapter protocols in `backend/app/contracts/ports.py`.

The shared contract now defines:

- Change creation, Change views, and paginated-list response shape.
- Repository validation input and canonical repository information.
- Changed-path status, category, staging state, line statistics, binary state, and optional previous path.
- Git summary including branch, HEAD SHA, cleanliness, changed files, totals, bounded patch, truncation state, untracked-patch omission, and refresh time.
- Verification request as an executable plus argument array and bounded timeout; no shell command string is accepted.
- Verification result including status, exit code, duration, stdout, stderr, output truncation, and timestamps.
- Review states: `NO_CHANGES`, `MISSING_EVIDENCE`, `FAILED_VERIFICATION`, and `READY_FOR_HUMAN_REVIEW`.
- Stable health and error-envelope response models.
- `GitInspectionPort.validate_repository` and `GitInspectionPort.inspect` for Person 2.
- `VerificationPort.run` for Person 3.

Contracts reject undeclared fields and apply explicit length, range, timezone-awareness, UUID, and Git SHA validation where applicable.

#### Persistence

Added a standard-library SQLite boundary and parameterized Change repository.

- The database initializes idempotently and creates its parent data directory.
- SQLite uses foreign-key enforcement and a five-second busy timeout.
- The `changes` table stores Change identity, intent, canonical repository path, timestamps, and only the latest Git and verification JSON documents.
- Git and verification JSON is validated through the frozen Pydantic contracts when read back.
- Change metadata supports create, get, newest-first list, latest-Git update, latest-verification update, and delete.
- Persistence was verified across separate SQLite connections.
- Deletion removes Change metadata only and never touches the selected repository.
- Refreshing Git evidence clears the previous verification result so stale passing evidence cannot mark newly refreshed code ready.

#### Core services and review behavior

Added a Change service that composes persistence with the two adapter ports.

- Change creation validates and canonicalizes the selected repository through `GitInspectionPort` before persistence.
- Git refresh uses the configured one-megabyte patch limit.
- Verification uses the configured 256 KiB output limit.
- Unknown Change identifiers return the stable `CHANGE_NOT_FOUND` error.
- Review-state calculation is pure and deterministic.
- No Git evidence or a clean working tree produces `NO_CHANGES`.
- Changed files without verification produce `MISSING_EVIDENCE`.
- Any non-passing verification produces `FAILED_VERIFICATION`.
- Changed files plus a passing verification produce `READY_FOR_HUMAN_REVIEW`.
- Readiness remains a review-evidence summary and is not described as correctness proof.

#### HTTP API

Implemented these versioned routes:

- `GET /api/v1/health`
- `POST /api/v1/repositories/validate`
- `POST /api/v1/changes`
- `GET /api/v1/changes`
- `GET /api/v1/changes/{change_id}`
- `POST /api/v1/changes/{change_id}/refresh`
- `POST /api/v1/changes/{change_id}/verify`
- `DELETE /api/v1/changes/{change_id}`

The API has a FastAPI application factory, lifespan-based database initialization, bounded list parameters, response models, loopback-oriented configuration, and CORS restricted to the configured local UI origin.

Application errors use the documented `{ "error": { "code", "message", "details" } }` envelope. Request-validation responses omit submitted values so repository paths and other sensitive input are not echoed. Unexpected exceptions are logged server-side and returned as a generic `INTERNAL_ERROR` without a stack trace or local path.

Until adapter handoff, explicit unavailable adapters return `CAPABILITY_UNAVAILABLE`; they do not provide fake success results. Contract-conforming fakes exist only under CORE tests.

#### Verification performed

- `python -m pytest`: 13 tests passed.
- `python -m compileall -q backend`: passed.
- OpenAPI generation: passed and listed all expected routes.
- Live Uvicorn check on `127.0.0.1:8765`: health and OpenAPI requests returned HTTP 200.
- Health response was `{"status":"ok","api_version":"1"}` from the running backend.
- Working tree was clean after the implementation commits.

Tests cover strict contract validation, JSON round trips, all review-state branches, persistence across connections, metadata deletion, canonical repository-path use, complete create-refresh-verify behavior, verification invalidation after refresh, stable missing-Change errors, and sanitized validation failures.

#### Commits

- `5c6c587` - `[INTEGRATION] Bootstrap Python backend`
- `d4431d8` - `[CORE] Add contracts persistence and API`

At the time of this record, local `master` was two commits ahead of `origin/master`; the commits had not been pushed by `[SD]`.

#### Handoff and remaining work

Person 2 must implement `GitInspectionPort` without editing shared contracts. Person 3 must implement `VerificationPort` without editing shared contracts. Adapter domain failures should use or extend `AppError` so the HTTP layer can preserve stable error codes rather than converting expected failures into `INTERNAL_ERROR`.

Person 1's concrete adapter wiring remains pending the two formal handoffs. Real Git inspection, real verification execution, integration fixtures, end-to-end tests, and UI integration are not claimed as complete by this record.

### `[AC]` - 2026-09-18 22:40:41 -04:00 - Person 3 VERIFY implementation

#### Assignment and ownership

`[AC]` accepted the Person 3 assignment covering the `[VERIFY]` verification module described in `BACKEND_IMPLEMENTATION_PLAN.md` (steps V1-V3). Work was limited to `backend/app/verification/` and `backend/tests/verification/`. No files owned by `[CORE]`, `[GIT]`, `[QA]`, or `[UI]` were created or edited, and the frozen contracts were consumed, not modified.

The required context was read before implementation: `OVERALL_CONTEXT.md`, `PROJECT_CONTEXT.md`, `BACKEND_IMPLEMENTATION_PLAN.md`, and `AGENT_COORDINATION.md`. Because no bootstrap or frozen contracts existed at the start of this work, implementation was deliberately held until Person 1's `[INTEGRATION]`/`[CORE]` commits were pulled, per the plan's Gate 0/Gate 1 sequencing.

#### Command validation (V1)

- Added an executable allowlist matching the plan's demo list (`python`, `python3`, `pytest`, `uv`, `node`, `npm`, `npm.cmd`, `pnpm`, `pnpm.cmd`, `yarn`, `yarn.cmd`, `cargo`, `go`, `dotnet`).
- Rejected any executable containing a path separator, so only bare allowlisted names are accepted.
- Resolved the executable with `shutil.which` and distinguished "not allowed" from "not found" using two separate stable error codes.
- Left argument-count, argument-length, and timeout-range enforcement to the already-frozen `VerificationRequest` contract rather than re-implementing bounds the contract already guarantees.

#### One-shot execution and bounds (V2-V3)

- Implemented `SubprocessVerificationRunner`, the concrete `VerificationPort`, using `subprocess.run` with an argument list, `shell=False`, and `cwd` set to the canonical repository root.
- Captured stdout and stderr separately, recorded monotonic duration and UTC start/completion timestamps, and classified exit code 0 as `PASSED` and any other exit code as `FAILED`.
- Enforced the requested timeout on the direct child process only; a `subprocess.TimeoutExpired` produces a `TIMED_OUT` result with a null exit code rather than an unhandled exception. Descendant-process supervision and orphan cleanup are explicitly out of scope, consistent with this document's recovery/environment non-goals.
- Bounded stdout and stderr independently to the configured output limit and set a combined `output_truncated` flag when either stream was cut.

#### Verification performed

- `python -m pytest backend/tests/verification`: 11 tests passed, covering allowlist rejection, path-separator rejection, missing-executable resolution, pass/fail/timeout results, working-directory propagation, and output truncation.
- Full backend suite after pulling Person 2's Git adapter commit: 29 tests passed (13 CORE + 5 GIT + 11 VERIFY), no regressions in other owners' tests.

#### Commits

- Not yet committed at the time of this record; commit and push both require this developer's explicit approval before they happen.
- Local `master` was fast-forwarded to `d4ed137` (`[KB]` Person 2 Git inspection) immediately before this work was recorded.

#### Handoff and remaining work

Person 1 can wire the concrete adapter with `backend.app.verification.runner.SubprocessVerificationRunner()` (no constructor arguments) into `create_app(verification=...)` once ready for Gate 3 concrete wiring; `backend/app/main.py` itself was intentionally left unedited by this record. After that handoff is acknowledged, Person 3 switches to `[QA]`: integration fixtures, API integration tests, and the demo smoke test are not yet started.

### `[SD]` - 2026-09-18 22:57:28 -04:00 - Adapter recovery and Gate 3 integration

`[SD]` reviewed the Person 2 and Person 3 implementations against the frozen contracts and exercised both concrete adapters through real boundaries. The original 29-test suite passed, but a real create request failed because the Git adapter returned dictionaries rather than `RepositoryInfo` and `GitSummary`. Additional probes found incorrect porcelain-v2 flags, omitted rename/conflict records, double-counted staged diff statistics, untracked-file reads, unstable Git errors, character-based patch truncation, and independent stdout/stderr output budgets.

With explicit user authorization to correct cross-owner work, `[SD]` completed the recovery and integration pass:

- Reimplemented `GitRepositoryInspector` as a concrete `GitInspectionPort` returning frozen Pydantic contracts.
- Added stable `AppError`-based Git codes for invalid paths, non-Git directories, repositories without commits, and Git command failures.
- Implemented porcelain-v2 record parsing for ordinary, rename/copy, conflict, untracked, and ignored records.
- Corrected `.` staged/unstaged semantics and create/modify/delete/conflict classification.
- Replaced double-counted statistics with one `git diff --numstat -z HEAD --` source.
- Mapped per-file additions, deletions, and binary state, including rename-safe NUL parsing.
- Stopped reading untracked file contents; untracked paths are reported with unknown statistics and an explicit omission flag.
- Separated untracked omission from tracked-patch truncation.
- Enforced UTF-8 byte-accurate Git patch truncation.
- Expanded deterministic classification for dependency manifests, test/spec patterns, CI/configuration directories, documentation, source, and other paths.
- Changed verification output limiting to one shared stdout/stderr byte budget with UTF-8-safe truncation.
- Added verification startup-error handling that returns `VerificationStatus.ERROR` without leaking the operating-system exception.
- Wired `GitRepositoryInspector` and `SubprocessVerificationRunner` as the default FastAPI adapters.
- Added real API integration tests using temporary committed Git repositories and real verification subprocesses.
- Added API coverage for passing, failing, timed-out, output-truncated, disallowed, and repository-validation outcomes.

Acceptance evidence at this checkpoint:

- `python -m pytest`: 48 tests passed in 9.39 seconds.
- The complete suite passed twice from separate test-process invocations.
- `python -m compileall -q backend`: passed.
- Both concrete classes satisfy their runtime-checkable frozen ports.
- A live Uvicorn server on `127.0.0.1:8765` returned HTTP 200 for health and OpenAPI.
- The live health response remained `{"status":"ok","api_version":"1"}`.
- The old Person 1 smoke-test server process that had retained port 8765 was identified by exact PID/command line and stopped before the final live check; no test server remained listening afterward.

The backend has now crossed Gate 3: concrete adapters are wired and the real create -> modify -> refresh -> verify -> ready-for-human-review path passes. UI integration can proceed against the real API. Broader product acceptance still requires the UI to remove final mock data and exercise this backend flow.
