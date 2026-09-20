# Roadmap: Sentinel (Change Assurance Runtime)

## Overview

This milestone closes the one remaining gap in Sentinel's "Native Environment Provenance" pillar:
replacing the current restricted-token-only agent launch (a real but modest privilege reduction,
honestly disclosed as such) with a genuine Windows AppContainer sandboxing boundary. The work
proceeds in three delivery boundaries, in the order the highest-risk item in
`PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` §A.5 recommends. First, prove the AppContainer
mechanism actually works without repeating the exact failure that killed the prior Low-integrity
attempt — a launched process that can no longer write to an ordinary repository. Second, harden
that mechanism to be least-privilege by construction, to fail loudly instead of silently degrading
on setup failure, and to describe itself honestly everywhere it is surfaced (API, CLI, TUI,
desktop, Passport). Third — staged as its own dedicated verification pass, not shipped alongside
the build work, per §A.5's explicit recommendation — adversarially prove the boundary holds and
confirm none of the 16/16 closed threat-model findings or the existing test suite regressed. By the
end, Sentinel's launch-authority claim is genuinely, verifiably reduced, not just disclosed as
reduced.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: AppContainer Launch With Preserved Repository Writes** - Agent processes launch under a genuine Windows AppContainer boundary and can still read/write the selected repository, closing the exact gap that broke the earlier Low-integrity attempt
- [ ] **Phase 2: Least-Privilege Scoping, Fail-Loud Errors, and Honest Disclosure** - The AppContainer grants only the capabilities real testing proved necessary, setup failures never silently degrade, and every surfaced claim states exactly what boundary was achieved
- [ ] **Phase 3: Adversarial Verification and Regression Proof** - Adversarial tests prove the boundary is real and the full existing test suite plus all 16/16 threat-model findings remain clean

## Phase Details

### Phase 1: AppContainer Launch With Preserved Repository Writes
**Goal**: A launched agent process runs under a genuine Windows AppContainer boundary (capability
SIDs, package identity, per-resource ACLs), replacing the current restricted-token-only launch,
while ordinary repository reads/writes keep working.
**Depends on**: Nothing (first phase of this milestone) — builds on the existing restricted-token
launch in `execution/process_supervisor.py` (`spawn_restricted_supervised`,
`CreateRestrictedToken(DISABLE_MAX_PRIVILEGE)` + `CreateProcessAsUser`), which stays as the
documented fallback design reference, not the shipped boundary, once this phase lands.
**Requirements**: SBOX-01, SBOX-02
**Success Criteria** (what must be TRUE):
  1. A launched agent process runs inside a genuine Windows AppContainer — a real package SID is
     present on the live process token — not merely a restricted primary token with the caller's
     unchanged integrity level.
  2. The AppContainer is constructed with concrete capability SIDs and explicit per-resource ACL
     grants on the repository path (an ACE naming the AppContainer SID), not a zero-capability
     container that can do nothing.
  3. A real agent command running under the AppContainer boundary can create, edit, and delete
     files in the user-selected repository working tree end to end — the exact failure mode that
     killed the earlier Low-integrity attempt (Low integrity denied ordinary Medium-integrity
     writes) does not recur.
  4. Applying the AppContainer boundary requires no destructive one-time change to the user's
     repository or account (no integrity-label mutation, no repository-wide ACL rewrite) — the
     boundary is applied per-launch, not by altering shared state.
**Plans**: 2 plans
Plans:
- [ ] 01-01-PLAN.md — Genuine AppContainer low-box token (package SID + capability SIDs) and
      additive per-resource repository ACL grant in `spawn_restricted_supervised`, independently
      verified end to end on the live spawned process's own token
- [ ] 01-02-PLAN.md — Wire the AppContainer SID through the full `AgentLauncher.launch()` surface
      (`authority_reduction`), correct the now-stale "integrity level is retained" disclosure, and
      prove the same repository roundtrip plus no-silent-fallback behavior at that layer
