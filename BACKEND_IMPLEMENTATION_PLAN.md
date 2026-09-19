# Three-Person Backend Implementation Plan

## 1. Outcome

Deliver the complete backend for the two-day Git-based Change Review prototype. The backend must let the UI:

1. Create and list lightweight Change records.
2. Validate a local Git repository.
3. inspect its current branch, HEAD, working-tree status, diff statistics, and patch.
4. Classify changed paths.
5. Run one approved verification command.
6. Return a review state based on Git changes and the latest verification result.

This plan intentionally excludes the event journal, process supervision, filesystem tracking/snapshots, recovery, replay, and tool registry described in the original proposal.

## 2. Delivery constraints

- Three backend contributors.
- Two calendar days.
- Windows is the demo platform.
- All contributors use one shared repository and must not edit overlapping files.
- The backend is local-only and binds to `127.0.0.1`.
- The coding agent runs outside this backend.
- Git is the only source of change information.
- The backend reports review evidence; it never claims correctness or safety.
- Implementation, integration, error handling, and acceptance must satisfy the CML working standard in `OVERALL_CONTEXT.md`.

## 3. Technology decision

Use Python 3.12+ with:

- FastAPI for the local HTTP API.
- Pydantic v2 for request/response contracts.
- The Python standard-library `sqlite3` module for persistence.
- The Python standard-library `subprocess` module for Git and verification commands.
- Pytest for unit and integration tests.
- Uvicorn for local development serving.

This stack avoids a native database dependency, works well on Windows, and keeps the UI/backend boundary as ordinary JSON over HTTP.

## 4. Repository layout and exclusive ownership

```text
backend/
  app/
    main.py                         # [CORE]
    core/                           # [CORE]
      config.py
      errors.py
      database.py
      change_repository.py
      change_service.py
      review_service.py
      router.py
    contracts/                      # [CORE], frozen after Gate 1
      models.py
      ports.py
    git/                            # [GIT]
      adapter.py
      parser.py
      classifier.py
      errors.py
    verification/                   # [VERIFY]
      runner.py
      validation.py
      errors.py
  tests/
    core/                           # [CORE]
    git/                            # [GIT]
    verification/                  # [VERIFY]
    integration/                   # [QA] after module handoffs
  fixtures/                         # [QA]
pyproject.toml                      # [INTEGRATION]
.gitignore                          # [INTEGRATION]
```

No contributor edits another contributor's path. Changes to `backend/app/contracts/` after Gate 1 are made only by `[CORE]` following a written contract-change request.

## 5. The three assignments

### Person 1 - `[CORE]` API, persistence, and integration lead

Owns:

- FastAPI application creation and lifecycle.
- Shared Pydantic contracts and service protocols.
- SQLite schema and migrations/bootstrap.
- Change CRUD service.
- Review-state composition.
- HTTP routes, error envelope, and OpenAPI output.
- Final adapter wiring after formal handoff.

Does not own:

- Git command construction or parsing.
- Path classification rules.
- Verification subprocess implementation.
- Git or verification module tests.

### Person 2 - `[GIT]` repository inspection lead

Owns:

- Repository validation.
- Safe, argument-array Git subprocess calls with `shell=False`.
- Branch and HEAD inspection.
- Porcelain status parsing.
- Diff statistics and bounded patch retrieval.
- Changed-path classification.
- Git-specific errors and tests.

Does not own:

- HTTP routes.
- SQLite.
- Verification command execution.
- Shared contract definitions.

### Person 3 - `[VERIFY]` verification and quality lead

Owns initially:

- Verification-command validation.
- Approved executable configuration.
- One-shot subprocess execution.
- Timeouts, duration, exit status, and bounded output.
- Verification-specific errors and tests.

After the verification module is handed off, this person switches to `[QA]` and owns:

- End-to-end fixtures.
- API integration tests.
- Demo smoke test.
- Final acceptance checklist execution.

