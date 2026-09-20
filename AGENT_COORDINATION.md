# Three-Person Coordination Rules

## Purpose

Three contributors share one working tree. These rules give every path one owner, make intersections explicit, and prevent simultaneous code or prose edits.

## Required read order

Before claiming work, read completely:

1. `Change_Assurance_Runtime_Project_Proposal (2).pdf`.
2. `OVERALL_CONTEXT.md`.
3. `PROJECT_CONTEXT.md`.
4. `BACKEND_IMPLEMENTATION_PLAN.md`.
5. `AGENT_COORDINATION.md`.
6. The contracts and tests consumed by the assignment.

The PDF proposal is product-design authority; the context documents and plan record the approved cuts and implementation interpretation. Reading a summary is not a substitute for reading the proposal. Before the first claim, `[KB]` and `[AC]` submit the comprehension statement required by plan section 12.3 and wait for `[SD]` acknowledgement. Report conflicts before editing.

## Permanent people and tags

| Person | Tag | Role | Exclusive paths |
| --- | --- | --- | --- |
| Person 1 | `[SD]` | Independent verification, shared contracts/core, migrations, integration, release acceptance | `backend/app/contracts/`, `backend/app/core/`, `backend/app/main.py`, `backend/migrations/`, `backend/tests/acceptance/`, root configuration, OpenAPI snapshots, context/plan documents |
| Person 2 | `[KB]` | Git evidence, agent launcher, environment/dependency tracking, assurance | `backend/app/git/`, `execution/`, `environment/`, `dependencies/`, `assurance/`, matching unit tests |
| Person 3 | `[AC]` | Identity, policy, credential broker, GitHub/outcomes, recovery, Passport, CLI, terminal UI, and the desktop application | `backend/app/identity/`, `policy/`, `credentials/`, `providers/`, `outcomes/`, `recovery/`, `passport/`, `cli/`, `tui/`, `apps/desktop/`, matching owner unit/contract tests |

No additional implementation tag creates a fourth owner. `[INTEGRATION]` is a temporary activity led by `[SD]`, not a separate person or permission to edit arbitrary files.

`frontend/` is reserved for the deferred **browser** UI and remains unassigned/frozen; nothing in this document reopens it. The user-facing terminal UI is active work owned exclusively by `[AC]` under `backend/app/tui/`; terminal presentation tests stay in `[AC]`'s matching test path until `[SD]` adds independent acceptance coverage.

`apps/desktop/` is a separate, distinct thing from `frontend/`: an Electron desktop application consuming the backend's HTTP API, built by the `[AC]` contributor on a local, unpushed `frontend` branch (see `HANDOFF.md` at the repo root for its current state and the integration checklist). Recorded here as `[AC]`-owned per that handoff's own request, superseding any conflicting ownership note in a document local to that branch (e.g. its own `FRONTEND_PLAN_ADDENDUM.md`, which this repository does not otherwise have access to). `[KB]` has no claim on `apps/desktop/`; `[KB]`'s own `execution/`, `git/`, `environment/`, `dependencies/`, `assurance/` surfaces are consumed by it exactly as any other API client would consume them, through the same frozen contracts every other caller uses.

## Root files and documentation

Root configuration, dependency manifests, lockfiles, OpenAPI snapshots, and Markdown context are single-editor resources owned by `[SD]` during declared integration windows.

- `[KB]` and `[AC]` submit requested dependency/configuration/doc wording in a handoff.
- `[SD]` applies the accepted change after checking for active claims.
- Implementation-history entries use the actual contributor tag and timestamp even when `[SD]` transcribes them.
- No contributor reformats or rewrites another owner's prose or paths incidentally.

## Claim before edit

Post this before changing files:

```text
[TAG] CLAIM
Work item: P1.2 | P2.4 | P3.3
Goal: <one concrete result>
Files: <exact paths or one owned directory>
Interfaces consumed: <names and versions>
Interfaces provided: <names and versions>
Context read: proposal PDF plus all four repository context/coordination documents
Proposal comprehension acknowledged by `[SD]`: <reference>
Expected handoff: <recipient and gate>
```

A directory claim includes its descendants. Do not start if a claim overlaps or if an uncommitted change exists in the target path without a documented owner.

## Exclusive-edit rule

- Edit only paths assigned to your permanent tag.
- A one-line import, generated client, formatting pass, test fixture, or copy change is still an edit and follows ownership.
- Never use a broad formatter over another owner's path.
- Never repair another owner's defect directly. Return a reproducible failing test or exact evidence to that owner.
- The only exception is a declared `[SD]` integration window after every affected owner hands off and stops editing the shared target.

## Contracts and intersections

`[SD]` owns shared contracts and signatures. `[KB]` and `[AC]` consume them and own their concrete implementations. `[SD]` also verifies every submitted implementation independently before integration.

Required intersection order:

1. `[SD]` proposes/finalizes contract and contract tests.
2. Both consumers acknowledge the version or request a change in writing.
3. Concrete work proceeds independently.
4. Provider emits a handoff with tests and limitations.
5. `[SD]` wires backend composition in a declared integration window.
6. `[SD]` freezes the accepted OpenAPI snapshot for the deferred UI phase.

