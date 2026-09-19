# Change Assurance Runtime - Three-Person Implementation Plan

## 1. Authority and outcome

This plan implements `Change_Assurance_Runtime_Project_Proposal (2).pdf` without a two-day deadline. The proposal is the product baseline. Only these four subsystems are removed:

1. Event/effect journal.
2. Process supervisor.
3. Filesystem tracker.
4. Tool registry.

The result is a local-first Change Assurance control plane that binds intent, actors, authority, Git state, environment and dependency evidence, assurance results, provider outcomes, and a final Change Passport. It must not claim observation, attribution, replay, or recovery that the four removed primitives would have supplied.

## 2. Scope consequences

| Removed subsystem | Removed capability | What remains |
| --- | --- | --- |
| Event journal | Causal event stream, trace timeline, tamper-evident event chain, effect replay | Durable current state, immutable result records, timestamps, and final Passport evidence |
| Process supervisor | Descendant-process ownership, orphan cleanup, process-tree policy, child-effect attribution | A top-level Agent Launcher that starts or attaches to one invocation and stores a bounded aggregate execution summary |
| Filesystem tracker | Write interception, before-images, resource versions, uncommitted-file undo, conflict-aware local restoration | Read-only Git state/checkpoints and explicitly approved Git-native recovery on a dedicated Change branch |
| Tool registry | Tool manifests, MCP/tool inventory, signatures, trust decisions, capability-drift checks | Agent adapter metadata and ordinary dependency provenance only |

These cuts also mean:

- The proposal's replay engine and replay UI are not implementable and are removed.
- Environment drift may be compared between checkpoints, but cannot be causally attributed to a process.
- Local uncommitted file recovery and environment rollback are unsupported.
- Recovery is limited to reversible Git commits and supported provider operations.
- There will be no `/events`, `/effects`, `/replay`, `/tools`, or filesystem-snapshot APIs or tables.

## 3. Retained product capabilities

- Persistent Change lifecycle and enforceable Change Contract.
- Actor identity, agent identity, delegations, and scoped authority.
- Local GitHub credential broker that keeps durable credentials out of agent processes.
- Policy and risk evaluation before privileged operations.
- Agent-neutral launch/attach adapters with bounded aggregate results.
- Git repository validation, checkpoints, status, diff, and branch continuity.
- Environment passports and checkpoint-to-checkpoint drift comparison.
- Dependency manifest/lockfile discovery and dependency-change analysis.
- Assurance discovery, selection, execution, evidence coverage, and contract-deviation checks.
- GitHub pull-request and CI outcome tracking.
- Constrained Git/provider recovery with dry-run, approval, and post-action verification.
- A Change Passport containing intent, authority, evidence, assurance, outcomes, limitations, and recovery status.
- A real web UI and CLI backed by the same versioned API.

### 3.1 Proposal coverage matrix

| Proposal area | Decision | Owner | Implementation interpretation |
| --- | --- | --- | --- |
| Change object, contract, lifecycle | Keep | `[SD]` | Durable root, guarded state, freshness and idempotency |
| Actor/agent identity and delegation | Keep | `[SD]` | Scoped, expiring, revocable authority |
| Credential broker | Keep | `[SD]` | OS-backed secrets and brokered GitHub operations |
| Process supervisor | Cut | None | Replaced only by a top-level launcher; no process tree |
| Filesystem tracker | Cut | None | Git checkpoints remain, without filesystem attribution or snapshots |
| Event/effect journal | Cut | None | Ordinary entity/result persistence remains, without a causal stream |
| Environment tracker | Keep | `[KB]` | Redacted passports and drift comparison |
| Dependency tracking | Keep | `[KB]` | Manifest/lockfile comparison without causal attribution |
| Tool registry/supply-chain trust | Cut | None | No tool inventory, signatures, or trust decisions |
| Assurance engine | Keep | `[KB]` | Discovery, selection, bounded checks, and evidence coverage |
| Recovery engine | Keep with reduced boundary | `[SD]` | Git commit and provider compensation only |
| Replay engine | Remove as dependency | None | Cannot be implemented without the event journal/process/filesystem evidence |
| Git/PR/CI continuity | Keep | `[KB]` + `[AC]` | Git evidence by `[KB]`; provider outcomes by `[AC]` |
| Change Passport | Keep | `[SD]` | Aggregated retained evidence plus limitations |
| UI and CLI | Keep | `[AC]` | Complete real-data workflow and unsupported states |

