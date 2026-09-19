# Multi-Agent Coordination Rules

## Purpose

All contributors work in one shared working tree. These rules prevent concurrent agents from editing the same code, documents, or generated artifacts.

## Required task tag format

Every task, status update, commit, and handoff must begin with one owner tag:

```text
[TAG] short description
```

Use one primary tag per task. A task may name a dependency tag, but two tags must not jointly own the same files.

## Ownership tags

| Tag | Owns | Planned paths |
| --- | --- | --- |
| `[CORE]` | app bootstrap, shared types, storage schema, API contracts | `src/core/`, `src/shared/`, `src/types/` |
| `[EXEC]` | command runner, Git inspection, repository snapshots, event capture | `src/execution/`, `src/git/` |
| `[RECOVERY]` | file-effect model, planning, conflict detection, recovery execution and verification | `src/recovery/` |
| `[UI]` | screens, components, styles, client data hooks | `src/ui/`, `src/components/`, `src/styles/` |
| `[QA]` | fixtures, automated tests, test scripts, demo validation | `tests/`, `fixtures/`, `scripts/` |
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
```

Do not begin work until no active claim overlaps the requested files. A directory claim blocks all files beneath it unless it explicitly lists exceptions.

## Interface-first handoffs

Cross-tag work happens through a written handoff, never simultaneous edits.

```text
[TAG] HANDOFF to [TAG]
Status: ready | blocked
Changed files: <exact list>
Contract: <types, endpoint, event payload, or behavior>
Verification: <command and result>
```

The receiving agent must acknowledge the handoff before relying on it. If a contract must change, its owning tag changes it and emits a new handoff.

## Text and documentation ownership

Only `[DOCS]` edits prose files. Code owners may provide proposed wording in their handoff, but must not directly edit README files, context documents, demo scripts, or other agent-owned text.

UI display copy belongs to `[UI]`; product claims must remain consistent with `PROJECT_CONTEXT.md`. `[DOCS]` reviews public-facing claims before the demo.

## Git hygiene

- Check `git status --short` before editing and before committing.
- Never discard, reset, stash, reformat, or move another agent's changes.
- Keep commits scoped to one owner tag: `[UI] Add change review timeline`.
- Do not amend or rebase another agent's commit.
- Do not edit lockfiles directly; route them through `[INTEGRATION]`.
- Resolve a conflict only if all involved owners have handed it to `[INTEGRATION]`.

## Stop conditions

Stop and report rather than guessing when:

- A needed file has an active claim by another tag.
- A required contract is undefined or conflicts with an existing handoff.
- Work needs a root configuration or dependency change.
- The requested feature expands beyond the prototype scope in `PROJECT_CONTEXT.md`.

## Recommended execution order

1. `[CORE]` creates the project skeleton, durable model, and API contracts.
2. `[EXEC]` and `[RECOVERY]` implement against the agreed contracts in separate directories.
3. `[UI]` builds against stable mock data, then integrates the API after handoff.
4. `[QA]` creates the sample repository and verifies the safe-restore/conflict scenario.
5. `[INTEGRATION]` wires the final application and applies only agreed configuration changes.
6. `[DOCS]` finalizes the demo script and scope disclaimer.

