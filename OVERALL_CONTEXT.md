# Change Assurance - Overall Context

## Document role

This is the stable, product-level context for the repository. It explains why the product exists, the long-term system boundary, the language we use, and the engineering principles that should survive individual implementation phases.

`PROJECT_CONTEXT.md` is the operational context for the current two-day prototype. It may narrow this document, but it must not silently contradict it. `BACKEND_IMPLEMENTATION_PLAN.md` describes the current backend execution plan. `AGENT_COORDINATION.md` governs ownership and collaboration.

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

The long-term root object is a **Change**: a persistent record connecting intent, actors, effects, evidence, authority, and outcomes.

## Long-term product direction

The complete Change Assurance Runtime may eventually include:

- Change lifecycle and evidence records.
- Native process and file-effect observation.
- Conflict-aware local recovery.
- Environment provenance.
- Scoped agent identity and credential brokering.
- Tool provenance and trust decisions.
- Trace replay and debugging.
- Git, pull-request, CI, artifact, and deployment continuity.

These are future architectural directions, not claims about the current prototype.

## Current product slice

The current build is intentionally narrower: a local Git-based Change Review prototype. It records intent, reads the selected repository's current Git working tree, runs one approved verification command, and presents evidence for human review.

The following systems are explicitly cut from the current implementation:

- Event/effect journal.
- Process supervision and descendant attribution.
- Filesystem tracking, snapshots, recovery, and undo.
- Tool registry and tool trust.
- Credential broker.
- Environment provenance.
- Replay.

The current coding agent operates outside the app. Git is the sole source of code-change information.

## Product invariants

### Evidence must be real

User-visible status comes from the backend or is labeled unavailable. Do not hardcode healthy, safe, verified, complete, or ready states. A demo fixture may create real state, but the UI must still obtain that state through the same API used in normal operation.

### Observation must not be described as enforcement

Reading a Git diff is not filesystem attribution. Running a command is not process supervision. A passing test is not proof of correctness. The product must state what it observed and what remains unknown.

### Local-first behavior

The prototype operates against a repository chosen by the user and exposes a loopback-only API. Core review functionality must not require a cloud account, hosted database, or external provider.

### Selected repositories are user data

Inspection code must be read-only. The backend must not reset, clean, checkout, stage, commit, or otherwise mutate the selected repository. The only exception is behavior caused by a verification command the user explicitly requests; that boundary must be documented rather than hidden.

### Contracts are authoritative

Shared request, response, and error contracts are versioned coordination points. Implementations conform to contracts; they do not invent private variations. A contract change requires an explicit handoff and consumer review.

### No safety theater

Unsupported capability is shown as unsupported. Missing evidence is shown as missing. Errors are not converted into optimistic statuses. The system must not imply assurance it did not establish.

### Deterministic review logic

Given the same Change metadata, Git state, and verification result, the backend must return the same classifications and review state. Classification and state rules belong in pure, tested functions wherever possible.

## CML working standard

This project must use the same context discipline and implementation standard expected from CML:

- Stable overall context is separated from the current implementation slice.
- Scope cuts and non-goals are explicit and enforced in code review.
- User-visible states are backed by real application data, not placeholder success values.
- Interfaces are defined before parallel implementation.
- Each subsystem has one owner and an explicit handoff contract.
- Integration happens at planned gates, not through overlapping edits.
- Tests verify behavior at module boundaries and through the real end-to-end path.
- Empty, loading, failure, and unsupported states are first-class behavior.
- Product copy reflects actual capability and avoids aspirational claims.
- A feature is complete only when implementation, tests, error handling, and user-visible state agree.

The available local CML export contains application UI and an audit, but not the canonical CML project-context or overall-context documents. If those canonical documents are added to the workspace, `[DOCS]` must compare their structure and update this context system without weakening the project-specific scope decisions above.

## Core vocabulary

- **Change**: the user's intent and the review evidence attached to one repository task.
- **Working-tree change**: a path reported by Git relative to the current HEAD.
- **Verification**: one explicitly requested test or build command and its final result.
- **Evidence**: Git or verification data returned by the backend.
- **Review state**: a deterministic summary of available evidence, not a correctness score.
- **Ready for human review**: changes exist and the latest verification passed; a human still decides whether to accept them.

## Current architecture boundary

```text
External coding agent or developer
              |
              v
       Local Git repository
              ^
              | read-only Git inspection
              |
Web UI -> Local API -> Change store
                    -> Git adapter
                    -> One-shot verification runner
```

No current component sits between the coding agent and the operating system.

## Quality bar

Backend work is acceptable only when:

- Inputs are validated at the boundary.
- Errors have stable codes and safe messages.
- Paths with spaces and Windows path behavior are tested.
- Subprocesses use argument arrays and do not invoke a shell.
- Output and execution time are bounded.
- Persistence survives restart.
- Tests cover success, empty, failure, timeout, and malformed-input states.
- The end-to-end demo uses a real temporary Git repository and real API calls.
- No final demo screen depends on mock data.
- Documentation matches actual behavior.

## Decision authority

- This file owns stable product principles and long-term vocabulary.
- `PROJECT_CONTEXT.md` owns the active release scope.
- An implementation plan owns task sequencing but cannot expand scope.
- API contracts own integration behavior once frozen.
- Tests own demonstrated acceptance behavior.

Changing a stable product invariant requires an explicit decision recorded by `[DOCS]` and acknowledged by `[CORE]`, `[UI]`, and `[QA]`. Scope may be reduced in `PROJECT_CONTEXT.md`; expanding it requires revising the plan and ownership map before implementation.

## Completion principle

The product is not complete because a happy-path screen renders. It is complete when real state flows through the actual backend, boundaries are honest, failures are legible, tests demonstrate the promised behavior, and every visible claim is supported by evidence.