## 4. Architecture

```text
Web UI / CLI
      |
      v
Local authenticated API
      |
      +-- Change Service + Contract + State Machine
      +-- Identity / Delegation / Policy
      +-- Credential Broker ------> GitHub API
      +-- Agent Launcher ---------> top-level invocation only
      +-- Git State Tracker ------> local Git repository
      +-- Environment Tracker ----> host/repository facts
      +-- Dependency Tracker -----> manifests and lockfiles
      +-- Assurance Engine -------> bounded checks
      +-- Outcome Tracker --------> PR and CI state
      +-- Recovery Engine --------> approved Git/provider compensations
      +-- Passport Builder
      |
      v
SQLite evidence and state store
```

No component is renamed to conceal a removed subsystem. `ExecutionSummary` is one aggregate record per invocation, not an event journal, and the Agent Launcher is not a process supervisor.

## 5. Technology baseline

- Python 3.12+, FastAPI, Pydantic v2, SQLite, and explicit schema migrations.
- React, TypeScript, and Vite for the web UI.
- A typed API client pinned to the OpenAPI contract.
- Typer for the local CLI.
- Subprocess argument arrays, `shell=False`, bounded output, and bounded runtime.
- Windows Credential Manager behind a narrow credential-store port; tests use an in-memory fake.
- GitHub REST APIs behind a provider port. Durable secrets never enter Change records, logs, result payloads, or agent environments.

## 6. Domain model and persistence

All durable entities have stable IDs, UTC timestamps, schema versions, and explicit relationships.

| Entity | Minimum responsibility |
| --- | --- |
| `Change` | Intent, repository identity, owner, lifecycle state, risk, timestamps |
| `ChangeContract` | Allowed/forbidden paths, expected outcomes, required checks, authority ceiling |
| `Actor` | Human, agent, or service identity and provenance |
| `Delegation` | Grantor, grantee, scopes, boundary, expiry, revocation |
| `AgentRun` | Adapter, top-level invocation, start/end, exit status, bounded summary; no process graph |
| `GitCheckpoint` | Branch, HEAD, status digest, changed paths, bounded diff, capture time |
| `EnvironmentPassport` | OS/runtime/toolchain/package-manager facts and redacted configuration fingerprints |
| `DependencyChange` | Ecosystem, package, old/new version, confidence, risk notes |
| `AssurancePlan` | Selected checks, rationale, required checks, coverage gaps |
| `AssuranceRun` | Check identity, result, exit code, duration, bounded output, evidence references |
| `CredentialGrant` | Provider, scopes, expiry, Change binding, revocation; never a provider secret |
| `ProviderOperation` | GitHub operation, authorization, idempotency key, final result |
| `Outcome` | PR, CI, artifact, or deployment reference and observed status |
| `RecoveryPlan` | Compensations, preconditions, unsupported effects, conflicts, approval |
| `RecoveryAction` | One approved compensation and verified result |
| `ChangePassport` | Versioned export of retained evidence and limitations |

Forbidden persistence concepts: `Event`, `Effect`, `ProcessTree`, `ResourceVersion`, `BeforeImage`, `FilesystemSnapshot`, `ToolRecord`, and replay traces.

Migrations extend the existing SQLite database in place. Existing Change, Git summary, and verification records must be migrated or exposed through compatibility adapters; user data must not be reset.

## 7. Lifecycle and transition guards

```text
DRAFT -> ACTIVE -> LOCALLY_VERIFIED -> REVIEW_READY -> PR_OPEN
      -> CI_VERIFIED -> ARTIFACT_BUILT -> DEPLOYED -> OBSERVING -> STABLE
```

Exceptional states are `BLOCKED`, `FAILED`, and `CANCELLED`. Recovery separately uses `PLANNED -> APPROVED -> EXECUTING -> RECOVERED | PARTIAL | RECOVERY_FAILED`; it does not rewrite history.

Required guards:

