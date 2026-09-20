# Sentinel (Change Assurance Runtime)

## What This Is

Sentinel is a Windows-first, local-only "change assurance runtime" that sits between an AI coding
agent and a real Git repository. It launches the agent under real Windows process-tree
supervision, captures Git/environment/dependency evidence before and after it runs, records every
mutation in a hash-chained journal, and produces a signed Change Passport describing exactly what
happened — independently observed, not self-reported by the agent. It ships as a FastAPI backend, a
scriptable CLI, a Textual terminal UI, and an Electron desktop app, all driven from one frozen
OpenAPI contract (66 operations / 61 routes / 110 schemas).

The product is already substantially built: 1,022+ tests passing, a full threat-model review
(16/16 findings closed), and working Change lifecycle, evidence capture, agent launch/supervision,
credential brokering, GitHub PR integration, recovery preview/execute, and Passport export.

## Core Value

An AI agent's process-tree launch authority must be genuinely, verifiably reduced — not just
disclosed as reduced. Today the launcher only disables maximum token privileges while keeping the
caller's integrity level (a real but modest reduction); it is not a sandbox and the product's own
docs are explicit about that gap. Closing that gap with a real Windows AppContainer boundary — the
mechanism the original proposal specifies (§12, §20, §31) — is the one piece of "native environment
provenance" that remains between "meaningfully lowered privilege" and an actual isolation boundary.

## Requirements

### Validated

- ✓ Change lifecycle (DRAFT → ACTIVE → LOCALLY_VERIFIED → REVIEW_READY → RECOVERY_* → FAILED) with
  contract, authority-ceiling, and idempotent mutation API — existing, full backend
- ✓ Git/environment/dependency evidence capture, diffed for drift — existing
- ✓ Top-level agent launch/attach/pause/resume/stop under a kill-on-close Windows Job Object, with
  full descendant-process attribution (PID, image path, command line, lifetime, exit code) —
  existing (Process Supervisor Part A)
- ✓ Restricted-token launch (`CreateRestrictedToken(DISABLE_MAX_PRIVILEGE)` + `CreateProcessAsUser`),
  disclosed everywhere as reduced privilege, never as a sandbox — existing
- ✓ Identity/delegation, default-deny policy engine, credential broker (sole boundary exposing
  durable secrets), GitHub provider with PR create/close and outcome tracking — existing
- ✓ Constrained, non-destructive Git recovery: preview → typed-approval → execute on a dedicated
  branch, conflict-first via temporary worktree — existing
- ✓ Signed Change Passport export (Ed25519) — existing
- ✓ Append-only, hash-chained event/effect journal with end-to-end replay verification — existing
- ✓ API authentication (single-user bearer token), frozen OpenAPI contract with drift-detection test
  — existing
- ✓ CLI covering all backend operations; TUI covering evidence/agent-run/recovery/Passport screens;
  Electron desktop app covering all 66 operations, verified against a real backend and a real
  3-level launched process tree — existing
- ✓ Docker-backed containerized agent isolation was implemented then fully reverted (module, tests,
  contract fields, launcher integration, generated schema all cleanly removed) — this project is
  Windows-native-first, explicitly not a Docker replacement (proposal §2 Principle 3, §24.1)

### Active

- [ ] **SBOX-01**: Agent processes launch under a genuine Windows AppContainer boundary (capability
      SIDs, package identity, per-resource ACLs) instead of (or as a stronger addition to) the
      current restricted-token-only launch
- [ ] **SBOX-02**: The AppContainer boundary does not break real repository writes — the exact
      failure mode that killed the first attempt (Low integrity level denied ordinary
      Medium-integrity writes to a selected repository)
- [ ] **SBOX-03**: Every surfaced claim (API, CLI, TUI, desktop, Passport) states the real boundary
      achieved and never uses "sandboxed" or "isolated" language it hasn't earned (continues the
      "no safety theater" invariant already enforced for the restricted-token boundary)
- [ ] **SBOX-04**: Adversarial tests prove the AppContainer restriction is real and fails loudly
      rather than silently falling back to an unrestricted launch (per proposal §19 "Adversarial
      tests" family — flagged in `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` §A.5 as
      deliberately deferred to its own verification pass)
