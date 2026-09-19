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