- `ACTIVE`: valid repository, contract, actor, and authority context.
- `LOCALLY_VERIFIED`: all required local checks have fresh passing results for the current Git checkpoint.
- `REVIEW_READY`: contract deviations are resolved or accepted and evidence gaps are visible.
- `PR_OPEN`: the provider operation was authorized and the PR identity recorded.
- `CI_VERIFIED`: required checks pass for the recorded commit SHA.
- Later states require real adapter evidence; unsupported stages are skipped, not fabricated.
- `STABLE`: configured observation criteria are met with no unresolved recovery action.

Transitions use optimistic concurrency and idempotency. A new Git checkpoint invalidates stale assurance and downstream readiness.

## 8. Versioned API

- `/api/v1/changes`: create, list, retrieve, update contract, transition, cancel.
- `/api/v1/changes/{id}/runs`: launch, attach metadata, stop top-level invocation if supported, retrieve aggregate result.
- `/api/v1/changes/{id}/git`: validate, checkpoint, status, diff, compare.
- `/api/v1/changes/{id}/environment`: capture and compare drift.
- `/api/v1/changes/{id}/dependencies`: scan and retrieve changes/risk.
- `/api/v1/changes/{id}/assurance`: discover, plan, run, retrieve.
- `/api/v1/actors` and `/api/v1/delegations`: identity and scoped grants.
- `/api/v1/providers/github`: connection, grants, PR actions, CI refresh, revoke.
- `/api/v1/changes/{id}/outcomes`: provider outcome summaries.
- `/api/v1/changes/{id}/recovery`: preview, approve, execute, verify.
- `/api/v1/changes/{id}/passport`: build, retrieve, export.
- `/api/v1/capabilities`: supported, unavailable, and configured capabilities.

Every mutation accepts an idempotency key. Errors retain the safe `{ "error": { "code", "message", "details" } }` envelope. Secrets, raw environment values, and credential locations never appear in responses.

## 9. Person 1 - `[SD]` platform, authority, and recovery

Exclusive paths: `backend/app/contracts/`, `core/`, `identity/`, `policy/`, `credentials/`, `recovery/`, `passport/`, `backend/app/main.py`, `backend/migrations/`, and matching unit-test directories.

1. **P1.1 Migration and compatibility foundation**
   - Ordered migrations and schema-version tracking.
   - Preserve current data/API behavior during migration.
   - Repository/unit-of-work boundaries and optimistic concurrency.
2. **P1.2 Contracts and state machine**
   - Freeze entities, ports, requests, responses, and errors.
   - Implement guarded transitions, freshness, capabilities, and idempotency.
3. **P1.3 Local API identity**
   - Loopback by default, per-install/session bearer credential, and origin/CSRF defenses.
4. **P1.4 Actors, delegation, policy, and risk**
   - Scoped, expiring, revocable delegation.
   - Path, operation, provider, and risk policy with stable denial reasons.
5. **P1.5 GitHub credential broker**
   - Durable provider credentials only in Windows Credential Manager.
   - Short-lived internal capability grants bound to actor, Change, scopes, and expiry.
   - Proxy allowed GitHub calls and redact every secret boundary.
6. **P1.6 Recovery engine**
   - Dry-run and approved revert of commits on a dedicated Change branch.
   - Test in a temporary worktree, report conflicts, create a revert commit, verify new SHA.
   - Provider compensation for Change-created draft PRs/branches when policy permits.
   - Explicitly mark local uncommitted files, environment changes, and unknown effects unsupported.
7. **P1.7 Passport and composition**
   - Build the Passport from all ports and own application wiring, release migrations, and capability reporting.

## 10. Person 2 - `[KB]` evidence, execution, and assurance

Exclusive paths: `backend/app/git/`, `execution/`, `environment/`, `dependencies/`, `assurance/`, and matching unit-test directories.

1. **P2.1 Git State Tracker**
   - Extend inspection into named checkpoints and comparisons.
   - Record branch/HEAD/status/diff without normal repository mutation.
   - Detect staleness, branch movement, conflicts, and detached HEAD.
2. **P2.2 Agent Launcher**
   - Codex, Claude, and generic adapters over one launch port.
   - Validate command, cwd, environment allowlist, timeout, and output bounds.
   - Store top-level aggregate results only and expose lack of descendant control.
   - Attach mode records supplied metadata without pretending to observe execution.
3. **P2.3 Environment Tracker**
   - Capture redacted Windows/OS, runtime, compiler, package-manager, selected environment-key fingerprints, and repository facts.
   - Deterministically compare drift; never persist secret values.
