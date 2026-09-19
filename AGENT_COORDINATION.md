# Multi-Agent Coordination Rules

## Purpose

All contributors work in one shared working tree. These rules prevent concurrent agents from editing the same code, documents, or generated artifacts.

## Required context read order

Before claiming work, every agent must read:

1. `OVERALL_CONTEXT.md`.
2. `PROJECT_CONTEXT.md`.
3. The implementation plan governing its task.
4. This coordination document.

The agent's claim must state that these documents were read. If they conflict, the agent stops before editing and reports the exact conflict.

## Required task tag format

Every task, status update, commit, and handoff must begin with one owner tag:

```text
[TAG] short description
```

Use one primary tag per task. A task may name a dependency tag, but two tags must not jointly own the same files.

## Ownership tags

| Tag | Owns | Planned paths |
| --- | --- | --- |
| `[CORE]` | backend app, lightweight Change model, persistence, shared contracts, API routes | `backend/app/main.py`, `backend/app/core/`, `backend/app/contracts/`, `backend/tests/core/` |
| `[GIT]` | read-only Git inspection and path classification | `backend/app/git/`, `backend/tests/git/` |
| `[VERIFY]` | one-shot verification command validation and execution | `backend/app/verification/`, `backend/tests/verification/` |
| `[UI]` | screens, components, styles, client data hooks | `src/ui/`, `src/components/`, `src/styles/` |
| `[QA]` | backend integration fixtures, end-to-end tests, demo validation | `backend/tests/integration/`, `backend/fixtures/`, `scripts/` |
| `[DOCS]` | Markdown documentation, demo script, architecture notes | `*.md`, `docs/` |
| `[INTEGRATION]` | dependency upgrades, configuration, final wiring, merge-conflict resolution | root config files only, after notifying affected owners |

If the final project structure differs, the first `[CORE]` agent must update this table before other work begins.

## Exclusivity rule

An agent may edit only files under its assigned tag's paths. No agent may change another tag's owned file, including a one-line import, copy change, formatting pass, or comment, unless the current owner explicitly hands it off in writing.

Root-level files (`package.json`, lockfiles, build configuration, `.gitignore`) are owned by `[INTEGRATION]`. Other agents request required dependency/configuration changes; they do not make them.

## Claim-before-edit protocol

Before reading deeply, editing, or generating files, an agent must post a claim in the shared task channel or issue tracker:

```text
[TAG] CLAIM
Goal: <one concrete outcome>
Files: <exact files or directory>
Interfaces consumed: <API/type names, if any>
Interfaces provided: <API/type names, if any>
Context read: OVERALL_CONTEXT.md, PROJECT_CONTEXT.md, <implementation plan>, AGENT_COORDINATION.md
```

Do not begin work until no active claim overlaps the requested files. A directory claim blocks all files beneath it unless it explicitly lists exceptions.

## Interface-first handoffs

Cross-tag work happens through a written handoff, never simultaneous edits.

```text
[TAG] HANDOFF to [TAG]
Status: ready | blocked
Changed files: <exact list>
Contract: <types, endpoint, response payload, or behavior>
Verification: <command and result>
```

The receiving agent must acknowledge the handoff before relying on it. If a contract must change, its owning tag changes it and emits a new handoff.

## Text and documentation ownership

Only `[DOCS]` edits prose files. Code owners may provide proposed wording in their handoff, but must not directly edit README files, context documents, demo scripts, or other agent-owned text.

UI display copy belongs to `[UI]`; product claims must remain consistent with `PROJECT_CONTEXT.md`. `[DOCS]` reviews public-facing claims before the demo.

`OVERALL_CONTEXT.md` contains stable product context. `PROJECT_CONTEXT.md` contains the active slice. `[DOCS]` must keep those layers separate and may not copy temporary implementation details into overall context.

## Git hygiene

- Check `git status --short` before editing and before committing.
- Never discard, reset, stash, reformat, or move another agent's changes.
- Keep commits scoped to one owner tag: `[UI] Add change review summary`.
- Do not amend or rebase another agent's commit.
- Do not edit lockfiles directly; route them through `[INTEGRATION]`.
- Resolve a conflict only if all involved owners have handed it to `[INTEGRATION]`.

## Stop conditions

Stop and report rather than guessing when:

- A needed file has an active claim by another tag.
- A required contract is undefined or conflicts with an existing handoff.
- Work needs a root configuration or dependency change.
- The requested feature expands beyond the prototype scope in `PROJECT_CONTEXT.md`.

In particular, stop if a task introduces an event journal, process supervision, filesystem tracking/snapshots, recovery, or a tool registry. Those systems have been explicitly cut.

## Recommended execution order

1. `[INTEGRATION]` creates root configuration and the backend package skeleton during a declared bootstrap window.
2. `[CORE]` freezes contracts; `[GIT]` and `[VERIFY]` acknowledge them before implementation.
3. `[CORE]`, `[GIT]`, and `[VERIFY]` work in parallel in their exclusive paths.
4. `[CORE]` wires handed-off adapters; adapter owners fix defects only in their own paths.
5. The `[VERIFY]` owner switches to `[QA]` after handing off verification and runs integration/demo tests.
6. `[UI]` integrates only after the API handoff; `[DOCS]` finalizes product claims and the demo script.

The detailed backend ownership, contracts, handoff gates, and schedule are defined in `BACKEND_IMPLEMENTATION_PLAN.md`.
