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