An owner must not change a consumed contract silently. Use:

```text
[TAG] CONTRACT CHANGE REQUEST to [SD]
Contract/version: <name>
Reason: <specific blocked behavior>
Proposed compatible change: <shape>
Affected consumers/tests: <list>
```

## `[SD]` verification protocol

Every `[KB]` and `[AC]` handoff receives an independent review before integration:

1. Confirm the diff contains only claimed, owned paths.
2. Trace every new behavior to a frozen requirement and contract.
3. Run the owner's unit/contract tests from a clean state.
4. Inspect security, privacy, error, timeout, concurrency, idempotency, and data-migration boundaries.
5. Add black-box or adversarial tests under `backend/tests/acceptance/` where owner tests do not prove the boundary.
6. Check that removed capabilities are neither implemented nor implied.
7. Record `ACCEPT`, `ACCEPT WITH NON-BLOCKING FINDINGS`, or `REJECT` with evidence.

A rejected handoff returns to its owner. `[SD]` must not patch the owner's feature files, lower a test expectation, or broaden a contract to hide the defect. Resubmission includes the regression test added by the owner.

## Handoffs

```text
[TAG] HANDOFF to [TAG]
Work item: <plan ID>
Status: ready | blocked
Changed paths: <exact list>
Contract/version: <name/hash>
Behavior and limitations: <facts>
Verification: <commands and results>
Consumer action: <next step>
```

The receiver acknowledges before integration. A handoff transfers an interface, not permanent path ownership.

## Integration locks

At Gates 2 through 6 in the plan, `[SD]` posts a review or integration lock naming exact paths and participating handoffs. Owners stop edits to those paths until `[SD]` posts the result. `[SD]` may add independent black-box tests under `backend/tests/acceptance/`, but does not repair `[KB]` or `[AC]` feature code. Integration commits contain only accepted wiring, shared core/contracts, migrations, root configuration, and composition-level conflict resolution; defects return to their permanent owner.

## Scope guardrails

The product implements the PDF proposal except for:

- Process supervisor — reversed to the PDF's original scope (Windows Job Object process-tree
  supervision, descendant-process attribution, orphan cleanup, and restricted-token authority
  reduction), per `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part A. This supersedes the
  earlier top-level-only narrowing in `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A, which
  remains in effect for pause/resume specifically (still top-level-PID-only) alongside the wider
  process-tree work. Not reversed: any claim of a formal sandbox, namespace/mount isolation, or
  OS-level virtualization — restricted-token authority reduction is meaningfully lowered privilege,
  never described as "sandboxed" or "isolated" in any surfaced copy.
- Filesystem tracker — still cut, unchanged.
- Cross-agent container sharing (an external party receiving and acting on a Change's evidence or
  execution state) — **not implemented, threat-model only.** See
  `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` Part B. Do not claim this capability exists,
  is planned for a specific release, or is "coming soon" in any surfaced copy until Part B's open
  questions are resolved and a separate, reviewed Part C build plan exists.

Stop and report a scope conflict if work introduces local-file snapshots/undo (filesystem tracker) or any cross-agent/cross-machine access (Part B) without a Part C plan. Do not hide them under alternate names. Git checkpoints, aggregate top-level execution results, environment passports, dependencies, assurance results, provider outcomes, constrained Git/provider recovery, the per-Change event/effect journal, trace-only replay, the bounded tool registry (top-level launched executable plus declared manifests only, no MCP/descendant-call interception), agent pause/resume, real process-tree supervision and descendant attribution, restricted-token authority reduction, checkpoint-based Change forking, incremental (poll-based, TUI-only) live agent output, and signed Passport export all remain in scope. See `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` for the journal/replay/tool-registry boundary, `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` for the pause/resume, forking, and live-capture boundary, and `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` for the process-tree-supervision and signed-export boundary (Part A) and the cross-agent-sharing threat model (Part B, unimplemented).

## Git hygiene

- Run `git status --short` before editing, before pulling, and before committing.
- Preserve all unrelated changes; never reset, discard, stash, move, or reformat another person's work.
- Commit one coherent work item with the permanent tag: `[KB] Add environment passport comparison`.
- Do not amend, rebase, or force-push another person's commits.
- Pull/rebase only when the shared working tree is clean and no integration lock is active.
- Lockfiles are generated in an `[SD]` integration window, never hand-edited.
- Record test commands and results in the handoff and context log.

## Failure and stop conditions

Stop before editing when:

- A claim or integration lock overlaps the target.
- The required contract is absent, ambiguous, or incompatible.
- The task requires another owner's path.
- A migration could lose existing user data.
- A credential could enter logs, SQLite, API payloads, or an agent environment.
- Product behavior would imply a removed capability.

When stopped, provide the exact path, interface, error, and owner needed. Do not broaden your claim to work around the block.

## Completion standard

An item is ready for handoff only when implementation, unit tests, failure behavior, security boundaries, user-visible status, and documentation wording agree. Passing tests alone do not authorize claims of process attribution, complete observation, safety, replay, or full local recovery.
