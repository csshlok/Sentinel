# Change Assurance Runtime - Backend, Terminal UI, and Verification Plan

## 1. Authority and outcome

This plan implements the backend of `Change_Assurance_Runtime_Project_Proposal (2).pdf` without a two-day deadline. The proposal is the product baseline. The interactive terminal UI is part of this phase; only the browser-based web UI is deferred. One subsystem remains removed from the product architecture:

1. Filesystem tracker.

The event/effect journal and tool registry, originally cut alongside the process supervisor, were reversed by explicit user decision and are retained in bounded form — see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` for the full design, integration surface, and non-goals. The process supervisor, also originally cut, was first narrowed to top-level-only pause/resume (`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A) and has since been reversed to its original PDF scope — real Job Object-based process-tree supervision, descendant attribution, orphan cleanup, and restricted-token authority reduction — see `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A.

The result is a local-first Change Assurance control plane that binds intent, actors, authority, Git state, environment and dependency evidence, assurance results, provider outcomes, a per-Change event/effect journal, and a final Change Passport. It must not claim observation, attribution, or recovery that the two removed primitives would have supplied, nor replay/tool-trust capability beyond the bounded forms `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` defines.

## 2. Scope consequences

| Removed subsystem | Removed capability | What remains |
| --- | --- | --- |
| Filesystem tracker | Write interception, before-images, resource versions, uncommitted-file undo, conflict-aware local restoration | Read-only Git state/checkpoints and explicitly approved Git-native recovery on a dedicated Change branch |

Reversed (see `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A):

| Subsystem | Bounded form | Explicit non-goals |
| --- | --- | --- |
| Process supervisor | Windows Job Object-based process-tree supervision; every descendant PID attributed to the Change or explicitly marked unattributed with reason; restricted-token (Low integrity) authority reduction on the launched process; process-tree termination on recovery | No formal sandbox/namespace isolation claim; no macOS/Linux; filesystem-level effects still come from Git checkpoints only, not from process-level file-write interception |

Retained (bounded) — see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md`:

| Subsystem | Bounded form | Explicit non-goals |
| --- | --- | --- |
| Event/effect journal | Per-Change hash-chained record of mutations to entities this backend already models | No filesystem-write or process-spawn effect types; no cross-Change tamper evidence |
| Replay | Trace-only reconstruction and cryptographic verification of a Change's journal | No re-execution of any kind; no filesystem/controlled/forked replay |
| Tool registry | Trust lifecycle for the top-level launched executable and explicitly declared manifests, with Windows-Authenticode signature checks | No interception of a running agent's own tool/MCP calls; no sandboxing/enforcement of declared scope |

These cuts also mean:

- Local uncommitted file recovery and environment rollback are unsupported (filesystem tracker cut).
- Recovery is limited to reversible Git commits, supported provider operations, and (now) terminating a Change-owned process tree this process instance is still tracking; always requires approval.
- There will be no filesystem-snapshot APIs or tables. `/events`, `/replay`, and `/tools` exist in their bounded form (§8); process-tree supervision now has real API surface too (§8) since it is no longer cut.

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
- A scriptable CLI and polished interactive terminal UI backed by the versioned API.
- A stable API suitable for a later browser UI phase; no web frontend work occurs in this plan.

### 3.1 Proposal coverage matrix

| Proposal area | Decision | Owner | Implementation interpretation |
| --- | --- | --- | --- |
| Change object, contract, lifecycle | Keep | `[SD]` | Durable root, guarded state, freshness and idempotency |
| Actor/agent identity and delegation | Keep | `[AC]` | Scoped, expiring, revocable authority |
| Credential broker | Keep | `[AC]` | OS-backed secrets and brokered GitHub operations |
| Process supervisor | Keep (reversed to PDF scope) | `[KB]` | Windows Job Object process-tree supervision, descendant attribution, orphan cleanup, restricted-token authority reduction; pause/resume stays top-level-PID-only per `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A; see `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A |
| Filesystem tracker | Cut | None | Git checkpoints remain, without filesystem attribution or snapshots |
| Event/effect journal | Keep (bounded) | `[SD]` infra, `[KB]`/`[AC]` emission | Per-Change hash-chained record of mutations to entities already modeled; see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` Part A |
| Environment tracker | Keep | `[KB]` | Redacted passports and drift comparison |
| Dependency tracking | Keep | `[KB]` | Manifest/lockfile comparison without causal attribution |
| Tool registry/supply-chain trust | Keep (bounded) | `[SD]` infra, `[KB]` enforcement, `[AC]` surface | Top-level launched executable and declared manifests only; see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` Part B |
| Assurance engine | Keep | `[KB]` | Discovery, selection, bounded checks, and evidence coverage |
| Recovery engine | Keep with reduced boundary | `[AC]` | Git commit and provider compensation only |
| Replay engine | Keep (trace replay only) | `[SD]` core, `[AC]` surface | Deterministic reconstruction and hash-chain verification only, no re-execution; see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` §A.7 |
| Git/PR/CI continuity | Keep | `[KB]` + `[AC]` | Git evidence by `[KB]`; provider outcomes by `[AC]` |
| Change Passport | Keep | `[AC]` | Aggregated retained evidence plus limitations |
| CLI and terminal UI | Keep | `[AC]` | Scriptable commands plus a visual interactive workflow through the local API |
| Browser web UI | Deferred | None in this phase | Implement only after backend contracts and acceptance are complete |