4. **P2.4 Dependency Tracker**
   - Parse supported Python/Node manifests and lockfiles.
   - Identify direct changes, lockfile mismatch, risk, and unsupported ecosystems.
   - Never claim which process caused a change.
5. **P2.5 Assurance engine**
   - Discover pytest, Jest/Vitest, lint, type-check, build, and security/dependency checks.
   - Select checks from contract, path classification, and repository configuration.
   - Execute bounded checks, store structured results, invalidate stale results, expose coverage gaps.
6. **P2.6 Deviation and coverage analysis**
   - Compare paths, dependencies, and environment drift with the contract.
   - Produce deterministic findings consumed by lifecycle and UI.

## 11. Person 3 - `[AC]` experience, outcomes, and quality

Exclusive paths: `frontend/`, `backend/app/providers/`, `outcomes/`, `cli/`, `backend/tests/integration/`, `backend/tests/e2e/`, and `scripts/`.

1. **P3.1 Frontend foundation**
   - React/TypeScript app, typed client, routing, auth bootstrap, error boundary, accessible design system.
   - Loading, empty, stale, unsupported, denied, failure, and success states.
2. **P3.2 Onboarding and contract UX**
   - Repository, actor, intent, paths, outcomes, required checks, and authority review.
3. **P3.3 Active Change workspace**
   - Lifecycle, run summary, Git checkpoint, deviations, environment drift, dependencies, assurance, gaps.
   - No timeline and no process/file attribution language.
4. **P3.4 GitHub and outcomes**
   - GitHub operations only through Person 1's broker/port.
   - PR and required CI state tied to commit SHA.
   - Artifact/deployment only when real adapters exist; otherwise unsupported.
5. **P3.5 Recovery and Passport UX**
   - Dry-run actions, conflicts, unsupported effects, authority, confirmation, result, export.
6. **P3.6 CLI**
   - Equivalent create/status/checkpoint/assure/outcome/recovery/passport flows through the API; no policy bypass.
7. **P3.7 Integration and E2E QA**
   - Temporary repositories, fake GitHub contract server, browser tests, accessibility, failure injection, release smoke tests.

## 12. Parallel execution and intersection gates

### Gate 0 - Scope and contracts

Owner `[SD]`; reviewers `[KB]` and `[AC]`. Freeze cuts, capability matrix, ports, IDs, errors, and OpenAPI names. No consumer implementation begins until all three acknowledge the handoff.

Exit: contract tests compile, forbidden entities/endpoints are absent, and current tests pass.

### Gate 1 - Independent foundations

- `[SD]`: migrations, lifecycle, local auth, identity, policy.
- `[KB]`: Git checkpoints, launcher, environment/dependencies, assurance discovery.
- `[AC]`: frontend shell with contract fixtures, provider fake, E2E harness.

No shared source edits. Feedback is a contract-change request to `[SD]`.

Exit: each module passes unit/contract tests and has a formal handoff.

### Gate 2 - Evidence composition

Single integration window owned by `[SD]`: `[KB]` hands off ports, `[SD]` wires lifecycle/freshness/risk/Passport, then `[AC]` updates the typed client after OpenAPI refreezes.

Exit: create -> activate -> checkpoint -> environment/dependencies -> assurance -> review-ready passes through the API.

### Gate 3 - Authority and provider integration

- `[SD]` provides broker/policy ports and an in-memory provider double.
- `[AC]` implements GitHub operations only through those ports.
- `[KB]` supplies evidence/risk inputs and never handles secrets.

Exit: scoped operations succeed; expired, revoked, wrong-Change, and over-scoped grants fail; credentials never reach agent environment, logs, SQLite, or responses.

### Gate 4 - UI vertical slices

`[AC]` integrates frozen APIs. Backend defects return to the owning tag; `[AC]` does not patch backend-owned files.

Exit: browser tests cover onboarding, evidence, assurance, provider outcomes, denied/unsupported states, and Passport export with real responses.

### Gate 5 - Recovery integration

- `[SD]`: recovery plan/execution and temporary-worktree safety.
- `[KB]`: pre/post Git checkpoints and assurance verification.
- `[AC]`: confirmation UX, provider compensation adapter, E2E scenarios.

Exit: committed Change-branch recovery creates a verified revert; conflicts cause no target mutation; unsupported effects are visible.

