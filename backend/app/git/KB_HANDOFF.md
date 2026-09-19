# Person 2 stream-complete handoff (KB-0 .. KB-6)

`[kb] HANDOFF to [SD]` — 2026-09-19 01:55 -04:00

Status: **ready for independent `[SD]` review.** Every `[KB]` port in the frozen
contracts has a production implementation, real-boundary tests and documented
limitations. Nothing here wires the application; composition, persistence and
routes are `[SD]`'s Gate 3 work. This is self-verification, not `[SD]` acceptance.

The user confirmed this session is Person 2 and instructed end-to-end
implementation and testing. That is not an invented `[SD]` comprehension
acknowledgement; the comprehension statement is recorded in `PROJECT_CONTEXT.md`.

## Changed paths (all `[KB]`-owned)

- `backend/app/git/`: `adapter.py` (stderr no longer starves the stdout patch
  budget), `state.py` (new), `reader.py` (new).
- `backend/app/execution/`: `_process.py` (cancel/pid/separate stderr budget/long
  timeout), `resolve.py` (new), `launcher.py` (new).
- `backend/app/environment/tracker.py`, `backend/app/dependencies/{parsers,tracker}.py`,
  `backend/app/assurance/{models,deviations,discovery,engine}.py` (all new).
- Tests: `backend/tests/{git,execution,environment,dependencies,assurance,kb_flow}/`
  and `backend/tests/support_kb.py`.
- Context documents were updated at the user's explicit request.

No shared contract, migration, composition, dependency manifest or other owner's
concrete module was edited. Contract hashes consumed:
`ports.py` `550fb936777814e2d83ba562ed87863afda2537861a8c06f4215c74118232f04`,
`models.py` `a836f66e7330193995b66584fa875a0f102dad754c9272734462b946b949757f`.

## Port map

| Work item | Port | Concrete class |
| --- | --- | --- |
| KB-1 | `GitStatePort` | `backend.app.git.state.GitStateTracker` |
| KB-2 | `AgentLauncherPort` | `backend.app.execution.launcher.AgentLauncher` |
| KB-3 | `EnvironmentPort` | `backend.app.environment.tracker.EnvironmentTracker` |
| KB-4 | `DependencyPort` | `backend.app.dependencies.tracker.DependencyTracker` |
| KB-5 | `AssurancePort` | `backend.app.assurance.engine.AssuranceEngine` |
| existing | `GitInspectionPort` / `VerificationPort` | `GitRepositoryInspector` / `BoundedVerificationRunner` |

All constructors work with no arguments. Each class passes an `isinstance` check
against its `runtime_checkable` port in its own test module.

## Behavior

**Git checkpoints.** `capture` reuses the hardened read-only inspector and returns a
`GitCheckpoint` whose `status_digest` covers identity, HEAD, branch, every path
record, the bounded patch and a content digest of untracked files (which the
patch omits). Time is excluded, so identical states have identical digests.
`compare` reports added/removed/changed paths, head change and branch movement;
`is_current` is the freshness input (a truncated patch is conservatively stale
unless its original limit is supplied). Repositories with no commit are rejected
with `REPOSITORY_HAS_NO_COMMITS`; detached HEAD is `branch is None`.

