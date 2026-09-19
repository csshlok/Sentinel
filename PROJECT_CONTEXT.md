# Change Assurance Runtime - Project Context

## Goal

Build a Windows-first, repository-scoped prototype that makes an AI-assisted coding change observable, reviewable, and safely recoverable. This is a two-day vertical-slice demo, not a production security runtime.

## The demo promise

A developer can select a local Git repository, describe an intended change, run one command or coding-agent session through the app, and then:

1. See what changed in the repository and what command/test evidence was recorded.
2. Review a chronological timeline of the run.
3. Undo supported agent-produced file changes safely.
4. Preserve a later human edit as a recovery conflict instead of overwriting it.

The intended live demo is:

1. Create a Change with an intent statement.
2. Run a controlled command against a sample Git repository.
3. Record command output, exit status, Git state, and file before/after content or hashes.
4. Show the Change Review and Timeline.
5. Manually edit one agent-touched file after the run.
6. Choose Undo: restore safe paths and show the manually edited path as a conflict.

## Required scope

- Local existing Git repository.
- One generic shell-command runner; a Codex wrapper is optional if time permits.
- Durable local Change record and event timeline.
- Repository file create, modify, and delete detection.
- Before/produced/current comparison for recovery.
- Safe recovery for supported local repository file effects.
- Test/build command result captured as evidence.
- A UI with Change list, Change Review, Timeline, and Recovery views.

## Explicit non-goals

Do not implement or imply that this prototype provides:

- A real credential broker, secret storage, or GitHub authorization flow.
- OS sandboxing, Windows Job Object enforcement, or guaranteed process-tree control.
- Full host-machine environment monitoring or recovery.
- MCP/tool supply-chain trust, signing, or policy enforcement.
- Recovery of package installs, external APIs, deployments, CI, or cloud effects.
- Deterministic replay, agent-response replay, or multi-agent execution.
- Cross-platform support.

Unknown or unsupported effects must be shown as unknown/unsupported, never described as safely reversible.

## Product language

Preferred: "repository-scoped Change Assurance prototype", "supported local file recovery", "timeline reconstructed from recorded events".

Avoid: "secure sandbox", "complete rollback", "tracks everything", "guaranteed recovery", or "production-ready runtime".

## Suggested architecture

Keep the system deliberately small and local:

```text
Web UI
  -> Local API/service
       -> Change store (SQLite or simple durable local store)
       -> Command runner
       -> Repository snapshot/reconciliation service
       -> Recovery planner/executor
```

The authoritative recovery rule for each touched file is:

```text
before    = content at Change start
produced  = content immediately after the Change
current   = content when Undo is requested

if current == produced: restore before safely
else:                   report a conflict; do not overwrite current
```

## Core data concepts

- **Change**: id, title/intent, repository path, status, timestamps.
- **Event**: ordered timeline item such as command started, command exited, test result, or file reconciled.
- **File effect**: canonical repository-relative path, operation, before state, produced state, current state, recovery classification.
- **Recovery plan**: safe actions, conflicts, execution result, and verification result.
- **Evidence**: command, stdout/stderr reference, exit code, test/build result, Git baseline/after state.

## Definition of done

The project is ready to demo only when it can complete the six-step demo promise above on a fresh sample repository, including the conflict case. A visually complete UI without verified safe-path recovery is not done.