This tag switch must be announced. `[VERIFY]` work must be committed or handed off before `[QA]` work begins.

## 6. Contract-first design

All three contributors spend the first 45 minutes agreeing on the following contracts. Person 1 records them in `backend/app/contracts/`. After Gate 1, Persons 2 and 3 implement against those contracts without editing them.

### 6.1 Change model

```text
Change
  id: UUID string
  title: string, 1-120 characters
  intent: string, 1-2000 characters
  repository_path: canonical absolute path
  created_at: UTC timestamp
  updated_at: UTC timestamp
  last_refreshed_at: UTC timestamp or null
  git_summary: GitSummary or null
  verification: VerificationResult or null
  review_state: NO_CHANGES | MISSING_EVIDENCE | FAILED_VERIFICATION | READY_FOR_HUMAN_REVIEW
```

There is no event collection. Each refresh overwrites the latest Git summary, and each verification run overwrites the latest verification result.

### 6.2 Git contracts

```text
RepositoryInfo
  root: canonical absolute path
  branch: string or null
  head_sha: 40-character SHA

ChangedPath
  path: repository-relative POSIX-style path
  old_path: string or null
  status: ADDED | MODIFIED | DELETED | RENAMED | COPIED | UNTRACKED | CONFLICTED
  staged: boolean
  unstaged: boolean
  additions: integer or null
  deletions: integer or null
  category: SOURCE | TEST | DEPENDENCY | CONFIG | DOCUMENTATION | OTHER
  binary: boolean

GitSummary
  repository_root: string
  branch: string or null
  head_sha: string
  is_clean: boolean
  files: ChangedPath[]
  total_additions: integer
  total_deletions: integer
  patch: string
  patch_truncated: boolean
  untracked_patch_omitted: boolean
  refreshed_at: UTC timestamp
```

`GitInspectionPort` exposes:

```text
validate_repository(path) -> RepositoryInfo
inspect(path, patch_limit_bytes) -> GitSummary
```

### 6.3 Verification contracts

The API accepts an executable and argument list, not a shell command string:

```text
VerificationRequest
  executable: string
  args: string[]
  timeout_seconds: integer, 1-300

VerificationResult
  executable: string
  args: string[]
  status: PASSED | FAILED | TIMED_OUT | ERROR
  exit_code: integer or null
  duration_ms: integer
  stdout: string
  stderr: string
  output_truncated: boolean
  started_at: UTC timestamp
  completed_at: UTC timestamp
```

`VerificationPort` exposes:

```text
run(repository_path, request, output_limit_bytes) -> VerificationResult
```

### 6.4 Error envelope

Every non-2xx API response uses:

```json
{
  "error": {
    "code": "STABLE_MACHINE_CODE",
    "message": "Human-readable explanation",
    "details": {}
  }
}
```

Expected codes include:

- `CHANGE_NOT_FOUND`
- `INVALID_REPOSITORY_PATH`
- `NOT_A_GIT_REPOSITORY`
- `REPOSITORY_HAS_NO_COMMITS`
- `GIT_COMMAND_FAILED`
- `VERIFICATION_EXECUTABLE_NOT_ALLOWED`
- `VERIFICATION_EXECUTABLE_NOT_FOUND`
- `VERIFICATION_TIMED_OUT`
- `VALIDATION_ERROR`
- `INTERNAL_ERROR`

## 7. API surface

### Health

- `GET /api/v1/health`
  - Returns service status and API version.

### Repository validation

- `POST /api/v1/repositories/validate`
  - Input: `{ "path": "C:\\work\\repo" }`
  - Validates that the path exists, resolves to a Git work tree, and has a commit.
  - Returns `RepositoryInfo`.

### Changes

- `POST /api/v1/changes`
  - Input: title, intent, repository path.
  - Validates and canonicalizes the repository before insertion.
  - Returns `201` and the Change.

- `GET /api/v1/changes`
  - Returns newest-first Change summaries.

- `GET /api/v1/changes/{change_id}`
  - Returns the complete current Change view.