**Agent Launcher.** `launch` starts exactly one top-level process and is blocking.
Generic, Codex and Claude adapters bind allowed executables; the environment is an
allowlist (requested keys only; `PATH`, `GIT_*`, interpreter-injection keys and
broker-prefixed keys are refused; secret-named keys are refused unless they are
that adapter's own credential variable). Sensitive parent values are redacted from
captured output. Timeout and `stop` terminate the direct child only. `attach`
records declared metadata and never controls or observes anything. Every record
carries `descendant_control_available=False` and an explicit limitation.

**Environment Passport.** Deterministic, sorted, bounded facts: OS, interpreter,
tool versions (absent tools are simply absent), an allowlisted set of variables,
`PATH` and paths as keyed HMAC fingerprints, repository configuration and the
remote host (never its URL). A failed collector yields a `PARTIAL` passport with a
limitation. `compare` returns added/removed/changed/unknown facts and never
attributes cause.

**Dependency Tracker.** Baseline is the checkpoint's HEAD commit, current is the
working tree. Supported: `requirements*.txt`, `pyproject.toml` (PEP 621, PEP 735,
Poetry), `poetry.lock`, `package.json`, `package-lock.json` (v1/2/3). Changed
files in any other ecosystem, and malformed or oversized files, are listed in
`unsupported_ecosystems` rather than guessed. Risk notes cover non-registry
sources, unpinned ranges, downgrades, major bumps, missing lockfiles and
manifest/lock mismatches. Nothing from the repository is executed.

**Assurance.** `discover` reads configuration, recognizes a fixed set of tools
(pytest, ruff, mypy, pip check, and `package.json` scripts that start with jest,
vitest, mocha, `node --test`, eslint, tsc or a known bundler), and selects checks
from Change Contract required checks plus changed-path/dependency evidence.
Unrecognized scripts become coverage gaps, never commands. `run` refuses stale
evidence (checks are `SKIPPED` with the reason). `evaluate` returns
freshness, required-check outcome, coverage gaps and contract deviations
(forbidden path, outside allowed paths, conflict, risk ceiling, dependency and
environment drift) and the four booleans `[SD]` needs for `LifecycleFacts`
(`required_assurance_passed`, `assurance_fresh`, `deviations_resolved`,
`required_evidence_complete`).

## Persistence and orchestration (added after the first handoff)

`backend/app/assurance/store.py` (`EvidenceStore`) writes the `[SD]`-owned
`agent_runs`, `git_checkpoints`, `environment_passports`, `dependency_reports`,
`assurance_plans` and `assurance_runs` tables through the frozen models' JSON, using
`Database` unchanged. Evidence rows are immutable; agent runs are replaced as they
change. Plans are stored as a `{"plan", "contract_sha256"}` envelope so a restarted
process still notices a contract change; read plans only through `EvidenceStore`.

`backend/app/assurance/service.py` (`EvidenceService`) is the whole retained flow
for one Change: `capture_baseline` (refuses to redo a baseline) -> `launch_agent` /
`attach_agent` / `stop_agent` -> `capture_current` (comparison, drift, dependencies)
-> `plan_assurance` -> `run_assurance` -> `evaluate` -> `assurance_facts`. It is
restart-safe: plans are rebound to their persisted checkpoint and contract digest.
`assurance_facts(change)` returns exactly the four `LifecycleFacts` fields `[KB]`
owns (all `False` with a reason when unproven) for `RuntimeLifecycleFacts`.
`AgentLauncher.adapters()` reports adapter metadata and executable availability
without disclosing paths. Rows written here feed `PassportBuilder` unchanged
(verified by a test using `[AC]`'s real builder).

What is left for `[SD]` is only composition: construct `EvidenceService(EvidenceStore(database))`
in `create_app`, add routes, map `AssuranceFacts` into `RuntimeLifecycleFacts`, and
mark the KB capabilities available. `launch_agent` is blocking, so run it off the
request thread.

## Verification

```text
python -m pytest -o addopts=""                       # whole repository
python -m coverage run --branch --source=backend/app/git,backend/app/execution,backend/app/environment,backend/app/dependencies,backend/app/assurance -m pytest backend/tests/git backend/tests/execution backend/tests/environment backend/tests/dependencies backend/tests/assurance backend/tests/kb_flow
python -m coverage report
python -m compileall -q backend
```

- Whole repository (excluding `backend/tests/tui`, which needs the optional
  `textual` extra that is not installed here): **502 passed, 1 skipped** (the opt-in
  Windows Credential Manager test), no regressions.
- `[KB]` suites: **339 passed**, combined statement+branch coverage **98%** across
  the five owned packages (2107 statements, 774 branches). Targets were 90%/85%.
- Real boundaries: disposable Git repositories (staged, unstaged, untracked,
  rename, delete, binary, conflict, detached, unborn, Unicode, spaces); real
  subprocesses for launch/timeout/cancel/output-budget/environment canaries; real
  `git` for environment/dependency reads; a real `pytest` pass and fail; a real
  Node `node --test` pass and fail launched through `npm`; a real SQLite round trip
  of every evidence model.
- End-to-end flows in `backend/tests/kb_flow/test_kb_end_to_end.py` cover
  baseline -> agent edit -> checkpoint comparison -> environment drift ->
  dependency changes -> discovery -> execution -> evaluation -> staleness, a
  failing required check, a forbidden-path violation, a Node change, and
  cancel/attach records. Running checks does not itself make evidence stale
  (bytecode and cache writes are disabled), and a later edit does.

## Contract gaps and decisions for `[SD]`

1. `AgentLauncherPort` carries no actor or idempotency key. Authority must be
   enforced upstream; `launch` blocks, so composition should call it off the
   request thread. The launcher's own records are in memory (bounded to 512);
   `EvidenceService` persists every `AgentRun`, but a run in flight during a restart
   cannot be stopped afterwards (reported as a limitation).
2. `AssurancePort.run` receives no checkpoint. The engine remembers each plan's
   checkpoint and contract digest in memory (bounded to 256). `EvidenceService`
   rebinds persisted plans after a restart via
   `AssuranceEngine.remember(change, plan, checkpoint, contract_sha256)`; without it
   `run`/`evaluate` raise `ASSURANCE_PLAN_UNKNOWN`. `evaluate`, `remember` and
   `analyze_deviations` are additive methods outside the frozen protocol.
3. `EnvironmentDrift` has no expected/unexpected classification. Contract
   comparison is done in deviation analysis using the contract's
   `expected_outcomes` text.
4. The default fingerprint key is a fixed application constant so persisted
   baselines stay comparable. Inject an installation-specific key stored outside the
   database for stronger protection of fingerprinted values.
5. `DependencyPort.scan` reads the current working tree and requires the checkpoint's
   HEAD to still be the repository HEAD (`DEPENDENCY_CHECKPOINT_STALE` otherwise).
6. Windows `.cmd` shims are never executed. `npm`/`npx` are translated to
   `node <npm-cli.js>`; a Codex or Claude install that exists only as a `.cmd`
   shim is reported as not started.

## Limitations (intentional; the four cuts still apply)

- No event journal, process supervisor, filesystem tracker or tool registry:
  no descendant control, attribution or cleanup, no replay, no local-file undo, no
  tool trust. Attach is metadata only.
- Repeated Git reads detect observed movement; they are not an atomic snapshot.
  Active Git content filters and submodules are unsupported. Untracked files are
  covered by a bounded content digest, not by the patch.
- Checks run with the runtime's interpreter and PATH, not a repository virtual
  environment. `npm audit` needs network access and is only selected on Node
  dependency changes.
- Passing checks describe the commands that ran. They are not proof of correctness,
  and dependency risk notes are reviewer inputs, not vulnerability findings.
- Windows and Python 3.14 only; no Linux/macOS, real Codex/Claude agent, or
  interactive terminal smoke test is claimed.

## Earlier hardening (unchanged, still true)

The Git inspector bounds capture memory, suppresses external diff, textconv,
fsmonitor and filter execution, rejects malformed evidence with domain errors, and
checks repeated status/statistics/patch reads for movement. The bounded pipe reader
hashes stdout, terminates only the direct child on timeout, and never inherits
credentials or interpreter-injection variables. `BoundedVerificationRunner`
validates commands and limits and pins Python to the daemon interpreter.

## Consumer action

1. Independently review and add acceptance probes under `backend/tests/acceptance/`.
2. Compose `EvidenceService(EvidenceStore(database))` in `create_app` and add the
   routes (persistence is already done in `EvidenceStore`).
3. Feed `EvidenceService.assurance_facts` into `RuntimeLifecycleFacts` for the four
   assurance facts and mark the KB capabilities `AVAILABLE`.
