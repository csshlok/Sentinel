# Requirements: Sentinel (Change Assurance Runtime)

**Defined:** 2026-09-20
**Core Value:** An AI agent's process-tree launch authority must be genuinely, verifiably reduced via a real Windows AppContainer boundary — not just disclosed as reduced via restricted tokens.

## v1 Requirements

Scoped to closing the one remaining gap in "Native Environment Provenance": a genuine Windows
AppContainer sandbox boundary for launched agent processes, replacing/strengthening the current
restricted-token-only launch, without breaking real repository writes (the failure mode that killed
the first attempt).

### Sandboxing

- [ ] **SBOX-01**: Agent processes launch under a genuine Windows AppContainer boundary (capability
      SIDs, package identity, per-resource ACLs), not just a restricted token with unchanged
      integrity level
- [ ] **SBOX-02**: A launched agent process under the AppContainer boundary can still perform
      ordinary reads/writes to the user-selected repository working tree (the exact capability that
      broke under the earlier Low-integrity attempt)
- [ ] **SBOX-03**: The AppContainer boundary is granted only the capability SIDs/resource ACLs an
      agent genuinely needs (repository read/write, temp, and whatever else real testing shows is
      required) — least-privilege by construction, not a blanket allow
- [ ] **SBOX-04**: If AppContainer setup fails (missing capability, ACL grant failure, unsupported
      Windows version, etc.), the launcher fails loudly with a stable error — it never silently
      falls back to an unrestricted or restricted-token-only launch while claiming the stronger
      boundary was applied
- [ ] **SBOX-05**: Every surfaced description of the boundary (API response fields, CLI output, TUI
      copy, desktop UI copy, Change Passport) states exactly what was achieved (e.g. "AppContainer:
      applied, capabilities: [...]") and never uses "sandboxed" or "isolated" as an unqualified claim
- [ ] **SBOX-06**: Adversarial tests demonstrate the AppContainer restriction is real: a launched
      process cannot access resources outside its granted capabilities/ACLs, and an attempt to
      escape or bypass the boundary is observable and fails
- [ ] **SBOX-07**: The full existing backend test suite continues to pass, and the existing 16/16
      threat-model findings remain closed (no regression introduced by the new launch path)

## v2 Requirements

Deferred to a future milestone — real, tracked, not part of this scope.

### TUI Completion

- **TUI-01**: Lifecycle stepper screen in the terminal UI
- **TUI-02**: Git/dependency evidence tables in the terminal UI
- **TUI-03**: Assurance panel in the terminal UI
- **TUI-04**: Contract/delegation forms in the terminal UI
- **TUI-05**: Textual `Pilot` interaction and resize/no-colour tests for screens still missing them

### Desktop/Backend Integration

- **DESK-01**: Bespoke result screens replacing generic views (agent runs, assurance evaluation, delegations/actors, delivery/outcomes, recovery plan/approval, tool detail, forks)
- **DESK-02**: Pickers instead of pasted ids (actor, grant, checkpoint, tool) — needs list endpoints
- **DESK-03**: Expose allowed next lifecycle states so the desktop only offers valid transitions
- **DESK-04**: Installer (NSIS), code signing, app icon/metadata, update policy, release decision

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Docker-backed containerized agent isolation | Implemented and fully reverted this session; product thesis is native-first, not a Docker replacement (proposal §2, §24.1) |
| Low-integrity-level process launch | Tried once, reverted — breaks ordinary Medium-integrity repository writes |
| Linux/macOS execution adapters | Proposal explicitly defers cross-platform enforcement to later generations |
| Cross-agent container/session sharing | Threat-modeled only (Part B of `PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md`), not implemented, not this milestone |
| Filesystem tracker / local-file undo outside Git | Approved cut, unchanged |
| MCP/descendant tool-call interception | Bounded scope, unchanged |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SBOX-01 | Phase 1: AppContainer Launch With Preserved Repository Writes | Pending |
| SBOX-02 | Phase 1: AppContainer Launch With Preserved Repository Writes | Pending |
| SBOX-03 | Phase 2: Least-Privilege Scoping, Fail-Loud Errors, and Honest Disclosure | Pending |
| SBOX-04 | Phase 2: Least-Privilege Scoping, Fail-Loud Errors, and Honest Disclosure | Pending |
| SBOX-05 | Phase 2: Least-Privilege Scoping, Fail-Loud Errors, and Honest Disclosure | Pending |
| SBOX-06 | Phase 3: Adversarial Verification and Regression Proof | Pending |
| SBOX-07 | Phase 3: Adversarial Verification and Regression Proof | Pending |

**Coverage:**
- v1 requirements: 7 total
- Mapped to phases: 7/7 ✓
- Unmapped: 0

---
*Requirements defined: 2026-09-20*
*Last updated: 2026-09-20 after roadmap creation (3 phases, full coverage)*