- `DELETE /api/v1/changes/{change_id}`
  - Optional only after required endpoints pass. Deletes metadata, not repository content.

### Git refresh

- `POST /api/v1/changes/{change_id}/refresh`
  - Inspects the current working tree.
  - Replaces the stored latest Git summary.
  - Recomputes review state.
  - Returns the complete Change view.

### Verification

- `POST /api/v1/changes/{change_id}/verify`
  - Input: `VerificationRequest`.
  - Runs in the canonical repository root.
  - Replaces the stored latest verification result.
  - Recomputes review state.
  - Returns the complete Change view.

No timeline, replay, recovery, process, tool, or filesystem-effect endpoints are permitted.

## 8. Persistence design

Use one SQLite database stored under a configurable local data directory. Enable foreign keys and a busy timeout. WAL mode is optional for this single-process prototype.

### `changes` table

```text
id                    TEXT PRIMARY KEY
title                 TEXT NOT NULL
intent                TEXT NOT NULL
repository_path       TEXT NOT NULL
created_at            TEXT NOT NULL
updated_at            TEXT NOT NULL
last_refreshed_at     TEXT NULL
git_summary_json      TEXT NULL
verification_json     TEXT NULL
```

Rules:

- Store UTC timestamps in ISO 8601 form.
- Store only the latest Git summary and verification result.
- Validate deserialized JSON with Pydantic before returning it.
- Use parameterized SQL exclusively.
- Open database transactions inside the repository layer.
- Never modify the selected Git repository from persistence code.

## 9. Detailed work breakdown

### Person 1 - `[CORE]`

#### C1. Bootstrap contracts and application shell

- Create package layout and `__init__.py` files inside owned paths.
- Define all enums and Pydantic models.
- Define `GitInspectionPort` and `VerificationPort` protocols.
- Create FastAPI app factory.
- Add health endpoint.
- Add centralized exception mapping and validation error handling.

Acceptance:

- App imports without concrete Git/verification implementations.
- OpenAPI generation succeeds.
- Contract serialization tests pass.

#### C2. Persistence

- Implement database initialization.
- Create the `changes` table idempotently.
- Implement create, list, get, update-latest-Git, update-latest-verification, and delete metadata methods.
- Test restart persistence using a temporary database.

Acceptance:

- CRUD tests pass.
- Unknown ID maps to `CHANGE_NOT_FOUND`.
- JSON and timestamps round-trip correctly.

#### C3. Change and review services

- Validate title and intent through Pydantic.
- Ask `GitInspectionPort` to validate/canonicalize a repository on Change creation.
- Implement review-state precedence:
  1. No Git summary or clean Git summary -> `NO_CHANGES`.
  2. Changes exist and no verification result -> `MISSING_EVIDENCE`.
  3. Latest verification is not `PASSED` -> `FAILED_VERIFICATION`.
  4. Changes exist and verification passed -> `READY_FOR_HUMAN_REVIEW`.
- Make clear that readiness means evidence is present, not that the code is correct.

Acceptance:

- Every state has a unit test.
- Refresh and verify overwrite the prior latest result.

#### C4. HTTP routes

- Implement required endpoints.
- Keep route handlers thin.
- Enforce response models.
- Add bounded pagination parameters to list Changes if time permits; otherwise cap results at 100.
- Configure CORS only for the agreed local UI origin.

Acceptance:

- Route tests cover success, validation failure, and missing Change.
- No stack trace or local path is returned in unexpected-error messages.

#### C5. Final wiring

- After `[GIT]` and `[VERIFY]` handoffs, instantiate concrete adapters in `main.py`.
- Do not change adapter implementations during wiring.
- If a contract mismatch exists, return it to the owning person rather than patching across ownership boundaries.

### Person 2 - `[GIT]`

#### G1. Git subprocess boundary