**Notes**: Touches `execution/process_supervisor.py` and `execution/launcher.py` (native launch
code), which `AGENT_COORDINATION.md`'s exclusive-path table assigns to `[KB]`. No new contract
fields were needed — both plans reuse the existing `AgentRun.restricted_token_applied`/
`authority_reduction` fields, so `contracts/`/`main.py` (`[SD]`-exclusive) are untouched by this
phase. Any future structured AppContainer disclosure fields remain available for Phase 2.

### Phase 2: Least-Privilege Scoping, Fail-Loud Errors, and Honest Disclosure
**Goal**: The AppContainer boundary proven in Phase 1 is hardened to grant only what real testing
showed necessary, to fail loudly rather than silently fall back when setup fails, and to be
described accurately everywhere it is surfaced.
**Depends on**: Phase 1
**Requirements**: SBOX-03, SBOX-04, SBOX-05
**Success Criteria** (what must be TRUE):
  1. The set of capability SIDs and ACL grants applied to the AppContainer is the minimum needed
     for real agent operation (repository read/write, temp, and whatever else Phase 1's testing
     showed necessary) — no blanket "AllApplicationPackages" or over-broad grant is present, and
     each granted capability corresponds to a demonstrated need.
  2. If AppContainer construction fails for any reason (missing capability, ACL grant failure,
     unsupported Windows version), the launch raises a stable, distinguishable error, and the
     process never launches under a weaker boundary while claiming the stronger one was applied.
  3. Every surface that reports the boundary — API response field, CLI output, TUI copy, desktop UI
     copy, and the Change Passport — states the concrete boundary achieved (e.g. "AppContainer:
     applied, capabilities: [...]") and none of them uses "sandboxed" or "isolated" as an
     unqualified claim.
  4. An operator reading only the CLI or TUI output, without reading source code, can tell whether
     a given run used the new AppContainer boundary or the older restricted-token-only path, and
     cannot mistake one for the other.
**Plans**: TBD
**UI hint**: yes
**Notes**: Inherently cross-owner per `AGENT_COORDINATION.md`'s exclusive-path table: launcher
internals are `[KB]`-exclusive (`execution/`), CLI/TUI/desktop/Passport copy is `[AC]`-exclusive
(`cli/`, `tui/`, `apps/desktop/`, `passport/`), and any new/changed contract fields are
`[SD]`-exclusive (`contracts/`, `main.py`). Coordinate via the claim/handoff protocol rather than
editing outside your own path; do not let this block sequencing.

### Phase 3: Adversarial Verification and Regression Proof
**Goal**: The AppContainer restriction is adversarially proven to be real, and the change
introduces no regression in the existing backend test suite or the 16/16 closed threat-model
findings.
**Depends on**: Phase 2
**Requirements**: SBOX-06, SBOX-07
**Success Criteria** (what must be TRUE):
  1. An adversarial test that attempts to read, write, or execute a resource outside the
     AppContainer's granted capability SIDs and ACLs (e.g. a path never ACL'd for the container, a
     capability never granted) fails, and that failure is observable in the test/evidence output
     rather than silently succeeding.
  2. An adversarial test that attempts to escape or bypass the AppContainer boundary (e.g.
     attempting to re-elevate privileges, spawning a child process outside the job/container) fails
     and is recorded as a failed attempt, not treated as a successful escape or a silent fallback.
  3. The full existing backend test suite (1,022+ tests) passes with the new AppContainer launch
     path in place.
  4. Re-checking the 16/16 threat-model findings in `THREAT_MODEL_FINDINGS.md` against the new
     launch path shows no regression — each previously-closed finding remains closed.
**Plans**: TBD
**Notes**: Per `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md` §A.5, this adversarial pass is
deliberately staged as its own phase rather than shipped alongside Phase 1/2's build work. New
adversarial/regression tests most likely land in `backend/tests/execution/` (matching `[KB]`'s
owner test path) and/or `backend/tests/acceptance/` (`[SD]`-exclusive per
`AGENT_COORDINATION.md`); route accordingly.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. AppContainer Launch With Preserved Repository Writes | 0/2 | Planned | - |
| 2. Least-Privilege Scoping, Fail-Loud Errors, and Honest Disclosure | 0/TBD | Not started | - |
| 3. Adversarial Verification and Regression Proof | 0/TBD | Not started | - |
