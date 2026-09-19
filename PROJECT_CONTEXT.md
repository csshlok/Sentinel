# Change Assurance - Project Context

## Relationship to overall context

This document defines the active two-day implementation slice. Read `OVERALL_CONTEXT.md` first for stable product principles, vocabulary, the CML working standard, and decision authority. This document may narrow that direction but must not silently contradict it.

## Goal

Build a two-day, repository-scoped prototype that helps a developer review an AI-assisted code change before accepting it. The prototype is a local Git review dashboard, not an execution security runtime.

## The demo promise

A developer can select a local Git repository, enter the intended change, let a coding agent or developer work outside the app, and then use the app to:

1. See the current Git status and diff.
2. Understand which files changed and the size/type of the change.
3. Run one configured test or build command and see its final result.
4. Review intent, source changes, and verification evidence in one UI.
5. Decide whether the change is ready for human review.

## Intended live demo

1. Open a sample Git repository in the app.
2. Create a Change with a short intent statement.
3. Use Codex, another agent, or a manual edit outside the app to modify the repository.
4. Refresh the Change Review to load Git status and diff.
5. Run the configured verification command.
6. Show the summarized files, diff, test/build result, and review readiness.

## Required scope

- Select and validate an existing local Git repository.
- Create a lightweight Change record with an ID, title/intent, repository path, and timestamps.
- Read Git branch, HEAD, working-tree status, diff statistics, and patch content.
- Classify changed paths using simple rules such as source, test, dependency, configuration, and documentation.
- Run one user-configured test or build command as a one-shot subprocess.
- Store only the final verification command, exit code, duration, and output needed by the UI.
- Provide a UI with Change List, New Change, Change Review, Diff, and Verification Result views.
- Clearly show missing evidence and unsupported capabilities.

## Cut from this prototype

The following subsystems are intentionally removed from the two-day build:

- Event/effect journal and causal timeline.
- Process supervisor, descendant-process attribution, and process cleanup.
- Filesystem observation, before-images, snapshots, file-effect attribution, and recovery/undo.
- Tool registry, MCP inventory, tool manifests, signatures, and trust decisions.

## Other non-goals

- Credential brokering, secret storage, or GitHub authorization.
- OS sandboxing or Windows Job Object enforcement.
- Host-machine environment provenance or recovery.
- Package-install attribution or external API effect tracking.
- CI, pull-request, deployment, or cloud integration.
- Replay of commands, tools, agents, or filesystem state.
- Cross-platform behavioral guarantees.

## Product language

Preferred terms:

- "Git-based Change Review prototype"
- "working-tree changes"
- "verification result"
- "ready for human review"

Do not claim:

- Complete observation or attribution.
- Safe execution or sandboxing.
- Replay, rollback, or recovery.
- Process-tree visibility.
- Tool or credential trust enforcement.
- Production readiness.

## Suggested architecture

```text
Web UI
  -> Local API/service
       -> Lightweight Change store
       -> Read-only Git inspection adapter
       -> One-shot verification command runner
```

The coding agent does not run inside or through this prototype. It modifies the selected repository independently; the app reviews the resulting Git working tree.

## Core data concepts

- **Change**: ID, title, intent, repository path, created time, and last refresh time.
- **Git summary**: branch, HEAD, changed paths, status, additions/deletions, and patch.
- **Path classification**: source, test, dependency, configuration, documentation, or other.
- **Verification result**: command, start/end time, exit code, duration, result status, and bounded output.
- **Review state**: ready, failed verification, or missing evidence. This is a UI summary, not a correctness guarantee.

## Definition of done

The project is demo-ready when a user can create a Change for a sample repository, modify that repository outside the app, refresh and inspect its Git diff, run one verification command, and view a clear review summary. No demo path or UI text may imply event journaling, process supervision, filesystem tracking, tool trust, or recovery.

The final demo must use real backend responses and a real Git repository. Mock data, hardcoded health/readiness labels, and placeholder success values are allowed during isolated UI development only and must be removed before acceptance.

## Current implementation status

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