## 4. Architecture

```text
Interactive terminal UI / CLI / API clients (browser UI deferred)
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
      +-- Tool Registry ----------> top-level executable + declared manifests only
      +-- Event/Effect Journal ---> per-Change hash chain
      +-- Replay Service ---------> trace-only reconstruction/verification of the journal
      +-- Passport Builder
      |
      v
SQLite evidence and state store
```

No component is renamed to conceal a removed subsystem. `ExecutionSummary` is one aggregate record per invocation, not an event journal, and the Agent Launcher is not a process supervisor.

## 5. Technology baseline

- Python 3.12+, FastAPI, Pydantic v2, SQLite, and explicit schema migrations.
- OpenAPI is frozen and validated so every interface consumes the same contracts.
- Typer for scriptable CLI commands and command routing.
- Rich for colour, tables, panels, progress, syntax/diff rendering, prompts, and consistent status semantics.
- Textual for the keyboard-driven interactive terminal application and reusable terminal components.
- Pytest plus coverage/branch reporting for unit, contract, acceptance, and integration evidence.
- Colour is never the only status signal. `NO_COLOR`, `--no-color`, non-TTY/plain output, and machine-readable JSON output are supported.
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

Forbidden persistence concepts: `ProcessTree`, `ResourceVersion`, `BeforeImage`, `FilesystemSnapshot`. `Event`, `Effect`, and `ToolRecord` (as `JournalEvent`/`JournalEffect`/`ToolManifest`) are retained in the bounded form defined by `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md`; nothing above authorizes a filesystem-write or process-spawn event type or effect.

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
- `/api/v1/changes/{id}/runs`: launch, attach metadata, stop, pause, resume top-level invocation if supported, retrieve aggregate result (incrementally visible while running, per `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part C) with attributed descendant-process list and restricted-token authority-reduction disclosure (`PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A).
- `/api/v1/identity/signing-key`, `/api/v1/changes/{id}/passport/export`: this operator's public signing key, and a signed export of a Change Passport (`PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A.7).
- `/api/v1/changes/{id}/fork`, `/api/v1/changes/{id}/forks`: fork a new Change from a captured checkpoint; list a Change's forks (`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part B).
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
- `/api/v1/changes/{id}/events`: paginated raw journal, filterable by `event_type`/`since_seq`.
- `/api/v1/changes/{id}/replay`, `/replay/verify`, `/replay/export`: trace reconstruction, cheap chain-verification, and redacted export.
- `/api/v1/tools`, `/api/v1/tools/{id}`, `/api/v1/tools/{id}/trust`, `/api/v1/changes/{id}/tools`: tool registry listing, detail, trust decisions, and per-Change observations.

Every mutation accepts an idempotency key. Errors retain the safe `{ "error": { "code", "message", "details" } }` envelope. Secrets, raw environment values, and credential locations never appear in responses.

## 9. Person 1 - `[SD]` verifier and integration lead

Exclusive paths: `backend/app/contracts/`, `backend/app/core/` (including `core/journal.py`, `core/replay_service.py`, `core/tool_registry_service.py`), `backend/app/main.py`, `backend/migrations/`, `backend/tests/acceptance/`, root configuration, OpenAPI snapshots, and project context/plan documents.

`[SD]` does not take feature work from `[KB]` or `[AC]`. `[SD]` defines shared contracts, reviews every handoff, writes independent acceptance/adversarial tests, and integrates only code that passes review. A defect is returned to its owner instead of silently repaired in the owner's path.

1. **P1.1 Contract, lifecycle, and migration baseline**
   - Freeze entities, ports, API shapes, lifecycle guards, freshness, capabilities, idempotency, and safe errors.
   - Add ordered migrations while preserving current data/API behavior.
   - Maintain repository/unit-of-work boundaries and optimistic concurrency in the shared core.
2. **P1.2 Independent verification harness**
   - Build acceptance fixtures, populated upgrade databases, disposable repositories, provider fakes, secret-leak scans, and full-system smoke commands.
   - Verify both behavior and explicit absence of removed capabilities.
3. **P1.3 `[KB]` review stream**
   - Review Git, launcher, environment, dependency, and assurance changes for contract compliance, edge cases, safety, and evidence accuracy.
   - Add black-box/adversarial acceptance tests without editing `[KB]` modules.
   - Return findings with severity, reproduction, expected behavior, and required regression test.
4. **P1.4 `[AC]` review stream**
   - Review identity, policy, broker, provider, outcomes, recovery, Passport, and CLI code.
   - Test authorization, expiry/revocation, idempotency, secret handling, conflict safety, partial failure, and unsupported-state accuracy.
5. **P1.5 Integration**
   - Wire accepted ports into `main.py`, apply migrations, update root dependencies/configuration, freeze OpenAPI, and resolve only composition-level conflicts.
   - Never weaken a contract or test merely to make integration pass.
6. **P1.6 Release verification**
   - Run clean-clone, upgrade, restart, end-to-end backend, security-boundary, and failure-injection suites.
   - Record an evidence-backed accept/reject decision for every work item and the release candidate.

## 10. Person 2 - `[KB]` evidence, execution, and assurance