- Implement one private command function using an argument array and `shell=False`.
- Always use `git -C <canonical-root> ...`.
- Set a short timeout for inspection commands.
- Decode output as UTF-8 with replacement for invalid bytes.
- Translate failures to stable Git-domain errors.

Acceptance:

- Paths containing spaces work.
- Arguments cannot be interpreted as shell syntax.
- Missing Git executable and nonzero exits are distinguishable.

#### G2. Repository validation

- Reject nonexistent and non-directory paths.
- Resolve the canonical repository top level with `git rev-parse --show-toplevel`.
- Require `git rev-parse --verify HEAD` for the prototype.
- Return branch using `git branch --show-current`; allow `null` for detached HEAD.

Acceptance:

- Normal repo, nested directory, detached HEAD, non-repo, and no-commit repo are tested.

#### G3. Status parsing

- Use `git status --porcelain=v2 -z --untracked-files=all`.
- Parse ordinary, renamed/copied, unmerged, and untracked records.
- Normalize returned paths to repository-relative `/` separators.
- Preserve staged and unstaged flags separately.

Acceptance:

- Tests cover modified, added, deleted, staged, unstaged, renamed, untracked, and conflicted states.

#### G4. Diff statistics and patch

- Use Git output relative to `HEAD` so staged and unstaged tracked changes appear together.
- Obtain machine-readable statistics using `--numstat`.
- Mark binary counts as `null`.
- Return a no-color, no-external-diff patch.
- Enforce a default 1 MiB patch limit and return `patch_truncated=true` when exceeded.
- Report untracked paths in status, but set `untracked_patch_omitted=true`; do not read their contents directly in this MVP.

Acceptance:

- Combined staged/unstaged changes are represented once per path.
- Binary files do not crash parsing.
- Large patches are deterministically truncated.

#### G5. Classification

Apply deterministic precedence:

1. Dependency: lockfiles and package manifests.
2. Test: test/spec directories and common test filename patterns.
3. Configuration: common config names/extensions and CI configuration directories.
4. Documentation: Markdown, docs directories, and common documentation files.
5. Source: recognized source-code extensions.
6. Other.

Keep classification pure and table-driven.

Acceptance:

- Every class and precedence collision has a unit test.

### Person 3 - `[VERIFY]`, then `[QA]`

#### V1. Command validation

- Accept separate `executable` and `args`; reject shell command strings.
- Configure an allowlist for the demo, initially: `python`, `python3`, `pytest`, `uv`, `node`, `npm`, `npm.cmd`, `pnpm`, `pnpm.cmd`, `yarn`, `yarn.cmd`, `cargo`, `go`, and `dotnet`.
- Reject path separators in the executable field unless an explicit absolute-executable feature is approved later.
- Clamp timeouts to 1-300 seconds.
- Limit argument count and individual argument length.

Acceptance:

- Shell metacharacters in an argument remain a literal argument.
- Disallowed and missing executables return different errors.

#### V2. One-shot execution

- Resolve the executable with `shutil.which`.
- Run with `cwd` set to the canonical repository root.
- Use `shell=False`.
- Capture stdout and stderr separately.
- Record monotonic duration and UTC start/completion times.
- Return pass for exit code 0 and fail for any other exit code.

Acceptance:

- Passing and failing commands return correct statuses.
- The child receives the repository as its working directory.

#### V3. Timeout and output bounds

- Enforce the requested timeout on the direct child process.
- Return `TIMED_OUT` with a null exit code when appropriate.
- Bound stored output to 256 KiB total and mark truncation.
- Do not claim or attempt descendant-process supervision or orphan cleanup.

Acceptance:

- Timeout test completes predictably.
- High-output command cannot create an unbounded API response or database value.

#### Q1. Integration fixtures

After the `[VERIFY]` handoff, switch to `[QA]`:

- Create temporary Git repositories programmatically.
- Configure local fixture-only Git identity.
- Commit a clean baseline.
- Provide fixture operations for modify, stage, delete, rename, and add untracked files.
- Do not rely on the developer's global Git configuration.