### Gate 6 - Release candidate

`[SD]` freezes integration. `[AC]` runs the full release matrix; owners fix only their modules. Context and acceptance evidence are updated after results are known.

Exit: all section 17 criteria pass from a clean clone and an upgraded existing database.

## 13. Shared ports

Person 1 owns signatures; concrete owners are:

- `GitStatePort`, `AgentLauncherPort`, `EnvironmentPort`, `DependencyPort`, `AssurancePort` -> `[KB]`.
- `CredentialStorePort`, `CredentialBrokerPort`, `PolicyPort`, `RecoveryPort`, `PassportPort` -> `[SD]`.
- `ProviderPort`, `OutcomePort` -> `[AC]`.

Ports exchange immutable Pydantic models, not dictionaries. Side effects require authority context and an idempotency key. Changes require owner review and a versioned handoff.

## 14. Recovery semantics

Supported:

- Preview/revert known commits on a dedicated Change branch.
- Conflict detection in a temporary worktree before target mutation.
- New revert commits; never reset/rewrite shared history.
- Authorized compensation of Change-created provider objects.
- Post-recovery Git capture and required assurance checks.

Unsupported:

- Restoring uncommitted/ignored files or filesystem metadata.
- Reversing arbitrary shell, package-manager, service, process, or host effects.
- Recovering effects not represented by known commits/provider objects.
- Recovery without explicit human approval.

Every preview lists actions, unsupported effects, assumptions, conflicts, and evidence freshness. Failed or partial recovery remains visible in the Passport.

## 15. Security and privacy

- Loopback-only by default; non-loopback requires an explicit secure deployment mode.
- Authenticate non-health routes and authorize mutations.
- Store credentials only through the credential-store port; redact secrets before logging.
- Give subprocesses an allowlisted environment without broker credentials.
- Canonicalize repository paths and prevent constrained-path escape.
- Use argument arrays and `shell=False`; enforce executable/timeout policy.
- Bound patch, output, and database payload sizes.
- Never label a Change safe merely because checks passed.

## 16. Verification plan

- Migration tests against the current schema and populated fixtures.
- State, concurrency, idempotency, freshness, policy, and delegation tests.
- Git fixtures for staged/unstaged/untracked/rename/conflict/detached/branch movement and spaces.
- Launcher validation/timeout/output/startup-error tests plus explicit descendant-control limitation.
- Environment redaction/drift and dependency parser fixtures.
- Assurance discovery/selection/staleness/gap/timeout tests.
- Broker tests for revocation, expiry, binding, scope denial, and secret non-disclosure.
- GitHub adapter contract tests against a local fake, including rate limits and partial failure.
- Disposable-repository recovery tests for isolation, approval, conflict safety, idempotency, and verification.
- API tests for all envelopes and forbidden endpoint absence.
- Browser E2E, accessibility, keyboard, responsive, restart-persistence, clean-clone, and upgrade smoke tests.

## 17. Definition of done

1. A user creates a Change Contract, selects an actor/agent, and sees authority before activation.
2. The app launches or attaches to a top-level run without claiming descendant supervision.
3. Git, environment, and dependency checkpoints are real, persisted, comparable, and visibly fresh/stale.
4. Assurance is evidence-selected, bounded, and gates lifecycle transitions.
5. GitHub credentials remain brokered and never enter agent environment or application data.
6. PR and CI results are tied to the correct commit SHA.
7. The Passport exports real intent, actors, authority, checkpoints, deviations, assurance, outcomes, limitations, and recovery status.
8. Supported recovery requires preview/approval, is conflict-safe, and is verified.
9. UI and CLI show real missing, stale, unsupported, denied, failed, and partial states.
10. Event journal, process supervisor, filesystem tracker, tool registry, and replay are absent from code, storage, API, and claims.
11. Existing data upgrades successfully and the complete release matrix passes.

## 18. Handoff format

```text
[TAG] HANDOFF to [TAG]
Work item: P1.2 | P2.4 | P3.3
Status: ready | blocked
Changed paths: <exact list>
Contract/version: <port, endpoint, schema, OpenAPI hash>
Behavior and limitations: <facts>
Verification: <commands and results>
Consumer action: <next action>
```

No handoff may claim a capability that depends on one of the four removed subsystems.
