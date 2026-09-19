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