#### Q2. API integration tests

- Health.
- Validate repository.
- Create/list/get Change.
- Refresh after a source edit.
- Verify with a passing command.
- Verify with a failing command.
- Review-state transitions.
- Invalid path, non-repo, missing Change, disallowed executable, timeout, and output truncation.

#### Q3. Demo smoke test

Automate the exact backend demo:

1. Create fixture repo and baseline commit.
2. Create Change through the API.
3. Modify source and test files outside the API.
4. Refresh.
5. Assert Git summary and classifications.
6. Run passing verification.
7. Assert `READY_FOR_HUMAN_REVIEW`.

## 10. Necessary collaboration and integration gates

These are the only planned points where work intertwines.

### Gate 0 - Bootstrap window (first 30 minutes)

Participants: all three.

- Agree on Python version, commands, UI origin, and allowed verification executables.
- Person 1 temporarily uses `[INTEGRATION]` to create only root dependency/configuration files.
- Persons 2 and 3 do not edit until bootstrap files are committed.

Exit criteria:

- Environment installs successfully.
- Empty app and test commands run.
- Ownership paths exist.

### Gate 1 - Contract freeze (by minute 75)

Participants: all three; Person 1 is the only editor.

- Walk through every contract in Section 6.
- Confirm names, nullability, enums, output limits, and error codes.
- Person 1 commits the shared contracts and ports.
- Persons 2 and 3 acknowledge them in writing.

Exit criteria:

- Contracts serialize.
- Ports import.
- No unresolved naming or behavior question remains.

After this gate, all three work in parallel.

### Gate 2 - Adapter handoff (end of Day 1)

Participants: all three; each owner edits only their files.

`[GIT]` supplies:

- Concrete class name and constructor.
- Passing Git tests.
- Example `GitSummary` output.
- Known limitations.

`[VERIFY]` supplies:

- Concrete class name and constructor.
- Passing verification tests.
- Example pass/fail/timeout output.
- Known limitations.

`[CORE]` supplies:

- Working persistence and routes using fakes.
- Passing core tests.
- Expected dependency-construction signature.

Exit criteria:

- Each module passes independently.
- No one begins cross-module fixes during the handoff meeting.
- Contract mismatches become explicit owner-tagged tasks.

### Gate 3 - Concrete wiring (start of Day 2)

Participants: Person 1 integrates; Persons 2 and 3 remain available but do not edit core files.

- Person 1 replaces fake ports with concrete adapters.
- Run a single create -> refresh -> verify flow.
- Any adapter defect is returned to its owner with exact reproduction steps.
- Only the owner edits the defective module.

Exit criteria:

- The live server completes the happy path.
- OpenAPI matches the frozen response models.
- Person 3 can begin `[QA]` integration tests.

### Gate 4 - Acceptance and release candidate (final four hours)

Participants: all three.

- Person 3 runs the integration suite and demo smoke test.
- Person 2 fixes only Git failures.
- Person 1 fixes only API/storage/composition failures.
- Person 3 fixes only verification/test-harness failures.
- Person 1 performs the final `[INTEGRATION]` configuration change, if needed, after all owners hand off.

Exit criteria:

- Required tests pass twice from a clean process start.
- The demo smoke test passes.
- No endpoint or UI-facing text claims a cut capability.
- Known limitations are documented.

## 11. Two-day schedule

### Day 1

| Time block | Person 1 - CORE | Person 2 - GIT | Person 3 - VERIFY |
| --- | --- | --- | --- |
| 0:00-0:30 | Gate 0 bootstrap | Gate 0 decisions | Gate 0 decisions |
| 0:30-1:15 | Write/freeze contracts | Review contracts | Review contracts |
| 1:15-3:30 | Database and Change repository | Git command boundary and repo validation | Command validation and basic runner |
| 3:30-5:30 | Change/review services | Status parser and tests | Timeout/output bounds and tests |
| 5:30-7:00 | Routes using fake adapters | Diff/statistics and classification | Finish module tests and handoff notes |
| 7:00-8:00 | Gate 2 handoff | Gate 2 handoff | Gate 2 handoff |