- [ ] **SBOX-05**: Full repository test suite and the existing threat-model findings remain clean
      after the change (no regression in the 16/16-reviewed threat model)

### Out of Scope

- Docker-backed containerized agent isolation — implemented and fully reverted this session
  (commits `2639a0c` / `5064f13`); the product's own thesis is "native first," explicitly not a
  Docker replacement
- Low-integrity-level process launch — tried once, reverted because it breaks ordinary repository
  writes; superseded by the restricted-token approach and now by the AppContainer approach
- Linux/macOS execution adapters — proposal explicitly defers cross-platform enforcement
  ("Extreme" difficulty, "do not attempt in first release")
- Cross-agent container/session sharing (Part B of `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md`)
  — threat-modeled only, not implemented, not part of this milestone
- Filesystem tracker / local-file undo outside Git — approved cut, unchanged
- MCP/descendant tool-call interception — bounded scope, unchanged
- TUI completion gaps (lifecycle stepper, evidence tables, assurance panel) and remaining
  desktop↔backend integration items (bespoke result screens, pickers, installer/signing) — real
  open items per `HANDOFF.md` / `OVERALL_CONTEXT.md`, but deliberately deferred: this milestone is
  scoped to the AppContainer sandboxing gap only, per explicit user decision

## Context

- This is a hackathon-stage (VTHacks14), pre-release Windows-only project with three-person
  exclusive path ownership (`[SD]`, `[KB]`, `[AC]`) governed by `AGENT_COORDINATION.md`. Any change
  to `execution/`/`main.py`/native launch code should respect that claim protocol if the ownership
  model is still active.
- The authoritative technical spec is
  `Change_Assurance_Runtime_Project_Proposal (2).pdf` — read `§11` (Native Environment Provenance),
  `§12` (Native OS Execution Architecture / Windows G1 process model), `§20` (Security and Threat
  Model), and `§31` (External Technical Foundations — Windows restricted tokens / sandbox process
  capabilities) before implementing.
- The prior AppContainer attempt's failure mode and the exact restricted-token fallback design are
  documented in `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` §A.5 — required reading before
  re-attempting AppContainer; it explains precisely why Low integrity broke writes and what the
  current boundary actually provides.
- `THREAT_MODEL_FINDINGS.md` records the 16-finding attack-surface review (15 fixed, 1 accepted) —
  any new sandboxing work should be checked against it, not treated as a fresh threat model.
- A concurrent, unrelated session/tool left an untracked `brag-output/` directory (launch-video
  material, unrelated to backend work) and a stashed, not-mine README.md truncation
  (`git stash list` → `stash@{0}`). Both were intentionally left untouched pending review; do not
  resolve them as part of this work.

## Constraints

- **Platform**: Windows-only for this milestone — AppContainer, Job Objects, and restricted tokens
  are all Windows-specific primitives; no Linux/macOS parity attempted.
- **Non-destructive Git**: any sandboxing work must not weaken the existing "evidence collectors are
  read-only, only the previewed/approved recovery action mutates a repository" invariant.
- **No safety theater**: the product's core discipline (enforced by prior threat-model review and
  README copy) — new sandboxing claims must be exactly as strong as what's implemented, verified by
  adversarial tests, and never described as more than they are.
- **Ownership**: `execution/`, native launch, and `main.py` composition fall under `[SD]`'s exclusive
  path per `AGENT_COORDINATION.md`, if that coordination model still governs this repo.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Reverted Docker-backed containerized agent isolation entirely | Product thesis is native-first, not a Docker replacement (proposal §2, §24.1) | ✓ Good — clean revert confirmed by tests |
| Rejected Low-integrity-level process launch | Broke ordinary Medium-integrity repository writes in real end-to-end testing | ✓ Good — informs the AppContainer approach to avoid repeating this |
| Shipped restricted-token-only launch (DISABLE_MAX_PRIVILEGE, integrity unchanged) as an interim boundary | Real, honestly-disclosed authority reduction while AppContainer work was deferred | ⚠️ Revisit — this milestone's job is to strengthen it |
| This milestone scopes to AppContainer sandboxing only, deferring TUI/desktop integration gaps | Explicit user decision — those items are lower priority than closing the sandboxing gap | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-20 after initialization*
