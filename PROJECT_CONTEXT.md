# Change Assurance - Project Context

## Relationship to overall context

This document defines the active implementation of `Change_Assurance_Runtime_Project_Proposal (2).pdf`. Read `OVERALL_CONTEXT.md` first for stable product principles, vocabulary, the CML working standard, and decision authority. The PDF proposal is the feature baseline; this document records the two approved cuts and their necessary consequences. `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` records the reversal that retains the event/effect journal and tool registry in bounded form.

## Goal

Build the retained Change Assurance Runtime described by the proposal, without a two-day deadline. The product is a local-first control plane that connects Change intent, identity and authority, agent execution summaries, Git/environment/dependency evidence, assurance, GitHub outcomes, constrained recovery, and a final Change Passport.

## Product promise

A developer can define a bounded Change, delegate scoped authority to an agent, launch or attach to its top-level invocation, collect real Git/environment/dependency evidence, run evidence-selected assurance, follow the resulting pull request and CI, and export a Change Passport. Supported Git/provider recovery is previewed, explicitly approved, and verified. Missing or unsupported evidence remains visible.

## Reference end-to-end flow

1. Connect a local repository and create a Change Contract.
2. Select an actor/agent and review its scoped, expiring authority.
3. Capture baseline Git and environment passports, then launch or attach to the agent.
4. Capture the resulting Git checkpoint, environment drift, and dependency changes.
5. Review contract deviations and the assurance plan; run required checks.
6. Authorize the broker to create or refresh a GitHub pull request and follow required CI for the exact commit.
7. Export a Change Passport containing evidence, decisions, outcomes, residual gaps, and recovery status.
8. When requested, preview and approve a supported Git/provider recovery and verify the result.

## Required scope

- Persistent Change lifecycle, Change Contract, guarded transitions, and evidence freshness.
- Human/agent/service identities, delegations, risk/policy decisions, and local API authentication.
- GitHub credential broker using OS credential storage and short-lived internal capability grants.
- Top-level Agent Launcher/attach adapters with aggregate, bounded execution results.
- Git checkpoints, comparisons, status/diff evidence, and branch/commit continuity.
- Redacted environment passports and drift comparison.
- Python/Node dependency manifest and lockfile analysis.
- Assurance discovery, selection, bounded execution, contract deviation, and evidence coverage.
- GitHub PR/CI outcomes tied to exact commit SHAs.
- Constrained Git commit/provider recovery with preview, approval, conflict checks, and verification.
- Versioned Change Passport, scriptable CLI, interactive terminal UI, capabilities reporting, and explicit unsupported states.
- A frozen OpenAPI contract suitable for a later browser UI phase; web frontend implementation is deferred.
- A per-Change hash-chained event/effect journal and trace-only replay (reconstruction/verification, no re-execution) — see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` §A.7 for the exact boundary.
- A tool registry covering the top-level launched executable and explicitly declared manifests, with Windows-Authenticode-based signature checks and drift-based trust invalidation — see the same plan's §B.10 for the exact boundary.

## Approved cuts

The following proposal subsystems are intentionally removed from the product:

- Process supervisor, descendant-process attribution, and process cleanup — narrowed, not
  absolute: suspending/resuming the single top-level launched process is retained (Windows-first,
  honestly unsupported elsewhere), per `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A.
- Filesystem observation, before-images, snapshots, file-effect attribution, and local-file recovery/undo.

The event/effect journal, causal timeline, and trace-only replay are retained in bounded form, as is a tool registry scoped to the top-level launched executable and explicitly declared manifests. See `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` for the full design and its own non-goals. Checkpoint-based Change forking and incremental, poll-based (TUI-only) agent output are also retained; see `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Parts B and C.

## Necessary consequences and non-goals

- No descendant-process ownership, orphan cleanup, process-tree policy, or Windows Job Object enforcement because the process supervisor remains cut beyond top-level pause/resume.
- No uncommitted-file restoration, resource versions, write attribution, or environment rollback because filesystem/process observation is absent.
- No attribution of an environment/dependency change to a particular process; only checkpoint comparison is claimed.
- No descendant-process attribution in any replay row, no filesystem-level write timeline, and no re-execution of any kind during replay — replay is a per-Change hash chain reconstruction/verification only.
- No interception or blocking of a running agent's actual tool/MCP calls, and no sandboxing/enforcement of declared filesystem/network scope — the tool registry governs only the top-level launched executable and explicitly declared manifests.
- No automatic recovery. Retained recovery is limited to known Git commits and supported provider objects and always requires approval.
- Initial host collectors target Windows; other platforms require tested adapters before support is claimed.

## Product language

Preferred terms:

- "Change Assurance Runtime"
- "Change Contract"
- "Git checkpoint"
- "environment passport"
- "assurance result"
- "scoped authority"
- "Change Passport"
- "supported Git/provider recovery"

Do not claim:

- Complete observation, causal attribution, or sandboxing.
- Descendant-process control.
- Local-file/environment rollback.
- Process-tree visibility.
- Interception or enforcement of a running agent's own tool/MCP calls, or credential trust enforcement.
- General recovery beyond the explicitly supported Git/provider actions.
- Replay beyond a per-Change hash-chain trace reconstruction/verification with no re-execution.
- Tool trust beyond the top-level launched executable and explicitly declared manifests.
- Pause/resume beyond the single top-level process (no descendant suspension), or on any non-Windows platform.
- Change forking as a Git branch/merge operation — it is an evidence-trail fork only, no repository mutation.
- Real-time agent output as a push/streaming transport, or in the browser frontend — TUI polling only.

## Active architecture

```text
Interactive terminal UI / CLI / API clients (browser UI deferred)
  -> Authenticated local API
       -> Change lifecycle, contracts, identity, policy
       -> Credential broker and GitHub outcomes
       -> Top-level Agent Launcher
       -> Git, environment, and dependency trackers
       -> Assurance engine
       -> Constrained recovery engine
       -> Tool Registry (top-level executable + declared manifests only)
       -> Event/Effect Journal (per-Change hash chain) and trace-only Replay
       -> Change Passport builder
       -> SQLite state/evidence store