### Day 2

| Time block | Person 1 - CORE/INTEGRATION | Person 2 - GIT | Person 3 - VERIFY/QA |
| --- | --- | --- | --- |
| 0:00-1:30 | Gate 3 concrete wiring | Fix owner-scoped adapter issues | Handoff VERIFY, create QA fixtures |
| 1:30-3:30 | Error handling and API hardening | Windows/path/binary edge cases | API integration tests |
| 3:30-5:00 | UI contract support and OpenAPI check | Support integration defects | Demo smoke test and state-transition tests |
| 5:00-7:00 | Gate 4 owner-scoped fixes | Gate 4 owner-scoped fixes | Gate 4 test/verify cycle |
| 7:00-8:00 | Release candidate and run instructions | Final Git sign-off | Final acceptance report |

If time slips, drop the optional DELETE endpoint and pagination first. Do not cut validation, output limits, state-transition tests, or the end-to-end demo path.

## 12. Testing strategy

The CML-quality rule is that final acceptance exercises real state through real boundaries. Unit fakes are allowed inside module tests, but the release candidate may not rely on fake Git results, fake verification results, hardcoded readiness, or in-memory-only persistence.

### Required unit coverage

- Contract validation and JSON round trips.
- Review-state precedence.
- SQLite create/list/get/update/restart behavior.
- Git status parsing for all supported states.
- Diff parsing, binary handling, and truncation.
- Classification rules and precedence.
- Verification pass/fail/timeout/error/truncation.

### Required integration coverage

- API with a real temporary SQLite database.
- API with a real temporary Git repository.
- API with a real safe verification executable.
- Full Change creation, refresh, verification, and review-state flow.

### Manual Windows checks

- Repository path containing spaces.
- Repository path containing non-ASCII characters.
- `npm.cmd` or another Windows command shim.
- Detached HEAD display.
- Server restart retains Change data.
- UI origin can call the API; an unapproved browser origin cannot read responses.

## 13. Safety and correctness boundaries

- Bind only to loopback.
- Restrict CORS to the configured UI origin.
- Never use `shell=True`.
- Never concatenate repository paths into command strings.
- Never run Git hooks as part of inspection commands.
- Never modify, reset, clean, checkout, add, or commit the selected repository.
- Cap Git patch output and verification output.
- Cap command duration.
- Redact unexpected internal exceptions in HTTP responses.
- Do not describe a passed test command as proof of correctness.
- Document that timeout applies to the direct child only; descendant-process control is out of scope.

## 14. Definition of backend complete

The backend is complete when all of the following are true:

- A fresh setup command installs and starts the local API.
- Health and OpenAPI endpoints load.
- A valid committed Git repository can be registered as a Change.
- Changes survive a backend restart.
- Refresh reports tracked and untracked working-tree paths, classifications, statistics, and a bounded tracked-file patch.
- Passing, failing, timed-out, missing, and disallowed verification commands return stable results.
- Review state follows the documented precedence.
- The complete demo smoke test passes.
- Required unit and integration tests pass.
- The API contains no endpoints for cut subsystems.
- The backend never writes to the selected repository except through the explicitly requested verification command's own behavior.

## 15. Handoff templates

### Module handoff

```text
[TAG] HANDOFF to [CORE]
Status: ready
Changed files: <exact list>
Concrete implementation: <import path and class>
Contract implemented: <port name>
Verification: <command and result>
Known limitations: <list>
```

### Contract-change request

```text
[TAG] CONTRACT CHANGE REQUEST to [CORE]
Current contract: <field/method>
Problem: <reproduction and reason>
Smallest proposed change: <exact change>
Affected tests/consumers: <list>
```

Person 1 either accepts and edits the contract or rejects the request with a workaround. Persons 2 and 3 never edit shared contracts directly.