Exclusive paths: `backend/app/git/`, `execution/` (including `execution/signature.py`), `environment/`, `dependencies/`, `assurance/`, and matching unit-test directories.

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
   - Produce deterministic findings consumed by lifecycle, API, CLI, and the later UI.

## 11. Person 3 - `[AC]` authority, outcomes, recovery, and CLI

Exclusive paths: `backend/app/identity/`, `policy/`, `credentials/`, `providers/`, `outcomes/`, `recovery/`, `passport/`, `cli/`, `tui/` (including `tui/timeline_screen.py`, `tui/tool_trust_screen.py`), and matching owner unit/contract tests.

1. **P3.1 Local API identity and actor model**
   - Implement loopback/session authentication plus human, agent, and service identities.
   - Implement scoped, expiring, revocable delegations bound to repository and Change.
2. **P3.2 Policy and risk**
   - Enforce path, operation, provider, lifecycle, and risk policy with stable denial reasons.
   - Require explicit authority context for every privileged mutation.
3. **P3.3 Credential broker**
   - Store durable provider credentials only in Windows Credential Manager.
   - Issue short-lived internal grants bound to actor, Change, scopes, and expiry.
   - Proxy allowed calls and prevent secrets entering logs, SQLite, responses, or subprocess environments.
4. **P3.4 GitHub and outcomes**
   - Implement GitHub operations behind broker/policy ports.
   - Record PR and required CI state tied to exact commit SHA.
   - Expose artifact/deployment only when real adapters exist; otherwise mark unsupported.
5. **P3.5 Recovery engine**
   - Preview and execute approved revert commits on dedicated Change branches.
   - Detect conflicts in a temporary worktree before target mutation.
   - Implement authorized provider compensation for Change-created objects.
   - Mark uncommitted files, environment changes, and unknown effects unsupported.
6. **P3.6 Change Passport**
   - Aggregate intent, actors, authority, evidence references, assurance, outcomes, limitations, and recovery status under the frozen Passport contract.
7. **P3.7 CLI and interactive terminal UI**
   - Implement scriptable `create`, `status`, `checkpoint`, `assure`, `outcome`, `recovery`, and `passport` commands through the API without bypassing policy.
   - Build an interactive terminal dashboard with Change list/detail, lifecycle stepper, evidence summary cards, coloured status badges, Git/dependency tables, assurance progress/results, PR/CI panels, and Passport export.
   - Provide guided Change Contract and delegation forms plus explicit recovery preview/confirmation screens.
   - Use a restrained semantic palette: success, warning, failure, informational, muted, and selected/focus states. Always pair colour with text and symbols.
   - Support keyboard-only navigation, small terminals, resize behavior, scrollable long output, plain/non-TTY mode, `NO_COLOR`, and JSON output.
   - Keep business rules in the API; the terminal UI renders server state and never invents readiness or authorization.

## 12. Mandatory contributor onboarding and proposal comprehension

`[KB]` and `[AC]` must understand the proposal directly before coding. Reading only this plan or another agent's summary is insufficient.

### 12.1 Required source order

Each contributor reads, in order:

1. `Change_Assurance_Runtime_Project_Proposal (2).pdf` in full.
2. `OVERALL_CONTEXT.md`.
3. `PROJECT_CONTEXT.md`.
4. This implementation plan.
5. `AGENT_COORDINATION.md`.
6. Existing contracts, migrations, implementation, and tests in the contributor's owned paths and consumed boundaries.

Use this page guide while reading the PDF, but do not substitute it for a full read:

| Proposal pages | Required understanding |
| --- | --- |
| 2-4 | Product thesis, five pillars, root Change object, observation over narration, least authority, typed reversibility |
| 6 | Original component responsibilities and boundaries |
| 9-11 | Lifecycle, end-to-end user flow, assurance summary, and recovery semantics |
| 14 | Why the original proposal ties replay to journal/process/resource evidence; see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` §A.7 for how trace replay is retained without process/filesystem evidence |
| 18 | Local authenticated API intent and original route families |
| 21-24 | Recommended implementation language, phased build, detailed milestones, MVP, and demo expectations |
| 26-28 | Threat model, feasibility risks, non-goals, and competitive boundary |
| 29-30 | Engineering backlog and acceptance criteria to reinterpret after the two approved cuts |
| 33-34 | External technical foundations and growth direction |

### 12.2 Scope interpretation rule

The PDF is the product-design authority. This plan is the implementation authority for the approved variation. Contributors must preserve the proposal's intent wherever possible, but must not implement or imply the process supervisor, filesystem tracker, or any event-journal/replay/tool-registry capability beyond the bounded form `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` defines. When a PDF requirement depends on a cut primitive, the implementation must expose an honest unsupported/limited state described in sections 2, 3.1, and 14.

### 12.3 Required comprehension statement

Before the first claim, each contributor sends `[SD]` a concise comprehension statement containing:

- The proposal capabilities owned by their stream.
- The proposal principles their design must preserve.
- The two cuts (process supervisor, filesystem tracker) and the limitations those cuts impose on their stream, plus the bounded event-journal/replay/tool-registry non-goals relevant to their stream.
- The ports/models they consume and provide.
- The top five failure/security risks in their stream.
- Any apparent conflict between the PDF, context documents, current code, and this plan.

Do not start implementation until `[SD]` acknowledges the statement and resolves any conflict. This is a comprehension gate, not permission to alter another owner's files.

## 13. Detailed parallel next steps before integration

`[KB]` and `[AC]` execute the following tracks concurrently. They work only against frozen contracts and owner-local fakes. They must not import each other's concrete classes, edit `main.py`, modify migrations, or perform final application wiring. `[SD]` answers contract questions and maintains the shared baseline but does not integrate partial work.

### 13.1 Common start for both contributors

1. Pull the clean integration baseline and run `python -m pytest` before editing.
2. Confirm the worktree is clean and post the claim from `AGENT_COORDINATION.md`.
3. Complete the proposal comprehension statement.
4. Inventory existing implementation in the owned paths. Reuse correct current behavior; do not rewrite working modules without a documented reason.
5. List every frozen port/model/error consumed and every new concrete class provided.
6. Build an owner-local test matrix before implementation: happy path, boundary, malformed input, timeout, partial failure, restart/persistence where relevant, and unsupported state.
7. Work in small work-item commits using the permanent tag. Every commit must keep that owner's tests green.
8. If a frozen contract blocks correct implementation, stop that item and submit a contract-change request. Continue unrelated owned work rather than inventing a private contract.

### 13.2 `[KB]` execution track

#### KB-0 - Evidence architecture and compatibility audit

- Map proposal environment/assurance/Git responsibilities to `GitStatePort`, `AgentLauncherPort`, `EnvironmentPort`, `DependencyPort`, and `AssurancePort`.
- Audit the existing Git inspector and verification runner for reusable behavior and migration needs.
- Define owner-local repository/service boundaries and test fakes without changing shared contracts.
- Produce fixtures for repositories with spaces, staged/unstaged/untracked/renamed/conflicted files, detached HEAD, multiple ecosystems, missing tools, and malformed manifests.

Exit: design note in the handoff draft, fixture inventory, proposed concrete classes, and green baseline tests.

#### KB-1 - Git checkpoints and comparison

- Persistable output must include canonical repository identity, branch/detached state, HEAD, worktree/index state, changed paths, bounded diff evidence, digest, capture time, and limitations.
- Implement checkpoint comparison, branch movement detection, evidence freshness inputs, merge-conflict representation, and safe handling of repositories without commits.
- Keep ordinary inspection read-only and preserve existing byte-accurate output bounds/error envelopes.

Testing extent:

- Unit-test every porcelain record type and classification branch.
- Use real disposable Git repositories for staged, unstaged, untracked, rename/copy, delete, binary, conflict, detached, no-commit, Unicode, and spaced-path cases.
- Test truncation by UTF-8 byte count, Git startup/failure errors, deterministic digesting, and repeated identical captures.
- Prove inspection does not mutate HEAD, index, worktree, configuration, or remotes.

Exit: `GitStatePort` contract suite passes and an owner-local comparison flow works across at least three successive checkpoints.

#### KB-2 - Top-level Agent Launcher

- Implement generic, Codex, and Claude adapters over one port with explicit executable discovery and adapter metadata.
- Enforce canonical working directory, executable/argument policy, environment allowlist, timeout, shared output budget, cancellation of the direct child when supported, and safe startup-error results.
- Implement attach mode as declared metadata only. Mark descendant control/attribution unavailable in every relevant result.

Testing extent:

- Cover allowed/disallowed/missing executables, argument limits, cwd propagation, environment stripping, pass/fail/timeout/startup error, cancellation, output interleaving/truncation, and paths with spaces.
- Verify broker credentials and known test secrets never enter the child environment or captured output.
- Use short real helper processes for boundary tests; do not rely only on mocks.
- Prove no result claims process-tree ownership or cleanup.

Exit: all three adapters satisfy the same contract tests, with unsupported descendant behavior explicit.

#### KB-3 - Environment Passport

- Implement deterministic collectors for Windows/OS identity, supported runtimes, compiler/toolchain, package managers, selected configuration keys, and repository configuration.
- Store normalized values or redacted fingerprints according to sensitivity; never raw secrets.
- Compare passports and classify added, removed, changed, expected, unexpected, unknown, and unsupported facts without causal attribution.

Testing extent:

- Unit-test normalization, stable ordering, fingerprinting, redaction, missing commands, localized/invalid output, and collector partial failure.
- Use controlled fake collectors plus a Windows smoke test for available real collectors.
- Seed canary secret values and assert they are absent from models, SQLite-ready serialization, exceptions, and logs.
- Prove identical inputs produce identical passports/diffs.

Exit: baseline/current comparison returns deterministic drift and an explicit completeness/limitations summary.

#### KB-4 - Dependency Tracker

- Support the frozen Python and Node manifest/lockfile set; report unsupported formats rather than guessing.
- Normalize package identity and versions, compare baseline/current state, distinguish direct declarations from lockfile-resolved evidence, and flag manifest/lock mismatch.
- Surface risk inputs without claiming vulnerability certainty or process attribution unless a real evidence source supports it.

Testing extent:

- Fixture-test every supported manifest and lockfile, including empty, malformed, duplicate, missing-lock, reordered, workspace, local/path, URL, and version-range cases.
- Test add/remove/upgrade/downgrade and deterministic ordering.
- Fuzz or property-test parsers with bounded malformed input where practical; parsers must fail safely and never execute repository content.

Exit: dependency comparisons are deterministic, bounded, and reference their source files/evidence quality.

#### KB-5 - Assurance engine and deviation analysis

- Discover configured checks without executing arbitrary discovered text blindly.
- Select required checks using Change Contract, changed-path/dependency/environment evidence, and repository configuration.
- Execute through the bounded runner, retain structured results, calculate evidence coverage, and invalidate results when the Git checkpoint or relevant contract changes.
- Compare actual paths/dependencies/environment drift against allowed/forbidden/expected contract terms.

Testing extent:

- Cover discovery for pytest, Jest/Vitest, lint, type-check, build, and supported security/dependency checks.
- Test selection precedence, duplicate elimination, missing required tools/checks, pass/fail/timeout/error, stale invalidation, partial execution, and missing coverage.
- Test every contract-deviation category and prove findings are deterministic.
- Use real minimal Python and Node fixtures for at least one passing and failing flow per supported runner family.

Exit: owner-local fake Change input produces a complete assurance plan, results, coverage gaps, deviation findings, and freshness decision.

#### KB-6 - Stream hardening and handoff

- Run all `[KB]` unit/contract/real-fixture tests together from a clean process.
- Run the repository-wide baseline suite and distinguish pre-existing failures from introduced failures.
- Review the diff for accidental mutation, secret/path leakage, nondeterminism, unbounded data, and claims that exceed evidence.
- Prepare the complete handoff package in section 20; do not wire the application.

Stream-complete exit: every `[KB]` port has a production implementation, owner-local fake, contract tests, real-boundary tests, stable errors, documented limitations, and no unresolved blocker.

### 13.3 `[AC]` execution track

#### AC-0 - Authority/outcome architecture and compatibility audit

- Map proposal identity/broker/outcome/recovery/Passport responsibilities to the frozen ports and current Change lifecycle.
- Define threat boundaries: local caller, actor, agent, credential store, provider, repository, terminal, logs, and database.
- Create owner-local in-memory credential store, fake GitHub server/adapter, policy fixtures, and API client fake for CLI/TUI development.

Exit: threat/data-flow note in the handoff draft, fake inventory, concrete class list, and green baseline tests.

#### AC-1 - Local authentication, actors, and delegations

- Implement local application principal/session validation plus human, agent, and service actor records.
- Implement grants bound to grantor, grantee, Change/repository, scopes, issued/expiry times, revocation, and optional use limits.
- Default deny missing, ambiguous, expired, revoked, wrong-Change, wrong-repository, and over-scoped authority.

Testing extent:

- Table-test every grant state and scope combination, boundary timestamps, replayed requests, concurrent revoke/use, and malformed identities.
- Verify safe errors reveal no secret or unnecessary local path.
- Test persistence/reload semantics through owner-local repositories/fakes without editing shared migrations.

Exit: policy inputs can unambiguously answer who may do what, for which Change/repository, until when.

#### AC-2 - Policy, risk, and credential broker

- Implement deterministic path, operation, provider, lifecycle, and risk rules with explainable decisions.
- Wrap Windows Credential Manager behind `CredentialStorePort`; keep a fully conforming in-memory fake.
- Issue short-lived internal grants and proxy only allowlisted GitHub operations. Never place durable provider credentials in the agent environment or ordinary data models.

Testing extent:

- Exercise allow/deny precedence, default deny, risk escalation, expiry/revocation, wrong binding, scope narrowing, idempotency, rate-limit/error mapping, and credential-store failure.
- Seed canary secrets and scan logs, exceptions, serialized models, test databases, CLI/plain/JSON/TUI output, and child environments.
- Run an opt-in Windows Credential Manager smoke test that creates and removes only a uniquely named test credential.

Exit: broker contract tests prove scoped operations and secret non-disclosure across every exposed boundary.

#### AC-3 - GitHub provider and outcomes

- Implement repository/branch discovery, draft PR creation/refresh, required-check/CI refresh, and normalized outcome records through brokered operations only.
- Bind outcomes to repository, branch, PR identity, head SHA, observation time, and evidence quality.
- Handle pagination, retryable/non-retryable failure, rate limits, stale SHA, partial responses, and idempotent retries.

Testing extent:

- Use a local fake HTTP provider or transport; automated tests must not require internet or a real credential.
- Contract-test request paths, headers/redaction, pagination, schema variation, 401/403/404/409/422/429/5xx, timeouts, retries, and duplicate idempotency keys.
- Prove CI for SHA A cannot verify SHA B and stale observations cannot advance lifecycle state.

Exit: fake-provider flow creates/refreshes a draft PR and normalizes CI evidence without exposing credentials.

#### AC-4 - Constrained recovery

- Plan only known Change-created commits/provider objects. List unsupported local/environment/unknown effects explicitly.
- Require fresh evidence, eligible dedicated branch, authority, preview, approval token, and idempotency key.
- Trial Git recovery in a temporary worktree; on success create a new revert commit, never reset/rewrite history. Verify final SHA/checkpoint inputs.
- Implement provider compensation only for objects provably created by the Change and permitted by policy.

Testing extent:

- Use disposable repositories for clean revert, multi-commit revert, conflict, already-reverted, branch moved, dirty target, missing object, repeated request, cancellation, and post-check failure.
- Assert preview has no target mutation and any preflight conflict leaves the target repository unchanged.
- Test provider compensation partial failure and resulting `PARTIAL`/`RECOVERY_FAILED` states.
- Prove unsupported effects remain visible and automatic approval is impossible.

Exit: owner-local recovery flow is dry-run-first, approval-bound, conflict-safe, idempotent, and evidence-producing.

#### AC-5 - Change Passport

- Build the versioned Passport only from frozen models/evidence references: intent, actors, delegation, checkpoints, environment/dependencies, assurance, outcomes, limitations, and recovery.
- Represent missing, stale, unsupported, denied, failed, and partial evidence explicitly.
- Provide deterministic JSON export and human terminal rendering without embedding secrets or unbounded raw output.

Testing extent:

- Golden-test canonical serialization and schema versioning.
- Cover complete, incomplete, stale, failed, partially recovered, unsupported, and legacy-migrated Changes.
- Verify stable ordering/digests and canary-secret absence.

Exit: the same inputs produce byte-stable canonical JSON and semantically equivalent terminal output.

#### AC-6 - Scriptable CLI

- Implement commands through the local API client only; do not import persistence/services to bypass authentication, policy, or lifecycle guards.
- Define stable exit codes and stdout/stderr rules. JSON mode writes one documented machine-readable object and no decoration.
- Cover create/list/show/status/checkpoint/assure/outcome/recovery/passport and connection/capability diagnostics.

Testing extent:

- Use an API transport fake for exhaustive command/exit-code/error tests and a real local API for critical smoke flows.
- Test piping, redirected non-TTY output, Unicode, narrow width, `NO_COLOR`, `--no-color`, JSON schema, interrupted requests, and unreachable daemon.

Exit: every command has help, examples, stable exit behavior, plain output, JSON output, and no policy bypass.

#### AC-7 - Interactive terminal UI

- Implement Change list/detail, lifecycle stepper, evidence cards, Git/dependency tables, assurance progress/results, PR/CI panels, contract/delegation forms, recovery preview/confirmation, and Passport export.
- Centralize semantic theme tokens and status-to-colour/symbol/text mapping. Do not use colour as the only signal.
- Render backend loading, empty, stale, unsupported, denied, failed, partial, and success states without fabricated data.
- Keep long-running actions cancellable at the UI request level and show their actual final backend state.

Testing extent:

- Component/snapshot-test every state at representative 80x24, 120x30, and resized/narrow layouts.
- Interaction-test keyboard-only navigation, focus order, forms, validation, confirmation/cancel, scrolling, refresh, disconnect/reconnect, and long output.
- Test colour, no-colour, monochrome, and low-capability terminal behavior.
- Manually smoke-test in Windows Terminal and the VS Code integrated terminal; record terminal sizes and results.

Exit: a user can complete the retained flow from Change creation through Passport/recovery without using raw API calls, and every visual status is backed by API state.

#### AC-8 - Stream hardening and handoff

- Run all `[AC]` unit/contract/provider/Git/CLI/TUI tests from a clean process.
- Run the repository-wide baseline suite and inspect for secret leakage, authority bypass, unsafe repository mutation, unstable output, and hidden partial failures.
- Prepare the complete handoff package in section 20; do not wire `main.py` or edit shared migrations.

Stream-complete exit: every `[AC]` port and terminal surface has a production implementation, conforming fake, required tests, documented limitations, and no unresolved blocker.

### 13.4 Allowed communication while parallel work is active

- Ask `[SD]` contract and scope questions; do not negotiate private interfaces between `[KB]` and `[AC]`.
- Exchange only frozen models/port versions, never concrete imports or shared-file edits.
- If one stream needs evidence not present in a contract, submit a contract-change request to `[SD]` and continue unrelated work.
- Do not begin end-to-end composition, migrations, or application wiring. Those belong to `[SD]` after both complete handoffs.
- Each owner may use fakes for the other stream, but must label them as test-only and demonstrate contract conformance.

## 14. Parallel execution and intersection gates

### Gate 0 - Scope and contracts

Owner `[SD]`; reviewers `[KB]` and `[AC]`. Freeze cuts, capability matrix, ports, IDs, errors, review rubric, and OpenAPI names. No consumer implementation begins until all three acknowledge the handoff.

Exit: contract tests compile, forbidden entities/endpoints are absent, and current tests pass.

### Gate 1 - Independent foundations

- `[SD]`: contracts, migrations, lifecycle core, and independent verification harness.
- `[KB]`: Git checkpoints, launcher, environment/dependencies, assurance discovery.
- `[AC]`: identity, delegation, policy, credential store/broker, provider fakes.

No shared source edits. Feedback is a contract-change request to `[SD]`.

Exit: each stream has green owner tests and an internal progress record. This is not an integration handoff; both owners continue through their complete tracks.

### Gate 2 - Independent code review

Only after KB-6 and AC-8 are complete, `[KB]` and `[AC]` submit separate stream-complete handoffs. `[SD]` reviews diffs, runs owner tests, adds black-box/adversarial acceptance tests, and returns findings to the owner. Owners correct their own modules and resubmit. No rejected or partial stream is integrated.

Exit: both streams have an `[SD]` acceptance record with no unresolved blocking or high-severity findings.

#### `[SD]` post-handoff verification sequence

For each stream separately, `[SD]` performs:

1. **Intake integrity**: clean tree, expected commits, owned paths only, no generated/secret/local-machine artifacts, complete handoff evidence.
2. **Proposal and scope trace**: map behavior back to the proposal and approved cuts; identify missing retained behavior or safety-theater claims.
3. **Static review**: contracts, trust boundaries, subprocess/HTTP/Git/SQLite usage, error handling, bounds, determinism, redaction, and maintainability.
4. **Reproduction**: run the exact submitted commands and compare counts/coverage to the handoff.
5. **Independent probes**: add acceptance/adversarial cases the owner did not author, especially boundary crossings and plausible misuse.
6. **Finding decision**: record severity, file/symbol, reproduction, impact, expected correction, and regression-test requirement.
7. **Disposition**: `ACCEPT`, `ACCEPT WITH NON-BLOCKING FINDINGS`, or `REJECT`. High/blocking findings require owner correction and a full affected-suite resubmission.

Acceptance means the stream is eligible for integration; it does not mean the composed product works yet.

### Gate 3 - Backend composition

In a declared lock, `[SD]` performs integration in this order:

1. Re-run the unchanged baseline suite.
2. Apply shared migrations to empty, current, and populated legacy databases.
3. Wire accepted `[KB]` ports, then run their contract and `[SD]` acceptance tests.
4. Wire accepted `[AC]` ports, then run their contract and `[SD]` acceptance tests.
5. Compose freshness, risk, policy, Passport, recovery, and lifecycle transition rules.
6. Freeze OpenAPI and exercise the real CLI/TUI against the composed local API.
7. Run failure injection for unavailable dependencies, interrupted operations, stale evidence, partial provider results, and recovery conflicts.

`[KB]` and `[AC]` stop edits to integration targets and fix only defects returned to their paths.

Exit: create -> authorize -> activate -> checkpoint -> environment/dependencies -> assurance -> review-ready passes through the real API.

### Gate 4 - Authority and provider verification

Using the already completed `[AC]` implementation and `[KB]` evidence/risk inputs, `[SD]` independently probes cross-Change access, over-scoping, expiry, revocation, idempotency, redaction, stale SHAs, and provider partial failures. `[KB]` never handles secrets.

Exit: scoped operations succeed; invalid grants fail; credentials never reach agent environment, logs, SQLite, or responses.

### Gate 5 - Recovery integration

- `[AC]`: recovery plan/execution and temporary-worktree safety.
- `[KB]`: pre/post Git checkpoints and assurance verification.
- `[SD]`: adversarial review, integration wiring, and acceptance tests.

Exit: committed Change-branch recovery creates a verified revert; conflicts cause no target mutation; unsupported effects are visible.

### Gate 6 - Release candidate

`[SD]` freezes integration and runs the full backend release matrix. Owners fix only their modules and resubmit for verification. Context and acceptance evidence are updated after results are known.

Exit: all section 19 criteria pass from a clean clone and an upgraded existing database.

## 15. Shared ports

Person 1 owns signatures; concrete owners are:

- `GitStatePort`, `AgentLauncherPort`, `EnvironmentPort`, `DependencyPort`, `AssurancePort` -> `[KB]`.
- `CredentialStorePort`, `CredentialBrokerPort`, `PolicyPort`, `RecoveryPort`, `PassportPort`, `ProviderPort`, `OutcomePort` -> `[AC]`.

Ports exchange immutable Pydantic models, not dictionaries. Side effects require authority context and an idempotency key. Changes require owner review and a versioned handoff.

## 16. Recovery semantics

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

## 17. Security and privacy

- Loopback-only by default; non-loopback requires an explicit secure deployment mode.
- Authenticate non-health routes and authorize mutations.
- Store credentials only through the credential-store port; redact secrets before logging.
- Give subprocesses an allowlisted environment without broker credentials.
- Canonicalize repository paths and prevent constrained-path escape.
- Use argument arrays and `shell=False`; enforce executable/timeout policy.
- Bound patch, output, and database payload sizes.
- Never label a Change safe merely because checks passed.

## 18. Verification depth and evidence requirements

### 18.1 Required test layers for each owner

1. **Unit tests**: every pure rule, parser branch, normalization, redaction rule, state classification, and error mapping. These run without network, user credentials, or shared machine state.
2. **Port contract tests**: every method's success result, documented domain errors, validation boundary, idempotency behavior, and serialization round trip. The same suite must run against owner-local fakes and production implementations where feasible.
3. **Real-boundary tests**: disposable Git repositories, short subprocesses, temporary databases, local fake HTTP providers, and terminal pilots/snapshots. Mocks alone are insufficient for subprocess, Git, persistence, HTTP serialization, recovery, or TUI behavior.
4. **Failure/adversarial tests**: malformed/truncated input, timeout, cancellation, concurrency, stale evidence, partial response, restart, missing dependency, permission failure, oversized output, Unicode/path aliases, and repeated requests.
5. **Security/privacy tests**: default deny, authority boundary, path containment, command policy, secret canaries, log/exception/model/database/output scanning, and proof that credentials do not enter child environments.
6. **Owner-local flow tests**: complete the stream using conforming fakes for the other owner. These prove internal composition, not final product integration.
7. **Manual checks**: only where OS credential UI or terminal rendering cannot be adequately proven automatically. Manual evidence supplements automated tests and never replaces a testable assertion.

### 18.2 Coverage expectations

- All new or materially changed behavior must have a regression test. No untested branch may authorize a mutation, advance lifecycle, handle a secret, classify recovery safety, or report assurance success.
- Security-, policy-, lifecycle-, idempotency-, and recovery-decision branches require complete decision-table coverage.
- New owner packages target at least 90% statement and 85% branch coverage, measured on their own paths. A numeric target does not excuse missing behavioral cases.
- Exclusions are limited to defensive unreachable branches or platform guards and must be listed with a reason in the handoff.
- Tests must be deterministic: freeze/inject clocks, randomness, IDs, and provider responses. No ordinary automated test may require internet access, a real GitHub credential, or an existing user repository.

### 18.3 Mandatory cross-cutting suite

- Migration tests against empty, current, and populated legacy schemas.
- State, concurrency, idempotency, freshness, policy, and delegation tests.
- Git fixtures for staged/unstaged/untracked/rename/conflict/detached/branch movement and paths with spaces.
- Launcher validation/timeout/output/startup-error tests plus explicit descendant-control limitation.
- Environment redaction/drift and dependency parser fixtures.
- Assurance discovery/selection/staleness/gap/timeout tests.
- Broker tests for revocation, expiry, binding, scope denial, and secret non-disclosure.
- GitHub adapter tests against a local fake, including pagination, rate limits, stale SHA, and partial failure.
- Disposable-repository recovery tests for isolation, approval, conflict safety, idempotency, and verification.
- API tests for all envelopes and forbidden endpoint absence.
- CLI/API end-to-end, restart-persistence, clean-clone, and upgrade smoke tests.
- Rich rendering tests for colour/no-colour/plain/JSON output and terminal widths.
- Textual component/snapshot and interaction tests for keyboard navigation, forms, loading, empty, stale, denied, failed, partial, and unsupported states.
- Browser UI and browser accessibility testing are deferred; terminal accessibility remains required.

### 18.4 Evidence submitted with each work item

Every work-item commit or handoff states:

- Exact automated commands and pass/fail counts.
- Coverage command and owner-path statement/branch results.
- Real boundaries exercised versus fakes used.
- Manual checks with environment/terminal details and observed result.
- Known skipped/xfail cases and why they are not masking a defect.
- Residual limitations, unsupported cases, and any test gap requiring `[SD]` attention.

“Tests pass” without commands, counts, and boundary details is not sufficient evidence.

## 19. Definition of done

1. A user creates a Change Contract, selects an actor/agent, and sees authority before activation.
2. The app launches or attaches to a top-level run, with real descendant-process supervision (Job Object-based attribution, orphan cleanup, restricted-token authority reduction) per `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A; `attach` still claims no supervision, since nothing was launched.
3. Git, environment, and dependency checkpoints are real, persisted, comparable, and visibly fresh/stale.
4. Assurance is evidence-selected, bounded, and gates lifecycle transitions.
5. GitHub credentials remain brokered and never enter agent environment or application data.
6. PR and CI results are tied to the correct commit SHA.
7. The Passport exports real intent, actors, authority, checkpoints, deviations, assurance, outcomes, limitations, and recovery status.
8. Supported recovery requires preview/approval, is conflict-safe, and is verified.
9. API, CLI, and interactive terminal UI show real missing, stale, unsupported, denied, failed, and partial states.
10. The filesystem tracker is absent from code, storage, API, and claims (no filesystem-snapshot routes/tables). The process supervisor is present in its Part A bounded form (real descendant attribution, orphan cleanup, restricted-token authority reduction — never a formal sandbox claim). The event journal, tool registry, and trace replay are present, but strictly in the bounded form `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` defines: no filesystem-write timeline, no re-execution, no interception of a running agent's own tool/MCP calls. `test_no_removed_subsystem_endpoints_are_exposed` asserts `/snapshots`-style filesystem routes are absent; `test_expected_route_families_are_present` asserts `/events`, `/tools`, `/replay`, and the process-supervisor routes are present.
11. Existing data upgrades successfully and the complete backend release matrix passes.
12. The terminal UI passes keyboard, resize, no-colour, plain-output, and critical-flow interaction tests.
13. Browser web UI implementation remains deferred and does not block backend acceptance.

## 20. Handoff format

```text
[TAG] HANDOFF to [TAG]
Work items: KB-0..KB-6 | AC-0..AC-8
Status: ready | blocked
Proposal mapping: <pages/sections implemented and approved-cut consequences>
Changed paths: <exact list>
Commits: <ordered hashes and subjects>
Contract/version: <port, endpoint, schema, OpenAPI hash>
Provided implementations: <concrete classes/entry points>
Behavior and limitations: <supported, unsupported, assumptions>
Security/privacy review: <authority, secret, path, subprocess/provider/recovery boundaries>
Verification: <commands, counts, coverage, real boundaries, manual checks>
Known findings: <none or severity/list>
Integration instructions: <constructors, configuration, migration/data needs, ordering>
Consumer action: `[SD]` independent review; no direct integration by owner
```

Attach or reference the test matrix and owner-local flow result. The working tree must be clean, and the submitted commits must contain only the owner's paths. No handoff may claim a capability that depends on the process supervisor or filesystem tracker, or that exceeds the bounded event-journal/replay/tool-registry form defined in `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md`.