```

The Agent Launcher may start or attach to a top-level invocation, but it does not observe or control a descendant process tree. Git is the source of code-change evidence; it is not filesystem-effect attribution. The Event/Effect Journal records mutations to entities already modeled by this backend, not a filesystem or process-level causal trace; Replay reconstructs and verifies that journal without re-executing anything. The Tool Registry governs only the top-level executable the Agent Launcher resolves and explicitly declared manifests — it does not intercept a running agent's own tool calls.

## Core data concepts

- **Change / Change Contract**: intent, repository, boundaries, expected outcomes, checks, authority, lifecycle.
- **Actor / Delegation**: authenticated identity and its scoped, expiring authority.
- **Agent run**: top-level invocation plus aggregate bounded result, never a process graph.
- **Git checkpoint**: branch, HEAD, status/diff, changed-path evidence, and capture time.
- **Environment passport / dependency change**: redacted comparable state and manifest/lockfile differences.
- **Assurance plan/result**: selected checks, rationale, result, freshness, and coverage gaps.
- **Outcome**: PR/CI/artifact/deployment evidence when a real provider adapter exists.
- **Recovery plan/action**: approved, supported Git/provider compensation and verified result.
- **Change Passport**: exportable evidence chain and limitations for one Change.

## Definition of done

The backend/terminal phase meets all acceptance criteria in `BACKEND_IMPLEMENTATION_PLAN.md`: the retained proposal flow works end to end through the API, CLI, and interactive terminal UI using real data; migrations preserve existing data; authority and credentials are enforced; evidence freshness gates lifecycle state; every relevant failure or unsupported condition is represented; and recovery stays inside its documented Git/provider boundary.

No code, schema, route, or copy may imply process supervision, filesystem tracking/undo, or any capability beyond the bounded event journal/replay and tool registry described in `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` (no descendant-process attribution, no filesystem-level write timeline, no re-execution, no interception of a running agent's own tool/MCP calls). The terminal UI is required; browser UI implementation and browser acceptance are not part of this phase.

## Current implementation status

### `[SD]` - 2026-09-19 03:48:18 -04:00 - Gate 6 release-matrix record: ACCEPT for backend/CLI scope

Checked all 13 definition-of-done items (§19) against this session's evidence plus a fresh live-`uvicorn` smoke check (health open with no auth, capabilities 401 without a token and 200 with the real one, 44 routes). 11 of 13 items PASS with reproducible evidence (contract/authority, launcher non-supervision, real checkpoints, evidence-gated lifecycle, brokered credentials, SHA-bound outcomes, real Passport, conflict-safe verified recovery, no removed-subsystem code, clean-clone/upgrade/restart/end-to-end/security/failure-injection suites all passing together at **560 passed, 1 skipped**, deferred browser UI). Items 9 and 12 are **partial/not done** — entirely because `[AC]`'s terminal UI is an acknowledged partial slice (no lifecycle stepper, evidence tables, assurance panel, contract/delegation forms, or Textual interaction tests yet); not a backend defect. **Disposition: backend and CLI are release-ready; full product-level definition of done stays open pending the rest of AC-7.** Full item-by-item table in `OVERALL_CONTEXT.md`.

### `[SD]` - 2026-09-19 03:40:16 -04:00 - Fixed a real `[KB]` bug, formal Gate 2 review of `[KB]`, and API authentication

`[KB]`'s self-reported pass counts (509/544/560) were not reproducible here: a real, environment-dependent bug in `backend/app/execution/runner.py` (`minimal_environment()` strips `APPDATA`, breaking per-user-site-installed tools like `pytest` on this machine) made every assurance check silently fail. Fixed by re-injecting `APPDATA`/`USERPROFILE` in `BoundedVerificationRunner.run`, mirroring the identical pattern `[KB]` already uses in `git/adapter.py` for `HOME`/`USERPROFILE`. With only that fix, the full suite reaches exactly **560 passed, 1 skipped**, confirming the fix and ruling out any other hidden regression.

Formal Gate 2 review of the `[KB]` stream: **ACCEPT WITH NON-BLOCKING FINDINGS** (the bug above, now fixed; one low-severity informational finding about an unused parameter in `EvidenceService._dependencies_for`). Full seven-step writeup in `OVERALL_CONTEXT.md`.

Implemented API authentication (plan section 17), previously absent entirely: a single-user local bearer token (`backend/app/core/auth.py`), generated once and persisted next to the database, required on every `/api/v1/*` route except `/health`. `[AC]`'s CLI (`cli/client.py`) picks it up automatically from `CHANGE_ASSURANCE_API_TOKEN` with no changes needed to the 39 command call sites in `cli/main.py`. Every test file that builds the app/a live server directly was updated to send the token. Full detail and verification in `OVERALL_CONTEXT.md`.

### `[KB]` - 2026-09-19 03:55 -04:00 - Plan reconciliation: `[KB]` scope complete; API authentication and the rest of the release path are open

`[KB]`'s scope is complete against the plan, including the section 8 read routes, idempotency keys on every `[KB]` mutation and a visible checkpoint freshness flag. A clean clone of `origin/master` (`d8c2300`) passes **560 passed, 1 skipped**. Open items owned by others: **API authentication (plan section 17) is not implemented anywhere**, `[SD]` Gate 2 review of `[KB]` and recording of the release matrix, and the remaining `[AC]` terminal UI screens and interaction tests. Full detail in `OVERALL_CONTEXT.md`.

### `[KB]` - 2026-09-19 03:40 -04:00 - Full suite: 544 passed, 1 skipped

With the `textual` extra installed the whole repository, TUI tests included, passes: **544 passed, 1 skipped**. Earlier `[KB]` counts (531, 509, 502) excluded `backend/tests/tui` and are superseded by this figure.

### `[KB]` - 2026-09-19 03:15 -04:00 - Remaining Person 2 items closed

CLI groups `evidence`, `agent` and `assurance`; `Idempotency-Key` replay safety on agent launch/attach; in-flight agent runs persisted so they are listed and stoppable from a separate request. Whole repository excluding `backend/tests/tui`: **531 passed, 1 skipped**. Open and not `[KB]`'s: `[AC]` TUI panels 3-4 (need the `textual` extra), `.cmd`-shim-only Codex/Claude installs, non-Windows and real-agent smoke tests. Details in `OVERALL_CONTEXT.md`.

### `[KB]` - 2026-09-19 02:45 -04:00 - Person 2 stream composed into the API (user-authorized)

`create_app` now builds `EvidenceService(EvidenceStore(database))`, exposes it through 13 new `/api/v1` routes (`evidence`, `agents`, `assurance`; see `OVERALL_CONTEXT.md` for the list), gates every command-executing operation through the `[AC]` policy engine, and feeds `assurance_facts` into `RuntimeLifecycleFacts` so `LOCALLY_VERIFIED` and `REVIEW_READY` are reachable only with fresh, passing evidence. The five KB capabilities report `AVAILABLE`. Whole repository excluding `backend/tests/tui`: **509 passed, 1 skipped**. The edited `[SD]`-owned files are listed in `OVERALL_CONTEXT.md` for `[SD]` review. Still open: `[AC]` CLI/TUI clients for these routes.

### `[KB]` - 2026-09-19 02:20 -04:00 - Persistence and orchestration completed; only `[SD]` composition remains

`backend/app/assurance/store.py` (`EvidenceStore`) and `service.py` (`EvidenceService`) now persist and drive the full Person 2 flow against `[SD]`'s existing evidence tables, restart-safe and compatible with `[AC]`'s `PassportBuilder`. `AgentLauncher.adapters()` reports adapter/executable availability. The remaining Person 2 work is `[SD]`-owned composition: build `EvidenceService(EvidenceStore(database))` in `create_app`, add routes, map `assurance_facts` into `RuntimeLifecycleFacts`, and mark the KB capabilities available; `[AC]` TUI items 3 and 4 wait on those routes. Whole repository (excluding `backend/tests/tui`, needing the uninstalled `textual` extra): **502 passed, 1 skipped**; `[KB]` suites **339 passed**, 98% coverage. See `backend/app/git/KB_HANDOFF.md`.

### `[KB]` - 2026-09-19 01:55 -04:00 - Person 2 stream complete (KB-0..KB-6), ready for `[SD]` review

The five ports `[KB]` requested were frozen in `backend/app/contracts/` by `[SD]`, which cleared the earlier blocker, so the whole Person 2 stream is now implemented against them. Full handoff, contract gaps and limitations: `backend/app/git/KB_HANDOFF.md`. This is self-verification, not `[SD]` acceptance, and no application wiring was done.

- **KB-1** `GitStateTracker` (`backend/app/git/state.py`, `reader.py`): deterministic checkpoint digest that includes untracked-file content, three-checkpoint comparison, freshness (`is_current`), unborn repositories rejected, detached HEAD represented. Also fixed a real defect found by the tests: stderr shared the capture budget and could leave the stdout patch empty.
- **KB-2** `AgentLauncher` (`backend/app/execution/launcher.py`, `resolve.py`): generic/Codex/Claude adapters, environment allowlist with secret redaction, cancel/timeout of the direct child only, attach as metadata only, `descendant_control_available` always `False`.
- **KB-3** `EnvironmentTracker` (`backend/app/environment/`): deterministic redacted passport, keyed fingerprints for sensitive values, added/removed/changed/unknown drift with no causal claim, collector failures isolated as `PARTIAL`.
- **KB-4** `DependencyTracker` (`backend/app/dependencies/`): Python (`requirements`, `pyproject`, `poetry.lock`) and Node (`package.json`, `package-lock.json` v1-v3) comparison against the checkpoint HEAD; unsupported, malformed and oversized files reported; parsers fuzz-tested and never execute content.
- **KB-5** `AssuranceEngine` (`backend/app/assurance/`): discovery from configuration (unrecognized scripts become gaps, never commands), selection from the Change Contract and changed-path/dependency evidence, bounded execution, structured summaries, freshness invalidation on repository or contract change, and deviation analysis (forbidden/outside-allowed paths, conflicts, risk ceiling, dependency and environment drift).
- **KB-6** hardening: bounded in-memory run/plan retention, all suites run together from a clean process, diff reviewed for mutation, secret and path leakage, nondeterminism and unbounded data.

**Verification**: `python -m pytest -o addopts=""`: **473 passed, 1 skipped**. `[KB]` suites alone: **328 passed**, statement+branch coverage **98%** over `backend/app/{git,execution,environment,dependencies,assurance}` (targets 90%/85%). `python -m compileall -q backend`: passed. Real boundaries: disposable Git repositories, real subprocesses, a real `pytest` pass/fail, a real Node `node --test` pass/fail through `npm`, and a SQLite round trip of every evidence model. Owner-local end-to-end flows: `backend/tests/kb_flow/test_kb_end_to_end.py`.

**For `[SD]`**: compose the five classes, persist into the existing `git_checkpoints`/`environment_passports`/`dependency_reports`/`assurance_runs` tables, add routes, feed `AssuranceEvaluation` into `RuntimeLifecycleFacts` for the four assurance facts, and mark the KB capabilities `AVAILABLE`. Contract gaps (no actor/idempotency on the launcher port, no checkpoint on `AssurancePort.run`, no expected/unexpected drift category) are listed in the handoff.

**Not claimed**: descendant control or attribution, replay, local-file undo, tool trust, an atomic Git snapshot, proof of correctness from passing checks, or Linux/macOS/real-agent coverage. Commits: `93d1f84`, `732229d`, `6a215a5`, `81021d3`, `6595605` plus this documentation commit.

### `[SD]` - 2026-09-19 01:49:29 -04:00 - Hardening tests plus formal Gate 2 review of the `[AC]` stream

Four items, all test/verification work against `[SD]`'s own composition, not new capability: (1) a real app-restart persistence test (`test_state_persists_across_a_real_app_restart` — tears down one `create_app()` instance and builds a second against the same DB file, the first test to prove state survives outside one process); (2) committed forbidden/expected-route-family tests in `test_contract_boundaries.py` (previously only checked manually); (3) three failure-injection tests driving GitHub 5xx/404/no-remote scenarios through `/changes/{id}/providers/github/pulls` — which **found and fixed a real idempotency defect**: `ProviderOperationService.create_pull_request` called the provider before checking for an already-recorded operation, so replaying a *failed* request's idempotency key silently re-ran it against GitHub a second time (a successful replay happened to be masked by `GitHubProvider`'s own success-only cache). Fixed in `backend/app/core/runtime_service.py`; (4) the formal Gate 2 review disposition for the `[AC]` stream (AC-0..AC-7) that `BACKEND_IMPLEMENTATION_PLAN.md` §14 requires — **ACCEPT WITH NON-BLOCKING FINDINGS**, all findings either informational contract-gap notes `[AC]` already flagged or the one `[SD]`-side defect fixed in this same record.

Full seven-step review writeup (intake, scope trace, static review, reproduction, independent probes, findings, disposition) is in `OVERALL_CONTEXT.md`. `python -m pytest`: **286 passed, 1 skipped**, no regressions — includes `[AC]`'s new `backend/tests/{cli,tui}/` suites, which required installing the `tui` extra (`textual`) in this environment for the first time.

### `[SD]` - 2026-09-19 01:38:38 -04:00 - Real `LifecycleFactsPort` activates authority/outcome/recovery evidence

`ChangeService` was still defaulting to `UnavailableLifecycleFacts` (503 on every transition) even after the Gate 3 composition below wired real identity/outcome/recovery data. New `backend/app/core/lifecycle_facts_service.py` (`RuntimeLifecycleFacts`) is the real `LifecycleFactsPort`: `authority_valid` from live delegations, `pull_request_recorded`/`ci_passed_for_current_head` from persisted provider operations/outcomes (SHA-bound, not stale), and the five `recovery_*` facts from the latest persisted `RecoveryPlan`. Facts that need `[KB]`'s unimplemented environment/dependency/assurance stream stay honestly `False`, so `LOCALLY_VERIFIED`/`REVIEW_READY`/`ARTIFACT_BUILT`/`DEPLOYED`/`OBSERVING`/`STABLE` — and therefore `PR_OPEN`/`CI_VERIFIED` too, since the FSM only reaches them via `REVIEW_READY` — stay correctly unreachable through the real API; this is documented as a known limitation, not routed around.

This activates `DRAFT -> ACTIVE` (now authority-gated for real) and the full `RECOVERY_PENDING -> RECOVERING -> RECOVERED_VERIFIED` (and `RECOVERY_CONFLICT`/`RECOVERY_FAILED`) branch end-to-end through the real API. Full rationale and the one flagged contract gap (`LifecycleFactsPort.get_facts` has no caller-actor parameter, so `authority_valid` is existence-based rather than actor-specific) are recorded in `OVERALL_CONTEXT.md`.

`python -m pytest`: **265 passed, 1 skipped**, no regressions — 6 new unit tests (`backend/tests/core/test_lifecycle_facts_service.py`) plus one new end-to-end acceptance test driving `ACTIVE` and the recovery transition sequence through the real API against a real disposable Git repository.

### `[SD]` - 2026-09-19 01:12:33 -04:00 - Gate 3 composition for `[AC]`'s stream; AC-6/AC-7 unblocked

`[SD]` cleared both blockers recorded in `backend/app/cli/AC_REMAINING_WORK.md` without editing any `[AC]`-owned module. `pyproject.toml` now declares `typer`, `rich`, and a `tui` extra with `textual`, exactly as `[AC]`'s `CONTRACT CHANGE REQUEST` asked. `backend/app/core/router.py` now exposes real routes for actors, delegations, GitHub connect/grants/pull-requests, outcome refresh, recovery preview/execute, and Change Passport build/retrieve, composed in new `backend/app/core/runtime_service.py` / `runtime_repositories.py` against `[AC]`'s existing, unmodified `IdentityService`/`DelegationPolicyEngine`/`CredentialBroker`/`GitHubProviderAdapter`/`GitHubOutcomeTracker`/`GitRecoveryEngine`/`PassportBuilder`. Every privileged mutation is policy-gated (`DelegationPolicyEngine.evaluate`) and grant-binding-checked before it runs. `credential_grants`, `provider_operations`, `outcomes`, `recovery_plans`/`recovery_actions`, and `change_passports` are now written, not just migrated. `create_app` gained injectable `credential_store`/`http_transport` parameters (defaulting to the real `WindowsCredentialStore`/`UrllibHttpTransport`) mirroring the existing adapter-injection pattern.

Full commands and results, the two contract-gap resolutions, the one known inherited limitation (`CredentialBroker`'s in-process-only grant cache loses live tokens across a restart, failing safe), and exactly what remains `[AC]`'s to build (AC-6 CLI, AC-7 TUI, both now unblocked) are recorded in `OVERALL_CONTEXT.md`. `python -m pytest`: **258 passed, 1 skipped**, no regressions; 3 new `[SD]` acceptance tests in `backend/tests/acceptance/test_runtime_routes.py` exercise the full identity → GitHub PR → outcome → recovery → Passport path against a real disposable Git repository and a local HTTP transport fake (no network, no real credential). `[KB]`'s environment/dependency/assurance evidence remains genuinely absent and is reported as Passport `limitations`, not fabricated.

### `[AC]` - 2026-09-19 01:30 -04:00 - AC-6 complete; AC-7 first vertical slice (both blockers resolved by `[SD]`'s `c616f37`)

#### AC-6: complete

`backend/app/cli/` — `ApiClient` (thin JSON client, reuses the existing generic `HttpTransport` seam, no new HTTP dependency) plus a Typer app with `change`/`actor`/`delegation`/`github`/`outcome`/`recovery`/`passport` command groups covering every Gate-3 route. Stable exit codes (0 success, 1 API error, 2 connection error), `--json` single-object output, `NO_COLOR`/`--no-color`/non-TTY handling built in from the start.

Tests: `backend/tests/cli/test_client.py` and `test_main.py` (fake-transport unit tests for every error path), plus `test_smoke.py` — one real end-to-end test against a live `uvicorn` server on an ephemeral port with a real temporary Git repository, not a fake.

#### AC-7: first vertical slice, not the full spec

`backend/app/tui/app.py`'s `ChangeDashboard` — a working Textual app listing Changes through the same `ApiClient`, lifecycle state shown as colour-plus-symbol (never colour alone), honest empty/error/connection-failure states. Detail view, lifecycle stepper, evidence tables, assurance/outcome panels, contract/delegation forms, and the recovery preview/confirmation screen (highest priority — the backend logic for it already exists and is tested) are not yet built. Textual `Pilot` interaction testing is also not possible yet: no async pytest runner is configured in this project. Full itemized remaining work is in `backend/app/cli/AC_REMAINING_WORK.md`.

#### Validation

Full repository suite passed with no regressions after both additions (`python -m pytest`).

### `[AC]` - 2026-09-19 00:50:26 -04:00 - Person 3 AC-0..AC-5 complete; AC-6/AC-7 blocked

#### Completed scope

`[AC]` completed AC-0 through AC-5 of the Person 3 track: identity/delegation, policy, credential broker, GitHub provider/outcomes, constrained Git recovery, and Change Passport. Work was limited to `backend/app/{identity,policy,credentials,providers,outcomes,recovery,passport}/` and matching `backend/tests/` paths; no shared contract, migration, or `[SD]`/`[KB]`-owned file was edited.

#### What each piece does

- `backend/app/identity/`: `Actor`/`Delegation` persistence against `[SD]`'s canonical `actors`/`delegations` migration tables; `IdentityService.authorize()` is default-deny with full decision-table coverage.
- `backend/app/policy/`: `DelegationPolicyEngine` implements the frozen `PolicyPort` — authority, then default-denied operations, `ChangeContract.forbidden_paths`/`authority_ceiling`/`max_risk`.
- `backend/app/credentials/`: `CredentialBroker` implements `CredentialBrokerPort`; `WindowsCredentialStore` is a real, live-tested `ctypes` binding to Windows Credential Manager (no new dependency); `resolve_secret` is the only path a durable secret ever leaves the store.
- `backend/app/providers/` + `backend/app/outcomes/`: `GitHubProvider` behind a swappable `HttpTransport` (real: `urllib`; tests: local fake, no network); `OutcomeTracker` discards any check-run whose `head_sha` doesn't match the requested commit.
- `backend/app/recovery/`: `GitRecoveryEngine` implements `RecoveryPort` — revert-commit only, on a dedicated branch, conflict-checked in a temporary worktree before any target-repository mutation, approval-token mandatory, never resets/rewrites history.
- `backend/app/passport/`: `PassportBuilder` implements `PassportPort` from real persisted evidence only; missing evidence becomes an explicit `limitations` sentence, never a fabricated evidence reference; canonical digest is deterministic over evidence content.

#### Contract gaps found (worked around, flagged for `[SD]`)

- `CredentialBrokerPort.issue_grant` has no `provider` parameter although `CredentialGrant.provider` is required; inferred from the scope prefix (e.g. `"github.pr.create"` → `"github"`).
- `OutcomePort.refresh(change)` takes no actor/grant although GitHub access needs a resolved token; worked around with a constructor-supplied `read_grant_id`.
- `ChangeView` has no GitHub repository slug; resolved read-only via `git remote get-url origin` in `backend/app/providers/repository_slug.py`.

#### Validation results

- AC-owned suite: **90 passed, 1 skipped** (opt-in Windows Credential Manager smoke test — run manually with `RUN_WINDOWS_CREDENTIAL_SMOKE_TEST=1`, verified live against the real OS credential store; `cmdkey /list` confirmed no leftover credential).
- Full repository suite: **255 passed, 1 skipped**, no regressions from any owner's work.
- `python -m compileall -q backend`: passed.
- Every AC-owned port implementation verified via `isinstance(x, FrozenPort)` conformance in its own tests.
- Grep audit: no `print`/`logging` call exists anywhere in AC-owned modules — zero accidental secret-leakage surface.
- Recovery specifically tested against real disposable Git repositories, including a genuine merge-commit conflict (not mocked), with proof the target repository's HEAD/branches are never touched on preview or on conflict.

#### Commits

- `2672bc2`, `9a33210`, `d0ff17d`, `f062414`, `30babfe`, `34557df` — all pushed to `origin/master`.

#### AC-6/AC-7 status: blocked, not unstarted

Two independent blockers, detailed with exact remaining steps in `backend/app/cli/AC_REMAINING_WORK.md`:

1. `typer`, `rich`, and `textual` are not declared in `pyproject.toml`. Root dependency manifests are `[SD]`-owned; a `CONTRACT CHANGE REQUEST` was submitted (see that file) rather than editing `pyproject.toml` directly.
2. Most routes AC-6 commands would call (`assure`/`outcome`/`recovery`/`passport`) do not exist yet — that is Gate 3 wiring, which needs both `[KB]` and `[AC]` stream-complete handoffs reviewed first.

A hand-rolled terminal UI without Textual was deliberately not attempted; it would be exactly the kind of unsupported-capability-shown-as-supported this project's "no safety theater" invariant forbids.

### `[kb]` - 2026-09-19 00:01 -04:00 - Assignment review and three-commit delivery

The user requested a recheck of all assigned Person 2 work, removal of `.vscode/settings.json`, exactly three commits, and `[kb]` tags with timestamps and milestone updates going forward. The local settings file was removed; it was untracked and therefore has no Git deletion diff.

KB-0 through KB-6 were rechecked against the plan. Existing Git and bounded execution work is tested; the new checkpoint/launcher/environment/dependency/assurance interfaces and full stream remain incomplete. `backend/app/git/KB_HANDOFF.md` now provides the per-assignment milestone table and remaining gates.

Review corrected numeric-bound validation: fractional/boolean/non-integer output limits and non-finite/invalid collector timeouts now fail before subprocess startup. No shared contracts or other owner's feature code changed.

- Milestone 1, 00:00 -04:00: review and settings removal complete.
- Milestone 2, 00:01 -04:00: `python -m coverage run --branch --source=backend/app/git,backend/app/execution -m pytest` passed **150 tests in 28.96 seconds**, no skips/xfails. `python -m coverage report -m` reports **100% statement and branch coverage** (445 statements, 178 branches) for both packages. `git diff --check` passed.
- Milestone 3: three-commit delivery — `5bf01cb` execution foundation, `47ea584` Git hardening, then the documentation commit containing this record. Every commit uses `[kb]` and an offset-qualified timestamp. No push was requested.

This review does not represent `[SD]` acceptance or completion of KB-1 through KB-6. Continue reporting timestamped Person 2 milestones, including blockers and actual verification evidence.

### `[KB]` - 2026-09-18 23:57 -04:00 - Owned Git and execution hardening implemented

Following the user's confirmation to continue as Person 2, work proceeded against the existing frozen ports without changing shared contracts or composition. `backend/app/git/KB_HANDOFF.md` contains the exact paths, contract hashes, review boundary, tests and integration instructions.

- Git inspection now bounds capture memory, suppresses external diff/textconv/fsmonitor/filter execution and optional index writes, rejects malformed evidence with domain errors, and checks repeated status/statistics/full-diff reads for observed movement. It preserves normal Windows line-ending configuration. Active content filters and submodules are explicitly unsupported rather than silently producing incomplete evidence.
- `backend/app/execution/runner.py` provides `BoundedVerificationRunner`, a concrete existing `VerificationPort` implementation for Person 2 assurance work. It uses a reduced environment, safe executable resolution, a shared output budget and nonblocking pipes with a deadline. Timeout affects only the direct child; inherited descendant pipes cannot hang the caller. This primitive does not substitute for the missing launcher authority/attach/cancel/idempotency contracts.
- The existing uncommitted Git startup-error fix was preserved. No other owner's implementation, root dependency manifest or application wiring was edited. The new runner is exercised through dependency injection in owner tests; the production default remains the older verification runner.
- `python -m coverage run --branch --source=backend/app/git,backend/app/execution -m pytest`: **139 passed in 27.89 seconds**, no skips/xfails. `python -m coverage report -m`: **100% statement and branch coverage** across both owned packages (445 statements, 178 branches, no exclusions).
- Tests include real Windows Git repositories, hooks/filters, merge conflict, Unicode, submodule rejection, unchanged repository bytes/mtimes, bounded subprocesses, environment canaries, and an API create/refresh/verify/restart/refresh flow using real SQLite and the new runner.

This supersedes the earlier audit's no-runtime-change status. It does not complete KB-1 through KB-6: the five new shared ports/models are still absent. The full checkpoint, launcher, environment, dependency and assurance interfaces remain a concrete `[SD]` handoff dependency. Repeated Git reads are not an atomic checkpoint, and passing checks are not proof of correctness. The complete retained-proposal flow is not claimed.

### `[KB]` - 2026-09-18 23:41 -04:00 - Person 2 compatibility audit and blocked handoff

This entry records an audit, not completion of KB-1 through KB-6. The user explicitly requested updates to both context documents; this documentation update does not transfer shared-code ownership or represent an `[SD]` acceptance.

`git pull` reported already up to date at `3ccf0b8e8f0ebb4c5471637f73aa967a07752ef7`. The working tree already contained changes in `backend/app/git/adapter.py`, `backend/tests/git/test_git_adapter.py`, and an untracked `.vscode/` directory. Those changes were preserved and are not attributed to this audit. Future pulls must follow the clean-tree coordination rule.

#### Proposal comprehension submitted for `[SD]` acknowledgement

- Owned capabilities: Git baseline/current evidence (proposal pages 22 and 29), top-level agent adapters (pages 10 and 29), environment passports (pages 8 and 16), dependency comparison (pages 22 and 29), and evidence-selected assurance/deviation analysis (pages 12 and 22).
- Preserved principles: Change is the root, observation over narration, native operation, least authority, agent neutrality, and evidence coverage rather than a probability of safety (pages 2-4 and 12).
- Approved cuts: no event journal, process supervisor, filesystem tracker, or tool registry. Therefore no causal attribution, replay, descendant cleanup, local-file/environment undo, or tool-trust claims. Attach results describe supplied metadata only.
- Existing consumed contracts: `GitInspectionPort`, `VerificationPort`, `RepositoryInfo`, `GitSummary`, `ChangedPath`, `VerificationRequest`, `VerificationResult`, and `AppError`. The five planned Person 2 ports and their new evidence/authority models are absent from the shared contract package.
- Principal risks: stale or mixed Git evidence; repository-configured command execution during observation; secret inheritance/disclosure; unbounded subprocess capture or timeout escape through inherited pipes; and optimistic dependency/assurance conclusions from malformed, partial, or unsupported evidence.
- Conflicts/gaps: the execution plan assumes frozen new ports that are not implemented; the existing schema stores only latest Git/verification state; the current API has no authority or idempotency boundary. Historical UI-readiness statements describe the earlier prototype, not completion of the retained proposal.

#### `[KB]` CONTRACT CHANGE REQUEST to `[SD]`

Freeze versioned immutable Pydantic input/output models, safe errors, and port-contract tests for the following interfaces before their concrete implementations begin:

| Work item | Required interface decisions |
| --- | --- |
| KB-1 | `GitStatePort`: checkpoint identity, repository binding, content/status/index digest semantics, comparison, freshness, detached/unborn state, truncation and limitations; preserve existing `GitInspectionPort` compatibility |
| KB-2 | `AgentLauncherPort`: launch/attach/cancel, authority and idempotency binding, executable/argument/environment policy, aggregate statuses and explicit descendant limitations |
| KB-3 | `EnvironmentPort`: collectors, normalization, fingerprint salt/key ownership, redaction, capture completeness, comparison and unsupported states |
| KB-4 | `DependencyPort`: explicit supported manifest/lock versions, normalized identities, direct/resolved provenance, mismatches, bounded parsing and partial/unsupported results |
| KB-5 | `AssurancePort`: discovery/selection/run, Change Contract and evidence references, required checks, freshness, structured reporter results, deviations and coverage gaps |

Proposed concrete implementations after contract freeze: `GitStateTracker`, `AgentLauncher`, `EnvironmentTracker`, `DependencyTracker`, and `AssuranceEngine`, in the corresponding Person 2 application packages. Persistence remains a shared-core integration responsibility; no private replacement contracts or cross-owner concrete imports were introduced.

#### Review findings and verification

- `python -m pytest`: **49 passed in 7.31 seconds**. This ran the unchanged baseline, including its pre-existing uncommitted Git fix. Real temporary repositories, SQLite, API requests through TestClient, and short verification subprocesses were exercised; CORE tests also use explicit fakes.
- Reproduced: `_parse_numstat('invalid\\t0\\tfile.py\\0')` raises raw `ValueError` rather than `GitCommandError`. The parser needs stable handling of malformed numeric input, negative statistics and incomplete rename records.
- Reproduced with a synthetic value only: a parent `KB_REVIEW_SECRET_CANARY` environment variable reaches verification child output. The current runner is not suitable for the planned launcher secret boundary without an allowlisted environment and output-redaction design.
- Static finding: both Git and verification use `capture_output=True` and truncate after completion. Returned payload limits do not bound capture memory.
- Static finding: Git patch inspection uses `--no-ext-diff` but omits `--no-textconv`; repository-configured text conversion must be disabled for read-only evidence collection. Review optional index writes and inherited Git environment overrides as well.
- Static finding: independent Git commands do not establish a coherent checkpoint across concurrent repository changes. Verification results are not bound to checkpoint/contract identities; refresh invalidation alone does not prove freshness.
- No new-package coverage, Windows environment collectors, Node assurance flows, launcher cancellation, or retained-proposal end-to-end completion is claimed. Coverage tooling is not installed in the current interpreter.

Required test matrix after contract freeze: real Git status/rename/conflict/binary/unborn/Unicode fixtures; read-only and concurrent-change probes; short subprocess timeout/cancel/output/environment tests; deterministic collector redaction and partial-failure fixtures; Python/Node parser fixtures with malformed and unsupported cases; and assurance discovery, selection, freshness, deviation and missing-evidence decision tables. Each new package must report the plan's statement/branch coverage targets and owner-local flow evidence.

Handoff status: **blocked on shared contracts and comprehension acknowledgement**, not stream-complete. `[SD]` must resolve the listed contract decisions and clarify ownership of the legacy verification runner before reuse or modification. A user scope clarification was requested because implementing shared contracts/application wiring exceeds the Person 2-only ownership assignment. No runtime implementation or integration was changed by this audit.

### `[SD]` - 2026-09-18 23:27:01 -04:00 - Parallel execution packets and test depth defined

The plan now gives `[KB]` and `[AC]` complete independent execution tracks through stream-level completion before `[SD]` begins integration. Each contributor must read the entire proposal PDF, use the page-specific study guide, and submit a comprehension statement covering owned proposal capabilities, preserved principles, cut-dependent limitations, ports, risks, and document conflicts.

`[KB]` has detailed work packets KB-0 through KB-6 for evidence architecture, Git checkpoints, the Agent Launcher, environment passports, dependencies, assurance/deviation analysis, and stream hardening. `[AC]` has AC-0 through AC-8 for authority architecture, identity/delegation, policy/broker, GitHub outcomes, constrained recovery, Passport, scriptable CLI, terminal UI, and stream hardening.

Both streams develop concurrently against frozen contracts and conforming fakes. They do not edit shared composition, migrations, or each other's concrete modules. Integration starts only after both stream-complete handoffs pass `[SD]` review.

Testing requirements now define unit, port-contract, real-boundary, adversarial/failure, security/privacy, owner-local flow, and limited manual layers. New owner packages target at least 90% statement and 85% branch coverage, while security/policy/lifecycle/idempotency/recovery decisions require complete decision-table coverage. Every handoff must report exact commands, counts, coverage, real boundaries, manual checks, limitations, and known findings.

### `[SD]` - 2026-09-18 23:24:10 -04:00 - Interactive terminal UI added

The browser web UI remains deferred, but the CLI is now explicitly user-facing and includes an interactive terminal UI owned by `[AC]`. It will use Typer for commands, Rich for coloured visual output, and Textual for keyboard-driven screens and components.

Required terminal experiences include a Change dashboard, lifecycle stepper, evidence/status cards, Git and dependency tables, assurance progress/results, PR/CI panels, guided contract/delegation forms, recovery preview/confirmation, and Passport export. Colour must be semantic and restrained, always paired with text/symbols. `NO_COLOR`, `--no-color`, small-terminal/resize handling, plain non-TTY output, and JSON output are acceptance requirements rather than optional polish.

### `[SD]` - 2026-09-18 23:20:58 -04:00 - Verification and integration role established

Browser UI implementation is deferred; the CLI and terminal UI remain active. `[SD]` is the independent verifier and integration owner for all backend work submitted by `[KB]` and `[AC]`.

- `[SD]` owns shared contracts/core, migrations, application composition, independent acceptance tests, code-review findings, release verification, and the context documents.
- `[KB]` owns Git evidence, the top-level Agent Launcher, environment/dependency tracking, and assurance.
- `[AC]` owns identity/delegation, policy, credential brokering, GitHub/outcomes, constrained recovery, Change Passport, CLI, and terminal UI.

`[SD]` reviews each handoff for scope, correctness, contracts, security, migrations, failure behavior, and missing adversarial coverage. Rejected defects return to their original owner; `[SD]` does not overwrite `[KB]` or `[AC]` feature code. Only accepted handoffs enter an `[SD]` integration window. Browser frontend paths are unassigned and frozen until a later phase.

### `[SD]` - 2026-09-18 23:13:27 -04:00 - Proposal scope restored and work repartitioned

The PDF proposal is now the authoritative implementation baseline without the former two-day constraint. The active plan retains lifecycle/contracts, identity and delegation, credential brokering, the top-level Agent Launcher, Git/environment/dependency evidence, assurance, GitHub PR/CI outcomes, constrained recovery, Passport, UI, and CLI.

The only approved subsystem cuts are the event journal, process supervisor, filesystem tracker, and tool registry. Replay, descendant attribution, local-file/environment rollback, and tool trust are also unavailable because they require those removed primitives. These are technical consequences, not additional discretionary product cuts.

Work is assigned to three permanent owners:

- `[SD]`: platform, shared contracts, lifecycle, identity/policy, credential broker, recovery, Passport, and integration.
- `[KB]`: Git evidence, Agent Launcher, environment/dependency tracking, and assurance.
- `[AC]`: frontend, provider/outcome adapters, CLI, integration/E2E QA.

The existing 48-test Git review backend remains the migration baseline rather than being discarded. Its current Change, Git inspection, verification, and error behavior must be preserved or explicitly migrated while the wider proposal architecture is added.

### `[SD]` - 2026-09-18 22:22:49 -04:00 - Person 1

#### Completed scope

`[SD]` completed the initial `[INTEGRATION]` bootstrap and the Person 1 `[CORE]` implementation. The completed paths are `pyproject.toml`, `.gitignore`, `backend/app/main.py`, `backend/app/contracts/`, `backend/app/core/`, and `backend/tests/core/`. Work did not overlap the `[GIT]`, `[VERIFY]`, `[QA]`, or `[UI]` ownership areas.

The backend now has:

- A Python 3.12+ FastAPI project with Pydantic v2, SQLite, Uvicorn, pytest, and HTTPX.
- Strict shared models for Change, repository validation, Git summaries, changed paths, verification requests/results, review states, health, and errors.
- Frozen `GitInspectionPort` and `VerificationPort` interfaces for parallel implementation.
- An idempotent SQLite schema and parameterized persistence layer.
- Durable Change creation, retrieval, newest-first listing, update, and metadata deletion.
- Storage of only the latest Git summary and latest verification result, not an event journal.
- Pure deterministic review-state calculation.
- A FastAPI application factory and versioned API routes.
- Restricted CORS, bounded pagination, safe validation responses, and stable error envelopes.
- Explicit unavailable adapters until real Git and verification modules are handed off.
- CORE-only fakes used in tests, never as final application success data.

#### API delivered

- `GET /api/v1/health`
- `POST /api/v1/repositories/validate`
- `POST /api/v1/changes`
- `GET /api/v1/changes`
- `GET /api/v1/changes/{change_id}`
- `POST /api/v1/changes/{change_id}/refresh`
- `POST /api/v1/changes/{change_id}/verify`
- `DELETE /api/v1/changes/{change_id}`

#### Review-state behavior

1. Missing Git evidence or a clean Git summary returns `NO_CHANGES`.
2. Working-tree changes without verification return `MISSING_EVIDENCE`.
3. Non-passing verification returns `FAILED_VERIFICATION`.
4. Working-tree changes with passing verification return `READY_FOR_HUMAN_REVIEW`.

A Git refresh clears the stored verification result. This prevents an earlier passing command from being treated as evidence for newly refreshed repository state.

#### Data and safety behavior

- Repository canonicalization is delegated to the Git adapter before a Change is stored.
- Persistence uses parameterized SQLite queries.
- Database initialization is safe to repeat.
- Change data survives separate database connections and process restarts once the same database path is reused.
- Metadata deletion never deletes repository files.
- Git patch requests are configured for a one-megabyte limit.
- Verification output is configured for a 256 KiB limit.
- The API accepts verification executable and arguments separately; the real runner must not use a shell.
- Validation errors do not echo submitted repository paths.
- Unexpected errors do not expose local paths or stack traces through HTTP.
- Missing concrete adapters return `CAPABILITY_UNAVAILABLE`, not a fabricated successful result.

#### Validation results

- 13 CORE tests passed with `python -m pytest`.
- Backend compilation passed with `python -m compileall -q backend`.
- Generated OpenAPI included all expected routes.
- A live Uvicorn server bound to `127.0.0.1:8765` returned HTTP 200 for health and OpenAPI.
- The live health payload was `{"status":"ok","api_version":"1"}`.

Covered behavior includes contract strictness, serialization, review-state precedence, persistence, deletion, Change creation, canonical paths, refresh, verification, stale-verification invalidation, list responses, missing-Change errors, and sanitized validation failures.

#### Commits and repository state

- `5c6c587` - `[INTEGRATION] Bootstrap Python backend`
- `d4431d8` - `[CORE] Add contracts persistence and API`
- Local `master` was two commits ahead of `origin/master` at the time of this record.
- `[SD]` did not push the commits.

#### Parallel handoff

Person 2 consumes `backend.app.contracts.ports.GitInspectionPort` and the Git-related models from `backend.app.contracts.models`. Person 3 consumes `backend.app.contracts.ports.VerificationPort` and the verification models. Neither owner should edit the frozen contracts without a contract-change request.

Expected adapter failures must use or extend `backend.app.core.errors.AppError` so expected Git and verification errors retain stable API codes.

#### Still pending

- Person 2's real Git adapter and tests.
- Person 3's real verification runner and tests.
- Person 1's final concrete-adapter wiring after both handoffs.
- QA integration fixtures and real end-to-end testing.
- UI integration with the real API.
- Final removal of any UI mock data.
- Push or merge of the two local implementation commits.

The current backend is a tested CORE implementation with fake ports, not yet the complete integrated backend.

### `[AC]` - 2026-09-18 22:40:41 -04:00 - Person 3

#### Completed scope

`[AC]` completed the Person 3 `[VERIFY]` verification module (plan steps V1-V3). The completed paths are `backend/app/verification/` and `backend/tests/verification/`. Work did not overlap `[CORE]`, `[GIT]`, `[QA]`, or `[UI]` ownership areas; `backend/app/main.py` was left untouched because final concrete-adapter wiring is Person 1's Gate 3 responsibility, not Person 3's.

The verification module now has:

- An executable allowlist (`python`, `python3`, `pytest`, `uv`, `node`, `npm`, `npm.cmd`, `pnpm`, `pnpm.cmd`, `yarn`, `yarn.cmd`, `cargo`, `go`, `dotnet`) with rejection of path-separator-qualified executables.
- A concrete `VerificationPort` implementation, `SubprocessVerificationRunner`, that resolves the executable, then runs it with `subprocess.run`, `shell=False`, and `cwd` set to the canonical repository root.
- Pass/fail classification from the child exit code, and a `TIMED_OUT` result with a null exit code when the requested timeout elapses.
- Stdout/stderr bounded to the configured output limit with a combined `output_truncated` flag.
- Two distinct stable error codes, `VERIFICATION_EXECUTABLE_NOT_ALLOWED` and `VERIFICATION_EXECUTABLE_NOT_FOUND`, raised through `AppError` before any subprocess starts.

Argument count/length and timeout-range bounds were already enforced by the frozen `VerificationRequest` contract, so this module only validates and resolves the executable.

#### Validation results

- 11 new verification tests passed with `python -m pytest`.
- Full backend suite passed after pulling Person 2's Git adapter: 29 tests (13 CORE + 5 GIT + 11 VERIFY), no regressions.

#### Known limitations

- Only the direct child process is supervised. Descendant processes are not tracked or terminated on timeout, matching the project's documented non-goal around process-tree control.

#### Commits and repository state

- Not yet committed; pending explicit approval per this developer's workflow rules.
- Local `master` was fast-forwarded to `d4ed137` (`[KB]` Person 2 Git inspection) before this record was written.

#### Handoff

Person 1 can wire `backend.app.verification.runner.SubprocessVerificationRunner()` into `create_app(verification=...)` at Gate 3; the class takes no constructor arguments and implements `VerificationPort.run(repository_path, request, output_limit_bytes)`.

#### Still pending

- Person 1's final concrete-adapter wiring (Git and verification) into `main.py`.
- Person 3's `[QA]` phase: integration fixtures, API integration tests, and the demo smoke test.
- UI integration with the real API.

### `[SD]` - 2026-09-18 22:57:28 -04:00 - Integration recovery complete

After reviewing the Person 2 and Person 3 work, `[SD]` corrected the blocking contract and behavior defects and completed concrete backend wiring.

#### Git adapter corrections

- Returns `RepositoryInfo` and `GitSummary` instead of incompatible dictionaries.
- Uses stable API errors: `INVALID_REPOSITORY_PATH`, `NOT_A_GIT_REPOSITORY`, `REPOSITORY_HAS_NO_COMMITS`, and `GIT_COMMAND_FAILED`.
- Correctly parses ordinary, rename/copy, conflict, and untracked porcelain-v2 records.
- Correctly interprets `.` as unchanged for staged/unstaged state.
- Reports staged deletes and renames with the right status and previous path.
- Uses one NUL-delimited numstat source, preventing staged-change double counting.
- Populates per-file additions, deletions, and binary state.
- Does not read untracked file contents.
- Keeps `untracked_patch_omitted` separate from `patch_truncated`.
- Truncates tracked patches by UTF-8 bytes rather than Python characters.
- Covers dependency, test/spec, configuration/CI, documentation, source, and other classification precedence.

#### Verification corrections

- Stdout and stderr now share one total output budget.
- UTF-8 truncation cannot exceed the configured byte limit.
- Subprocess startup failures return `ERROR` with a null exit code and safe message.
- Existing allowlist, `shell=False`, working-directory, pass/fail, and timeout behavior remains intact.

#### Integration completed

- `create_app()` now uses `GitRepositoryInspector` and `SubprocessVerificationRunner` by default.
- Added real temporary-repository API tests.
- Verified create -> external file edit -> refresh -> passing verification -> `READY_FOR_HUMAN_REVIEW`.
- Verified a later refresh clears stale verification evidence.
- Verified failing and timed-out commands produce `FAILED_VERIFICATION`.
- Verified disallowed executables and invalid repositories use stable error envelopes.

#### Current validation state

- 48 tests pass in the full suite.
- The full suite passed twice in separate invocations.
- Backend compilation passes.
- Frozen port runtime checks pass for both concrete adapters.
- Live health and OpenAPI checks return HTTP 200 on loopback.
- No live smoke-test server remains running.

#### Updated readiness

The backend is ready for UI integration. Git inspection, verification execution, persistence, review-state composition, and the real API path are integrated. Remaining release work is UI integration, removal of UI mocks, and final end-to-end demo validation through the actual user interface.
