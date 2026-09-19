# Change Assurance - Project Context

## Relationship to overall context

This document defines the active implementation of `Change_Assurance_Runtime_Project_Proposal (2).pdf`. Read `OVERALL_CONTEXT.md` first for stable product principles, vocabulary, the CML working standard, and decision authority. The PDF proposal is the feature baseline; this document records the four approved cuts and their necessary consequences.

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
- Versioned Change Passport, CLI, capabilities reporting, and explicit unsupported states.
- A frozen OpenAPI contract suitable for a later UI phase; frontend implementation is deferred.

## Approved cuts

The following proposal subsystems are intentionally removed from the product:

- Event/effect journal and causal timeline.
- Process supervisor, descendant-process attribution, and process cleanup.
- Filesystem observation, before-images, snapshots, file-effect attribution, and local-file recovery/undo.
- Tool registry, MCP inventory, tool manifests, signatures, and trust decisions.

## Necessary consequences and non-goals

- No causal event/effect timeline, trace replay, or replay engine because the event journal is absent.
- No descendant-process ownership, orphan cleanup, process-tree policy, or Windows Job Object enforcement because the process supervisor is absent.
- No uncommitted-file restoration, resource versions, write attribution, or environment rollback because filesystem/process observation is absent.
- No tool manifests, signatures, inventory, trust decisions, or capability-drift tracking because the tool registry is absent.
- No attribution of an environment/dependency change to a particular process; only checkpoint comparison is claimed.
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
- Replay or local-file/environment rollback.
- Process-tree visibility.
- Tool or credential trust enforcement.
- General recovery beyond the explicitly supported Git/provider actions.

## Active architecture

```text
CLI / API clients (web UI deferred)
  -> Authenticated local API
       -> Change lifecycle, contracts, identity, policy
       -> Credential broker and GitHub outcomes
       -> Top-level Agent Launcher
       -> Git, environment, and dependency trackers
       -> Assurance engine
       -> Constrained recovery engine
       -> Change Passport builder
       -> SQLite state/evidence store
```

The Agent Launcher may start or attach to a top-level invocation, but it does not observe or control a descendant process tree. Git is the source of code-change evidence; it is not filesystem-effect attribution.

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

The backend phase meets all acceptance criteria in `BACKEND_IMPLEMENTATION_PLAN.md`: the retained proposal flow works end to end through the API and CLI using real data, migrations preserve existing data, authority and credentials are enforced, evidence freshness gates lifecycle state, every relevant failure or unsupported condition is represented, and recovery stays inside its documented Git/provider boundary.

No code, schema, route, or copy may imply an event journal, process supervision, filesystem tracking/undo, tool registry/trust, or replay. UI implementation and browser acceptance are not part of this phase and cannot block backend completion.

## Current implementation status

### `[SD]` - 2026-09-18 23:20:58 -04:00 - Verification and integration role established

UI implementation is deferred. `[SD]` is now the independent verifier and integration owner for all backend work submitted by `[KB]` and `[AC]`.

- `[SD]` owns shared contracts/core, migrations, application composition, independent acceptance tests, code-review findings, release verification, and the context documents.
- `[KB]` owns Git evidence, the top-level Agent Launcher, environment/dependency tracking, and assurance.
- `[AC]` owns identity/delegation, policy, credential brokering, GitHub/outcomes, constrained recovery, Change Passport, and CLI.

`[SD]` reviews each handoff for scope, correctness, contracts, security, migrations, failure behavior, and missing adversarial coverage. Rejected defects return to their original owner; `[SD]` does not overwrite `[KB]` or `[AC]` feature code. Only accepted handoffs enter an `[SD]` integration window. Frontend paths are unassigned and frozen until a later phase.

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
