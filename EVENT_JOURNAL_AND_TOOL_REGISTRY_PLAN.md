# Event/Effect Journal and Tool Registry — Reversal Implementation Plan

## 0. Authority and status of this document

`AGENT_COORDINATION.md`'s scope guardrails and `OVERALL_CONTEXT.md`'s "four approved cuts" currently forbid the event/effect journal, the tool registry, and their dependent replay engine. **The user has explicitly reversed that decision for these two subsystems.** The process supervisor and the filesystem tracker remain cut; nothing in this document reopens them, and every design choice below is deliberately bounded by that constraint.

This document is a plan, not an implementation. It contains no code. `OVERALL_CONTEXT.md`, `PROJECT_CONTEXT.md`, `AGENT_COORDINATION.md`, and `BACKEND_IMPLEMENTATION_PLAN.md` are read here for context but are not edited here; Part C §6 lists exactly what must change in each once implementation begins.

Source authority order for this plan, matching the project's own convention: `Change_Assurance_Runtime_Project_Proposal (2).pdf` (product-design authority) → `BACKEND_IMPLEMENTATION_PLAN.md` (existing architecture/execution model this plan must fit) → the current codebase (`backend/app/contracts/`, `backend/app/core/`, and every domain package) → this document (implementation authority for the reversal).

---

## PART A — Event/Effect Journal + Replay Engine

### A.1 Design decision, stated up front

The PDF's Effect model (§4.2) is resource-centric: `filesystem.write`, `dependency.install`, `tool.call`, with `before_digest`/`produced_digest`/`current_digest` and a `restoration_class`. Two of the PDF's four original cuts — the **filesystem tracker** and the **process supervisor** — are **not** reversed by this change. That means the journal cannot honestly emit `filesystem.write` effects (no write interception exists) or `process.spawn` effects (no descendant-process observation exists). Inventing those event types now, backed by nothing but Git diffs and top-level launcher summaries, would be exactly the "safety theater" this project's invariants forbid.

The honest design is therefore: **the Event Journal is a tamper-evident, causally-ordered record of mutations to entities this backend already models** (Change, Delegation, CredentialGrant, GitCheckpoint, EnvironmentPassport, DependencyReport, AssurancePlan/Run, AgentRun, ProviderOperation, Outcome, RecoveryPlan/Action, ToolManifest/ToolTrustDecision — see Part B). Every event type in §A.3 corresponds to a mutation this backend can already prove happened, through code that already exists. Nothing is journaled that the current evidence collectors cannot themselves attest to. `Effect` rows (§A.2) are a narrower sub-concept than the PDF's: a structured before/produced digest transition attached to an event, used only for the subset of resources that already carry a comparable digest today (`GitCheckpoint.status_digest`, `EnvironmentPassport` fingerprints, `DependencyReport` entries, `ChangePassport.canonical_digest`, and the new `ToolManifest.artifact_digest` from Part B). This is a smaller claim than the PDF's generic filesystem/process effect model, and it is stated as such in every user-facing surface (§A.7).

### A.2 Data model

New immutable Pydantic models in `backend/app/contracts/models.py` (frozen, `[SD]`-owned):

```
JournalEventType = StrEnum(  # namespaced, dot-separated, closed set — new members require a contract change
    "change.created", "change.contract_updated", "change.transitioned",
    "change.git_summary_refreshed", "change.legacy_verification_run", "change.deleted",
    "delegation.issued", "delegation.revoked",
    "credential.grant.issued", "credential.grant.revoked", "credential.secret.resolved",
    "git.checkpoint.captured",
    "agent.launched", "agent.attached", "agent.stop_requested", "agent.completed",
    "environment.passport.captured",
    "dependency.report.captured",
    "assurance.plan.created", "assurance.check.completed",
    "provider.pull_request.created", "provider.pull_request.refreshed", "provider.ci_refreshed",
    "outcome.recorded",
    "recovery.plan.created", "recovery.action.completed", "recovery.plan.completed",
    "passport.built",
    "policy.decision.denied",
    "tool.manifest.registered", "tool.trust.decided", "tool.trust.invalidated",
)

JournalEvent {
    id: UUID
    change_id: UUID
    seq: int                       # monotonic PER CHANGE, starting at 1, no gaps among committed rows
    event_type: JournalEventType
    actor_id: UUID | None          # None only for system-internal events (e.g. staleness recompute)
    subject_type: str | None       # e.g. "delegation", "recovery_action", "tool_manifest"
    subject_id: UUID | None
    payload: dict[str, object]     # redacted, bounded (see A.5); JSON-serializable, sorted-key canonical form on disk
    occurred_at: datetime
    prev_event_hash: str | None    # None only for seq == 1 (chain genesis for this Change)
    event_hash: str                # sha256 over the canonical envelope, see A.4
    schema_version: int
}

JournalEffect {
    id: UUID
    event_id: UUID
    change_id: UUID
    resource_type: str             # "git_checkpoint" | "environment_passport" | "dependency_report"
                                    # | "credential_grant" | "recovery_action" | "tool_manifest"
    resource_id: UUID
    before_digest: str | None
    produced_digest: str | None
    restoration_class: str         # "exact" | "conditional" | "compensating" | "stageable" | "none" | "unknown"
}

ReplayTimeline {
    change_id: UUID
    events: list[JournalEvent]
    effects: list[JournalEffect]
    chain_verified: bool
    first_break_seq: int | None    # first seq where event_hash fails to verify, if any
    generated_at: datetime
}

ChainVerificationResult {
    change_id: UUID
    verified: bool
    checked_events: int
    first_break_seq: int | None
    reason: str | None
}
```

`Digest` is the existing type alias already used by `GitCheckpoint.status_digest` / `ChangePassport.canonical_digest` — reused, not reinvented.

### A.3 Tamper-evidence mechanism: per-Change hash chain

This is the 4th independent application of a pattern the codebase already trusts, not a new primitive:

- `backend/app/git/state.py::summary_digest` already hash-chains Git evidence content.
- `backend/app/environment/tracker.py` already uses `hmac.new(..., hashlib.sha256)` for fingerprints.
- `backend/app/passport/builder.py::PassportBuilder.build` already computes a `canonical_digest` over sorted-key JSON.

The journal chain follows the identical canonicalization convention already established in `ChangeService._request_hash` (`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, `hashlib.sha256(...).hexdigest()`):

```
event_hash = sha256(
    prev_event_hash_or_empty_string
    + canonical_json({seq, change_id, event_type, actor_id, subject_type, subject_id, payload, occurred_at, schema_version})
)
```

The chain is **scoped per Change**, not global across the whole database. Rationale: the Change is this product's root object (`OVERALL_CONTEXT.md` §"Product thesis"); a per-Change chain lets every Change be independently verified, exported, and reasoned about without needing the entire database, and lets `[KB]`/`[AC]` emission code stay decoupled from a single global writer lock. The tradeoff — a compromised database could still splice two Changes' histories against each other — is stated explicitly as a limitation in §A.7; it is not claimed as cross-Change tamper evidence, only within-Change.

**Append-only enforcement (defense in depth, matching PDF §20 "Journal tampering: restricted storage + sequence/hash chaining + optional signatures"):**
1. Application code never issues `UPDATE`/`DELETE` against `journal_events` or `journal_effects`.
2. SQLite triggers reject any `UPDATE`/`DELETE` attempt outright:
   ```sql
   CREATE TRIGGER journal_events_immutable_update
     BEFORE UPDATE ON journal_events
     BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END;
   CREATE TRIGGER journal_events_immutable_delete
     BEFORE DELETE ON journal_events
     BEGIN SELECT RAISE(ABORT, 'journal_events is append-only'); END;
   ```
   (mirrored for `journal_effects`). This is the concrete "restricted storage" mechanism — not a comment, an enforced constraint any test can try to violate and watch fail.
3. `event_hash` is verified independently at reconstruction time (§A.6), so even a raw `sqlite3` edit that bypasses the ORM (but not the triggers, which apply regardless of caller) is only possible via direct file-level tampering while the daemon is stopped — and *that* is exactly what `ChainVerificationResult.verified == False` is designed to catch on next read.

### A.4 New tables (migration, `[SD]`-owned)

```sql
CREATE TABLE IF NOT EXISTS journal_events (
    id TEXT PRIMARY KEY,
    change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT NULL,
    subject_type TEXT NULL,
    subject_id TEXT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    prev_event_hash TEXT NULL,
    event_hash TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    UNIQUE (change_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_journal_events_change ON journal_events(change_id, seq);
CREATE INDEX IF NOT EXISTS idx_journal_events_type ON journal_events(change_id, event_type);

CREATE TABLE IF NOT EXISTS journal_effects (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES journal_events(id) ON DELETE CASCADE,
    change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    before_digest TEXT NULL,
    produced_digest TEXT NULL,
    restoration_class TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_effects_change ON journal_effects(change_id, resource_type);

-- append-only triggers as in A.3, on both tables
```

`change_id ... ON DELETE CASCADE` is consistent with every other evidence table in `migration_002_change_runtime_core` (`git_checkpoints`, `assurance_runs`, etc.). This is a deliberate consistency choice, not an oversight: Change metadata deletion in this product already means "delete this Change's evidence," and the journal is Change-scoped evidence. It is flagged explicitly in §A.7 as a limitation (deleting a Change deletes its own tamper-evidence chain along with it — there is no cross-Change audit log surviving Change deletion).

Sequence allocation follows the existing `ChangeRepository` optimistic-concurrency pattern: `SELECT COALESCE(MAX(seq), 0) + 1 FROM journal_events WHERE change_id = ?` computed and inserted inside the same `BEGIN IMMEDIATE` transaction as the underlying mutation (the existing `Database.connection(immediate=True)` context manager already supports this — no new primitive needed). This guarantees no seq gaps among *committed* rows and gives crash-safety: a mutation and its journal row commit or roll back together, atomically, in one SQLite transaction — matching this project's existing "no untested branch may authorize a mutation" and "persistence survives restart" invariants.

### A.5 Redaction and bounding

Non-negotiable, matching the existing invariant ("Never persist raw long-lived credentials in the journal", `BACKEND_IMPLEMENTATION_PLAN.md` §19.4) and the PDF's own §14.2 ("journal records stable digests rather than raw secrets"):

- `credential.secret.resolved` events **never** carry the secret. Payload is `{grant_id, scope, provider}` only — the exact set of fields `CredentialBroker.resolve_secret` already has access to *without* touching `CredentialStorePort.get`'s return value.
- Every payload is passed through the same canary-secret test pattern already used across `[AC]`'s test suites (`backend/tests/providers`, `backend/tests/credentials`): seed a known fake secret value, assert it is absent from `journal_events.payload_json` after any operation that touches it.
- Payload size is bounded (proposed: 8 KiB per event, matching the spirit of the existing `verification_output_limit_bytes`/`patch_limit_bytes` budgets); assurance check output goes into the payload as a **digest** (reusing `hashlib.sha256` on the already-captured `AssuranceRun` stdout/stderr), never the raw bytes a second time — the raw bytes already live in `assurance_runs.payload_json`, so the journal event references them by ID plus digest rather than duplicating storage.
- `environment.passport.captured` events store only the already-redacted `EnvironmentPassport` fingerprints (never re-deriving raw values); `EnvironmentTracker`'s existing `_scrub`/`fingerprint` methods are the only path a value takes before it can reach a journal payload.

### A.6 Every existing mutation point that must emit an event

This is the integration surface. Enumerated by exact file and method against the codebase as it exists today. A shared `JournalWriter` (new `backend/app/core/journal.py`, `[SD]`-owned) is injected via constructor into every owner's existing service/tracker classes — the same dependency-injection pattern already used for `GitInspectionPort`, `VerificationPort`, etc. `JournalWriter.append(connection, change_id, event_type, *, actor_id=None, subject_type=None, subject_id=None, payload=...) -> JournalEvent` takes the **same open `sqlite3.Connection`** the caller's own transaction is already using, so the event row commits atomically with the mutation it describes — no two-phase commit, no separate journal transaction to go out of sync.

**`[SD]`-owned (`backend/app/core/`) — emits directly, since these are already `[SD]`'s files:**

| File / method | Event(s) |
| --- | --- |
| `core/change_repository.py::ChangeRepository.create` | `change.created` |
| `core/change_repository.py::ChangeRepository.update_contract` | `change.contract_updated` |
| `core/change_repository.py::ChangeRepository.transition` | `change.transitioned` (payload: `from_state`, `to_state`, `reason`) |
| `core/change_repository.py::ChangeRepository.update_git_summary` | `change.git_summary_refreshed` (legacy compatibility path only) |
| `core/change_repository.py::ChangeRepository.update_verification` | `change.legacy_verification_run` |
| `core/change_repository.py::ChangeRepository.delete` | `change.deleted` (emitted in the same transaction, immediately before the row delete — since the cascade removes the journal too, this event exists chiefly so a `JournalWriter` unit test can assert emission order, and so any future export-before-delete flow has a final marker) |
| `core/runtime_service.py::ProviderOperationService.create_pull_request` (and any sibling method that calls `PolicyPort.evaluate` and receives a denial) | `policy.decision.denied` (payload: `operation`, `denial_reason`) — every privileged-mutation call site in this file that already checks `PolicyDecision.allowed` gains one `if not decision.allowed: journal.append(...)` line; this is the one event family owned entirely by `[SD]` because the policy-check call sites already live in `[SD]`'s composition file, not in `[AC]`'s `policy/engine.py` (which is a pure function with no DB handle) |
| `core/runtime_service.py::RecoveryService.execute` (composition wrapper around `[AC]`'s `GitRecoveryEngine`) | delegates to the `[AC]` emission in `recovery/git_recovery.py` (below); no duplicate event here |

**`[KB]`-owned (`backend/app/{git,execution,environment,dependencies,assurance}/`):**

| File / method | Event(s) |
| --- | --- |
| `git/state.py::GitStateTracker.capture` | `git.checkpoint.captured` + one `JournalEffect(resource_type="git_checkpoint", before_digest=<prior checkpoint's status_digest or None>, produced_digest=<new status_digest>, restoration_class="none")` — `"none"` because Git checkpoints are read-only observations, not a restorable resource in their own right (the *commits* they observe are restorable, which is what `RecoveryPort` already handles) |
| `git/state.py::GitStateTracker.compare` | none — read-only comparison, not a mutation |
| `execution/launcher.py::AgentLauncher.launch` | `agent.launched` at invocation start; `agent.completed` at terminal status, reusing the **already-existing** `AgentLauncher._notify`/`on_update` hook (`OVERALL_CONTEXT.md` records this hook already exists for `EvidenceService` persistence — the journal call is a second subscriber on the same hook, not new plumbing) |
| `execution/launcher.py::AgentLauncher.attach` | `agent.attached` |
| `execution/launcher.py::AgentLauncher.stop` | `agent.stop_requested`, with the resulting terminal status still reported via the `on_update`-driven `agent.completed` |
| `environment/tracker.py::EnvironmentTracker.capture` | `environment.passport.captured` + `JournalEffect(resource_type="environment_passport", produced_digest=<passport's own composite fingerprint digest>, restoration_class="unknown")` — `"unknown"` per the existing, already-true product claim that environment rollback is unsupported (`PROJECT_CONTEXT.md` "No ... environment rollback") |
| `dependencies/tracker.py::DependencyTracker.scan` | `dependency.report.captured` |
| `assurance/engine.py::AssuranceEngine.discover` | `assurance.plan.created` |
| `assurance/engine.py::AssuranceEngine.run` | one `assurance.check.completed` per `AssuranceRun` produced (payload: `check_id`, `status`, `duration_ms`, `output_digest` — a fresh `sha256` over the already-captured stdout/stderr, not a duplicate copy) |
| `assurance/service.py::EvidenceService.capture_baseline` / `.capture_current` | delegate to the tracker-level emissions above; `EvidenceService` is the actual DB-transaction owner (per `OVERALL_CONTEXT.md`'s own record of `EvidenceStore`/`EvidenceService`), so in practice the `JournalWriter` call happens here, in the same transaction as the `EvidenceStore` write, with the tracker methods staying pure/testable in isolation |
| `assurance/service.py::EvidenceService.launch_agent` / `.attach_agent` / `.stop_agent` | same pattern — `EvidenceService` is where the DB transaction and the launcher call are already composed |
| `assurance/service.py::EvidenceService.plan_assurance` / `.run_assurance` | same pattern |

**`[AC]`-owned (`backend/app/{identity,credentials,providers,outcomes,recovery,passport}/`):**

| File / method | Event(s) |
| --- | --- |
| `identity/repository.py::DelegationRepository` create path (the method backing `POST /api/v1/delegations`, composed in `core/runtime_service.py::IdentityAdminService`) | `delegation.issued` |
| `identity/repository.py::DelegationRepository.revoke` | `delegation.revoked` |
| `credentials/broker.py::CredentialBroker.issue_grant` | `credential.grant.issued` (payload: `provider`, `scopes`, `expires_at` — never the secret) |
| `credentials/broker.py::CredentialBroker.revoke` | `credential.grant.revoked` |
| `credentials/broker.py::CredentialBroker.resolve_secret` | `credential.secret.resolved` (redaction per §A.5 — this is the single highest-risk emission point in the entire plan and gets a dedicated adversarial test, see §C.5) |
| `providers/github.py::GitHubProvider.create_or_refresh_pull_request` | `provider.pull_request.created` or `provider.pull_request.refreshed` |
| `providers/github.py::GitHubProvider.list_check_runs_for_sha` | `provider.ci_refreshed` (lower priority than the other emissions — read-only against GitHub, but still an outbound network call worth a timeline entry per PDF §9.2's "tool/provider request/response hashes when available"; sized into Phase J2 as optional if time-constrained, see §C.4) |
| `outcomes/tracker.py::OutcomeTracker.verify_required_checks` | `outcome.recorded` per `Outcome` produced |
| `recovery/git_recovery.py::GitRecoveryEngine.plan` | `recovery.plan.created` |
| `recovery/git_recovery.py::GitRecoveryEngine.execute` | `recovery.plan.completed`, plus one `recovery.action.completed` + `JournalEffect(resource_type="recovery_action", before_digest=<pre-recovery HEAD>, produced_digest=<post-recovery HEAD>, restoration_class="exact")` per `RecoveryAction` — this is the one event family where `restoration_class="exact"` is honestly claimable, because `GitRecoveryEngine` already verifies the post-recovery digest before returning success |
| `passport/builder.py::PassportBuilder.build` | `passport.built` |

**Reconciliation with `PROJECT_CONTEXT.md`'s existing "Forbidden persistence concepts" list:** `Event` and `Effect` come *out* of that forbidden list (that is the entire point of this reversal). `ProcessTree`, `ResourceVersion`, `BeforeImage`, and `FilesystemSnapshot` **stay forbidden** — no event type above claims filesystem write attribution or process-tree ownership, and `JournalEffect.resource_type` deliberately has no `"file"` or `"process"` member.

### A.7 The Replay Engine

**Concrete definition, chosen and justified against the PDF:** PDF §9.1 lists five replay levels and marks only **Trace replay** — "Reconstruct the timeline exactly from recorded events and evidence" — as G1; the other four (tool-response replay, filesystem replay, controlled execution replay, forked replay) are explicitly G2/G3/G4 in the proposal's *own* roadmap, and the PDF's own dependency structure ties filesystem replay to the filesystem tracker and controlled/forked replay to the process supervisor — both of which **stay cut** in this reversal. `PROJECT_CONTEXT.md`'s existing text ("No causal event/effect timeline, trace replay, or replay engine because the event journal is absent") already frames trace replay as the direct, first-order consequence of the event journal specifically — confirming this was always meant to be a single, bounded increment, not the full five-level replay system.

**Therefore: Replay = deterministic reconstruction and cryptographic verification of a Change's causal timeline from `journal_events`/`journal_effects`, with no re-execution of anything.** It does not run agent commands again, does not reconstruct filesystem state, and does not fork alternate histories. Concretely, `ReplayPort.reconstruct(change_id)` returns a `ReplayTimeline`: every event for the Change in `seq` order, joined with its `JournalEffect` rows, plus `chain_verified` (recomputes every `event_hash` from `seq=1` forward and confirms it matches the stored value and the stored `prev_event_hash` linkage) and `first_break_seq` (the first `seq` where verification fails, surfaced honestly rather than silently trusting a tampered chain). This is exactly the PDF's §9.3 "Debugging UX" table — a selectable timeline where each row exposes input state, actor, authority, output, causal children, and recovery implications — built entirely from data this backend already has once §A.6 is wired.

**New port** (`backend/app/contracts/ports.py`, `[SD]`-owned):
```
class ReplayPort(Protocol):
    def reconstruct(self, change_id: UUID) -> ReplayTimeline: ...
    def verify_chain(self, change_id: UUID) -> ChainVerificationResult: ...
```
Implemented by a new `backend/app/core/replay_service.py::ReplayService` — `[SD]`-owned, because reconstruction reads across every other owner's event types and belongs in the same cross-cutting layer as `core/lifecycle_facts_service.py`.

**New API routes** (`backend/app/core/router.py`, following the existing `/api/v1/changes/{id}/...` convention exactly as named in the PDF's §13 and this codebase's §8-style route families):
- `GET /api/v1/changes/{id}/events` — paginated raw journal (mirrors the existing `GET /changes/{id}/git/checkpoints` pagination pattern), filterable by `event_type`, `since_seq`.
- `GET /api/v1/changes/{id}/replay` — `ReplayTimeline` with `chain_verified`.
- `GET /api/v1/changes/{id}/replay/verify` — `ChainVerificationResult` alone (cheap, for polling/health-style checks).
- `GET /api/v1/changes/{id}/replay/export` — a redacted, self-contained JSON bundle (events + effects + the Change's own summary) for external debugging, matching PDF P7 "Export replay bundle with redacted evidence" — redaction reuses §A.5, so nothing new to invent.

**CLI** (`[AC]`, `backend/app/cli/main.py`, new `events`/`replay` command groups matching the existing `evidence`/`agent`/`assurance` group pattern): `change events show CHANGE_ID [--type] [--json]`, `change replay show CHANGE_ID`, `change replay verify CHANGE_ID`, `change replay export CHANGE_ID --out FILE`.

**TUI** (`[AC]`, new `backend/app/tui/timeline_screen.py` alongside the existing `evidence_screen.py`/`recovery_screen.py` files): a scrollable timeline list (colour-plus-symbol per event family, never colour alone, matching every existing screen's convention), row selection opens a detail pane (actor, authority, payload, causal effect), and a persistent chain-verification badge (`chain_verified` shown honestly — a `False` value is a first-class, clearly rendered state, not hidden).

**Explicit non-goals and limitations (stated in the API `limitations` field pattern this codebase already uses, in Passport output, and in CLI/TUI copy):**

- **No descendant-process attribution in any replay row.** The process supervisor stays cut; `agent.launched`/`agent.completed` events describe only the top-level invocation `AgentLauncherPort` already observes — identical honesty boundary to the existing `AgentRun.descendant_control_available: Literal[False]`.
- **No filesystem-level "what changed" beyond Git.** Replay shows `git.checkpoint.captured` events with their already-existing `GitCheckpoint`/`GitCheckpointComparison` payloads; it does not show a byte-level filesystem write timeline, because the filesystem tracker stays cut.
- **No re-execution of any kind.** Tool-response replay, filesystem replay, controlled execution replay, and forked replay (PDF §9.1's G2-G4 rows) are explicitly out of scope for this reversal. Nothing runs an agent, a test, or a recovery action a second time during replay.
- **No cross-Change tamper evidence.** The hash chain is per-Change (§A.3); a `chain_verified: true` on every Change in a database does not prove the database as a whole has not been selectively edited by deleting whole Changes or inserting a fabricated Change with its own internally-consistent chain. This is stated explicitly, not glossed over.
- **`chain_verified` proves internal consistency, not real-world truth.** A verified chain proves the recorded events have not been edited since they were written; it does not prove the underlying evidence (e.g. a `GitCheckpoint` digest) was itself captured honestly — that assurance already comes from the existing read-only-collector guarantees elsewhere in this codebase, not from the journal.

---

## PART B — Tool Registry + Tool Supply Chain

### B.1 What counts as a "tool" here — the honest scope call

The PDF's §10.1 list (MCP servers, skills/plugins, CLI programs, language-helper packages, local scripts) assumes call-level observation of *everything an agent invokes*, including its descendants. Since the **process supervisor stays cut**, this backend cannot observe or intercept what a launched agent calls once it is running — the same boundary that already makes `AgentRun.descendant_control_available` always `False`.

**Concrete scope for this reversal:** the Tool Registry governs two things this backend *can* actually observe without process supervision:

1. **The top-level executable `AgentLauncherPort` itself resolves and launches** (`execution/launcher.py::_normalize`/adapter resolution already establishes an executable's identity before every launch — this is a filesystem `stat`/read, not process tracking, so it is honestly in scope).
2. **Explicitly declared tool/MCP manifests** — a user or agent can register a manifest by pointing at a config file (e.g. an MCP server's `.mcp.json`-style declaration) or by direct API/CLI input. Reading a declared config file is a filesystem *read* of a static artifact, not an interception of a running process, so it stays inside the existing "read-only collectors" boundary this codebase already relies on for environment/dependency evidence.

**What the registry explicitly does NOT do:** it does not intercept, block, or observe an MCP tool call made by a running agent process, and it does not attribute a specific tool invocation to a specific agent turn. That would require the still-cut process supervisor (to see the descendant process making the call) and/or a wrapping proxy the launched agent is not required to use. This is stated as a non-goal in §B.6, not silently implied away.

### B.2 Data model

```
ToolManifest {
    id: UUID
    name: str
    version: str
    publisher: str | None
    source: str                       # "launcher_executable" | "declared_manifest:<path>" | "registry:<url>"
    artifact_digest: Digest           # sha256 of the resolved executable/manifest file bytes
    signature_state: str              # "valid" | "invalid" | "unsigned" | "unknown"
    capabilities: list[str]           # declared scopes, e.g. "github.repo.read" — cross-referenced against
                                       # actual CredentialGrant.scopes the tool's launches have used (§B.4)
    filesystem_scope: list[str]       # declarative only — the launcher's existing cwd/allowlist, not enforced sandboxing
    network_scope: list[str]          # declarative only, unless/until a real egress collector exists (it does not)
    credential_requirements: list[str]
    trust_state: str                  # "UNKNOWN" | "OBSERVED" | "PROVISIONAL" | "APPROVED" | "DENIED"
    first_seen_at: datetime
    last_seen_at: datetime
}

ToolTrustDecision {
    id: UUID
    tool_id: UUID
    change_id: UUID | None            # None = publisher/version-level policy decision; set = Change-scoped override
    decided_by_actor_id: UUID
    decision: str                     # "APPROVE" | "DENY"
    scope: str                        # "exact_version" | "publisher_policy"
    reason: str | None
    decided_at: datetime
    invalidated_at: datetime | None
    invalidation_reason: str | None   # set automatically on digest/capability drift, see B.5
}

ToolObservation {
    id: UUID
    tool_id: UUID
    change_id: UUID
    agent_run_id: UUID | None
    observed_at: datetime
    capabilities_observed: list[str]  # scopes actually used via CredentialGrant during this run, not just declared
    context: str                      # "launch" | "attach" | "declared_manifest"
}

DriftReport {
    tool_id: UUID
    drifted: bool
    changed_fields: list[str]         # e.g. ["artifact_digest", "capabilities"]
    prior_trust_state: str
    new_trust_state: str
}
```

### B.3 New tables (migration, `[SD]`-owned, applied after the journal migration — §C.1)

```sql
CREATE TABLE IF NOT EXISTS tool_manifests (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    publisher TEXT NULL,
    source TEXT NOT NULL,
    artifact_digest TEXT NOT NULL,
    signature_state TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    filesystem_scope_json TEXT NOT NULL,
    network_scope_json TEXT NOT NULL,
    credential_requirements_json TEXT NOT NULL,
    trust_state TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (name, version, artifact_digest)
);

CREATE TABLE IF NOT EXISTS tool_trust_decisions (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL REFERENCES tool_manifests(id) ON DELETE CASCADE,
    change_id TEXT NULL REFERENCES changes(id) ON DELETE CASCADE,
    decided_by_actor_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    scope TEXT NOT NULL,
    reason TEXT NULL,
    decided_at TEXT NOT NULL,
    invalidated_at TEXT NULL,
    invalidation_reason TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_trust_decisions_tool ON tool_trust_decisions(tool_id, decided_at);

CREATE TABLE IF NOT EXISTS tool_observations (
    id TEXT PRIMARY KEY,
    tool_id TEXT NOT NULL REFERENCES tool_manifests(id) ON DELETE CASCADE,
    change_id TEXT NOT NULL REFERENCES changes(id) ON DELETE CASCADE,
    agent_run_id TEXT NULL,
    observed_at TEXT NOT NULL,
    capabilities_observed_json TEXT NOT NULL,
    context TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_observations_change ON tool_observations(change_id, observed_at);
```

`tool_manifests` is intentionally **not** scoped to a single Change (a tool is observed across many Changes; trust is a property of the tool, echoing PDF §10.3's UNKNOWN→OBSERVED→PROVISIONAL→APPROVED/DENIED lifecycle being per-tool, not per-Change). `tool_trust_decisions.change_id` is nullable specifically to support both a global publisher-policy approval and a narrower one-Change override, matching PDF's tool manifest's `scope: exact_version | publisher_policy` distinction from §10.2-10.3.

### B.4 Signature/attestation representation — honest mechanism, not a placeholder

Because this product is Windows-first (`BACKEND_IMPLEMENTATION_PLAN.md` §5, `PROJECT_CONTEXT.md` "Initial host collectors target Windows"), a real, bounded signature check is achievable: a new small module `execution/signature.py` (`[KB]`-owned, alongside the existing `execution/_process.py` bounded-subprocess helpers) shells out to Windows' built-in `signtool.exe verify /pa <path>` (or, if `signtool` is unavailable, falls back honestly to `signature_state = "unknown"` rather than fabricating "unsigned"). This reuses the exact bounded-subprocess pattern (`shell=False`, argument array, timeout, minimal environment) already proven in `execution/_process.py` — no new subprocess primitive, no new dependency. Non-Windows and missing-`signtool` cases are explicit `UNSUPPORTED`/`unknown` states, matching this project's "no safety theater" invariant rather than claiming coverage that does not exist.

`capabilities_observed` in `ToolObservation` is populated by cross-referencing which `CredentialGrant.scopes` were actually resolved (via `credential.secret.resolved` journal events, §A.6) during the time window of a given `AgentRun` for that tool — giving a real, evidence-backed "observed" capability set distinct from the tool's self-declared manifest capabilities, which is exactly the drift signal PDF §10.3 needs ("Any ... capability change can invalidate prior trust") without requiring process-level call interception.

### B.5 Trust lifecycle and capability-drift detection

Exactly PDF §10.3's state machine: `UNKNOWN -> OBSERVED -> PROVISIONAL -> APPROVED`, with a `-> DENIED` branch reachable from any state by explicit human decision.

- First launch of a previously-unseen `(name, version, artifact_digest)` tuple: `ToolManifest` auto-registers at `UNKNOWN`, immediately advances to `OBSERVED` (an observation exists), and emits `tool.manifest.registered` (§A.6).
- A human/actor decision via `POST /tools/{id}/trust` moves `OBSERVED`/`PROVISIONAL` to `APPROVED` or `DENIED`, recorded as a `ToolTrustDecision`, emitting `tool.trust.decided`.
- **Drift detection**: on every subsequent observation of a tool with an existing `APPROVED` decision, `ToolRegistryService.check_drift` (new, `[SD]`-owned, in `core/tool_registry_service.py`) recomputes `artifact_digest`/`capabilities` and compares against the snapshot the `APPROVED` decision was made against (stored alongside the decision). Any difference sets `trust_state` back to `PROVISIONAL`, stamps `invalidated_at`/`invalidation_reason` on the prior decision, and emits `tool.trust.invalidated` — this is the literal implementation of PDF §10.3's closing sentence and of `BACKEND_IMPLEMENTATION_PLAN.md` §19.1's existing invariant language ("A tool trust decision is invalidated when the artifact digest or declared capability set changes"), which this codebase's `capabilities.py` already carries as dead text under the current cut (`_REMOVED["tool_registry"]`) and which this reversal makes real.
- Default policy (matching PDF's "ordinary reversible work should not trigger approval spam" and this product's existing default-allow-with-visibility stance for non-privileged operations): launching a tool at `UNKNOWN`/`OBSERVED`/`PROVISIONAL` **does not block** — it is visible in the Change Passport and TUI as a flagged risk item. Launching a tool at `DENIED` **is blocked** at `AgentLauncherPort.launch`/`.attach`, returning the same `POLICY_DENIED`-shaped error family already used elsewhere in this codebase, so CLI/TUI/API error handling needs no new branch.

### B.6 Integration with `AgentLauncherPort` / `execution/launcher.py` — `[KB]`-owned

`AgentLauncher.launch` and `.attach` (both already resolve/validate an executable before starting anything, per `_normalize` and the existing adapter-resolution code in `resolve.py`) gain one pre-flight step: resolve-or-register the top-level executable as a `ToolManifest` via an injected `ToolRegistryPort` (new port, §B.7), check `trust_state`, refuse with the policy-denied error if `DENIED`, otherwise proceed and record a `ToolObservation` (`context="launch"` or `"attach"`) once the run's terminal status is known (reusing the same `on_update` hook already used for journal emission in §A.6 — a third subscriber on an existing hook, not new plumbing).

This is deliberately the *only* enforcement point. It governs what top-level agent CLI is allowed to run under this Change; it says nothing about what that agent does once running, which is the honest boundary stated in §B.1.

### B.7 New ports/contracts

```
class ToolRegistryPort(Protocol):
    def resolve_or_register(self, executable_path: str, *, source: str) -> ToolManifest: ...
    def get(self, tool_id: UUID) -> ToolManifest: ...
    def list(self) -> list[ToolManifest]: ...
    def record_observation(
        self, tool_id: UUID, change_id: UUID, agent_run_id: UUID | None,
        capabilities_observed: list[str], context: str,
    ) -> ToolObservation: ...
    def decide_trust(
        self, tool_id: UUID, actor_id: UUID, decision: str, scope: str,
        reason: str | None, change_id: UUID | None,
    ) -> ToolTrustDecision: ...
    def check_drift(self, tool_id: UUID) -> DriftReport: ...
```

### B.8 API routes (exactly the PDF's §13 naming)

- `GET /api/v1/tools` — full registry listing.
- `GET /api/v1/tools/{id}` — one `ToolManifest` with its decision history.
- `POST /api/v1/tools/{id}/trust` — approve/deny (`ToolTrustDecision` body), matching the PDF's route verbatim.
- `GET /api/v1/changes/{id}/tools` — tools observed for one Change (feeds the Change Passport's tool-trust section, and the PDF §30 Passport's "TOOLS" block: `Codex CLI: approved`, `Unknown MCP/skills: 0`, now real instead of a limitations placeholder).

### B.9 CLI/TUI surface

CLI (`[AC]`, matching the existing `agent`/`evidence` group pattern): `tool list [--json]`, `tool show TOOL_ID`, `tool trust TOOL_ID --decision approve|deny --scope exact_version|publisher_policy --reason TEXT`.

TUI (`[AC]`, new `backend/app/tui/tool_trust_screen.py`): a tool list with trust-state badges (colour-plus-symbol, never colour alone — same convention as every existing screen), a detail pane showing capability drift history, and an explicit approve/deny confirmation flow modeled on the existing recovery-confirmation screen (`recovery_screen.py`) — same "preview, then explicit approval" shape already proven for recovery.

### B.10 Explicit non-goals and limitations

- **No interception or blocking of a running agent's actual tool/MCP calls.** Governs only the top-level launched executable and explicitly declared manifests (§B.1). This is the single most important limitation in Part B and is stated in the API `limitations` field, Passport output, and TUI copy every time a tool's trust state is shown.
- **No sandboxing or enforcement of `filesystem_scope`/`network_scope`.** These fields are declarative/observational, feeding risk display, not enforced isolation — enforcement needs OS-level sandboxing (PDF §12, still future work even under the original proposal) and/or the still-cut process supervisor.
- **Signature verification is Windows-Authenticode-only and best-effort.** Non-Windows platforms and tools with no recognizable signature report `signature_state = "unknown"`, never a fabricated "unsigned" or "valid".
- **Capability-drift detection covers declared-manifest and observed-grant-scope changes only**, not arbitrary runtime behavioral drift.
- **A tool's `first_seen_at`/registration is trust-neutral.** Auto-registration at `UNKNOWN`/`OBSERVED` is not an implicit trust grant; only an explicit `ToolTrustDecision` changes enforcement behavior for a `DENIED` tool.

---

## PART C — Cross-cutting

### C.1 Migration ordering

Current `MIGRATIONS` tuple in `backend/migrations/versions.py` ends at `Migration(2, "change_runtime_core", ...)`. This reversal adds, in order:

```
Migration(3, "event_effect_journal", migration_003_event_effect_journal)   # journal_events, journal_effects, triggers
Migration(4, "tool_registry", migration_004_tool_registry)                  # tool_manifests, tool_trust_decisions, tool_observations
```

Migration 3 before migration 4 is a hard ordering requirement, not a convenience: `tool.manifest.registered`/`tool.trust.decided`/`tool.trust.invalidated` (§A.6) are journal event types, so the journal tables must exist before the tool registry's own emission code can be exercised in tests. Both migrations follow the existing additive, idempotent pattern exactly (`CREATE TABLE IF NOT EXISTS`, `_add_column` helper where applicable, no destructive statement, no data loss for existing databases) — `Database.initialize()` requires zero changes; it already walks `MIGRATIONS` in order and applies whatever is new.

### C.2 Ownership

Following the existing exclusive-path model in `AGENT_COORDINATION.md` exactly, with the same "shared core, owner-local emission" split the task frames:

| Path | Owner | What goes here |
| --- | --- | --- |
| `backend/app/contracts/models.py`, `contracts/ports.py` | `[SD]` | `JournalEvent`, `JournalEffect`, `ReplayTimeline`, `ChainVerificationResult`, `ToolManifest`, `ToolTrustDecision`, `ToolObservation`, `DriftReport`; `ReplayPort`, `ToolRegistryPort` (protocol signatures only — `[KB]`/`[AC]` provide concrete `ToolRegistryPort` call sites per their own emission responsibilities, but the port itself, like every other port, is `[SD]`-frozen) |
| `backend/migrations/versions.py` | `[SD]` | Migrations 3 and 4 |
| `backend/app/core/journal.py` (new) | `[SD]` | `JournalWriter` — hash chain computation, sequence allocation, append-only insert helper used by every owner |
| `backend/app/core/replay_service.py` (new) | `[SD]` | `ReplayService` implementing `ReplayPort` — reconstruction/verification reads across every owner's event types, so it lives in shared core exactly like `lifecycle_facts_service.py` already does for cross-cutting reads |
| `backend/app/core/tool_registry_service.py` (new) | `[SD]` | `ToolRegistryService` — manifest storage, trust-decision storage, drift computation (shared orchestration, not domain-specific behavior) |
| `backend/app/core/router.py`, `main.py` | `[SD]` | New routes wired at the declared Gate-3-style integration window, following the existing pattern exactly |
| `backend/app/core/runtime_service.py` | `[SD]` | `policy.decision.denied` emission call sites (§A.6) |
| `backend/app/git/state.py`, `execution/launcher.py`, `execution/signature.py` (new), `environment/tracker.py`, `dependencies/tracker.py`, `assurance/engine.py`, `assurance/service.py` | `[KB]` | All emission call sites listed in §A.6's `[KB]` table; the `AgentLauncherPort` tool-trust enforcement integration (§B.6), since `execution/launcher.py` is the literal tool-launch surface and already `[KB]`'s exclusive path |
| `backend/app/identity/repository.py`, `credentials/broker.py`, `providers/github.py`, `outcomes/tracker.py`, `recovery/git_recovery.py`, `passport/builder.py` | `[AC]` | All emission call sites listed in §A.6's `[AC]` table; `PassportBuilder` gains the replay-summary and tool-trust-summary Passport sections (§A.7, §B.8) |
| `backend/app/cli/main.py`, `backend/app/tui/*.py` | `[AC]` | `events`/`replay`/`tool` CLI command groups; `timeline_screen.py`, `tool_trust_screen.py` TUI screens |

This matches the task's own framing precisely: journal *infrastructure* (schema, writer, hash chain, replay reconstruction) is `[SD]`-owned shared core because it is cross-cutting and touches every domain; journal *emission* stays inside each owner's already-existing mutation methods, via constructor-injected `JournalWriter`/`ToolRegistryPort`, exactly like every other port in this codebase is already consumed.

### C.3 Phased implementation order and sizing

Seven phases. Every phase reuses an existing codebase pattern (digest hashing, DI ports, repository/service split, `on_update` hooks) rather than inventing new engineering — sizing reflects that.

| Phase | Owner | Content | Size | Depends on |
| --- | --- | --- | --- | --- |
| **J0** | `[SD]` | Journal contracts/ports, migration 3, `core/journal.py::JournalWriter` (hash chain, sequence allocation, append-only triggers), unit + contract tests | Small–Medium | none |
| **J1** | `[KB]` | Wire `JournalWriter` into every `[KB]` emission point (§A.6 table); real-boundary + adversarial tests | Medium | J0 |
| **J2** | `[AC]` | Wire `JournalWriter` into every `[AC]` emission point (§A.6 table), including the high-risk `credential.secret.resolved` redaction path; `[SD]` adds `policy.decision.denied` in parallel | Medium | J0 |
| **J3** | `[SD]` core + `[AC]` surface | `core/replay_service.py`, `ReplayPort`, `/events`/`/replay`/`/replay/verify`/`/replay/export` routes ([SD]); CLI `events`/`replay` groups + TUI `timeline_screen.py` ([AC]) | Medium | J1, J2 |
| **T0** | `[SD]` | Tool registry contracts/ports, migration 4, `core/tool_registry_service.py` (storage, drift, trust decisions), `/tools`, `/tools/{id}/trust`, `/changes/{id}/tools` routes | Small–Medium | J0 (tool events need journal tables) |
| **T1** | `[KB]` | `execution/signature.py` (Authenticode check), `AgentLauncherPort` tool-trust enforcement (§B.6), auto-registration/observation wiring | Medium | T0, J1 |
| **T2** | `[AC]` | Passport tool-trust + replay sections, CLI `tool` group, TUI `tool_trust_screen.py` | Small–Medium | T0, T1, J3 |

J1 and J2 parallelize (different owners, no shared files). T1 cannot start before T0 (needs the port/tables) and benefits from J1 already being done (drift/observation emission reuses the same `on_update` hook). No phase is sized **Large**: each is a bounded extension of an already-proven local pattern (this is itself a real finding worth carrying into the phase-sizing conversation — the codebase already has three independent sha256 canonicalization implementations before this plan adds a fourth, and three independent DI-port-plus-owner-local-fake implementations before this plan adds two more).

### C.4 Test strategy per phase

Matches the existing bar in `backend/tests/acceptance/` (black-box, HTTP-level, disposable Git repositories, adversarial/failure-injection) and `backend/tests/kb_flow/` (owner-local real end-to-end flow), not happy-path mocks:

- **J0**: unit tests for `JournalWriter` (canonicalization determinism, sequence allocation under simulated concurrent writers using two connections against the same file, hash-chain linkage across N events). Adversarial: attempt raw `UPDATE`/`DELETE` against `journal_events` directly via `sqlite3` and assert the trigger raises; corrupt one `payload_json` byte directly at the SQLite level between writes and confirm `verify_chain` (once J3 exists) detects it — this specific test is the proof-of-mechanism test in the same spirit as the existing `6ff5a04` "Windows path canonicalization proof tests" commit.
- **J1/J2**: real-boundary tests reusing the existing `backend/tests/kb_flow`-style disposable-repository fixtures — drive a full baseline→launch→checkpoint→assurance→recovery flow through the real API and assert every mutation produced exactly one well-formed, correctly-chained event with the right `event_type`/`subject_id`. Adversarial: canary-secret scan of every `journal_events.payload_json` row after a full flow that issues, resolves, and revokes a credential grant (dedicated test, see §C.5); kill a launched process mid-run and confirm the journal shows a consistent `agent.launched` with no orphaned event on rollback.
- **J3**: acceptance-level test reconstructing a real Change's timeline end-to-end and asserting event order matches actual execution order; a dedicated "tamper detection" acceptance test that directly edits one committed row via raw `sqlite3` (bypassing the app layer, not the trigger — i.e. edits `event_hash` itself, which no trigger can prevent since it's a legitimate-looking value) and asserts `GET /replay/verify` returns `verified: false` with the correct `first_break_seq`; export-bundle round-trip test confirming redaction holds in the exported JSON too.
- **T0**: unit tests for drift computation (digest change, capability-set change, both, neither) and trust-state transition table (every `(current_state, decision)` pair, matching the exhaustive decision-table coverage standard this project already requires for security/policy decisions).
- **T1**: real launcher tests — launch a `DENIED` tool and confirm refusal with no process started; launch an `UNKNOWN` tool and confirm auto-registration + `OBSERVED` + a real journal event; swap the executable bytes between two launches of the "same" declared tool (adversarial supply-chain simulation) and confirm `artifact_digest` drift is detected and prior `APPROVED` trust is invalidated; Windows Authenticode check against both a real signed system binary (e.g. `signtool.exe` itself) and an unsigned test binary, plus a simulated `signtool` absence returning `"unknown"` rather than failing the launch.
- **T2**: Passport golden tests including tool-trust and replay-summary sections across complete/incomplete/denied-tool/drifted-tool Changes; TUI component/snapshot tests for every trust-state badge and the drift-history detail pane, following the existing 80x24/120x30 Pilot test convention.

### C.5 The one test that must exist before anything else ships

A single adversarial test, run against the full flow (grant issue → agent launch using the grant → credential resolve → grant revoke), asserting a known canary secret value appears in **zero** of: `journal_events.payload_json`, application logs, exception text, CLI/TUI rendered output, or the `/replay/export` bundle. This is the direct extension of the existing canary-secret test pattern already used throughout `backend/tests/credentials`/`backend/tests/providers`, applied to the one new surface (the journal) that could otherwise silently reintroduce a secret-leak regression this project has already spent real effort preventing.

### C.6 Required edits to existing context documents (described, not performed)

None of the following are made by this plan. They are the precise edits a later implementation pass must make:

**`AGENT_COORDINATION.md`**, "Scope guardrails" section:
- Remove "Event/effect journal" and "Tool registry" from the bulleted cut list; the list becomes: Process supervisor, Filesystem tracker.
- Change "Stop and report a scope conflict if work introduces those systems, a replay engine, process-tree attribution, local-file snapshots/undo, or tool-trust records" to drop "a replay engine ... or tool-trust records" from the forbidden list, while keeping "process-tree attribution" and "local-file snapshots/undo" as still-forbidden (those remain consequences of the two subsystems that stay cut).
- Add one sentence clarifying the Tool Registry's bounded scope (§B.1) so a future contributor does not assume call-level MCP interception is now in scope.

**`OVERALL_CONTEXT.md`**:
- "Product direction" bullet list: "Event journaling, process supervision, filesystem tracking, and the tool registry are deliberately excluded" → becomes "Process supervision and filesystem tracking are deliberately excluded; the event/effect journal and tool registry are retained in bounded form" (or equivalent), with a pointer to this plan document.
- "Current product scope" §"four approved cuts" → becomes two approved cuts (process supervisor, filesystem tracking/local recovery); the journal/tool-registry/replay consequences language is removed or rewritten to describe what *is* now supported and its explicit limitations (§A.7, §B.10).
- Architecture ASCII diagram gains `Event/Effect Journal`, `Replay`, and `Tool Registry` boxes.

**`PROJECT_CONTEXT.md`**:
- "Approved cuts" section: remove "Event/effect journal and causal timeline" and "Tool registry, MCP inventory, tool manifests, signatures, and trust decisions"; keep the process-supervisor and filesystem-tracker bullets.
- "Necessary consequences and non-goals": remove the "No causal event/effect timeline, trace replay, or replay engine..." and "No tool manifests, signatures, inventory, trust decisions..." bullets; keep the process-supervisor/filesystem-tracker-dependent bullets (descendant-process ownership, uncommitted-file restoration).
- "Product language" → "Do not claim" list: remove "Replay or local-file/environment rollback" (split it — replay is now claimed in its bounded §A.7 form; local-file/environment rollback stays unclaimed) and "Tool or credential trust enforcement" (tool trust is now claimed in its bounded §B.10 form; credential trust enforcement claims are unchanged).
- "Required scope" section gains the bounded journal/replay/tool-registry capabilities, each cross-referenced to this plan's non-goals sections so the boundary stays precise rather than aspirational.

**`BACKEND_IMPLEMENTATION_PLAN.md`**:
- §2 "Scope consequences" table: remove the "Event journal" and "Tool registry" rows (or mark them "Retained (bounded) — see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md`").
- §3.1 "Proposal coverage matrix": flip "Event/effect journal" and "Tool registry/supply-chain trust" rows from `Cut` to `Keep (bounded)`, with owner `[SD]`/`[KB]`/`[AC]` split per §C.2 of this plan; flip "Replay engine" from `Remove as dependency` to `Keep (trace replay only)`.
- §6 "Forbidden persistence concepts": remove `Event`, `Effect`, and `ToolRecord`; keep `ProcessTree`, `ResourceVersion`, `BeforeImage`, `FilesystemSnapshot`.
- §8 "Versioned API": add the `/events`, `/replay`, `/replay/verify`, `/replay/export`, `/tools`, `/tools/{id}/trust`, `/changes/{id}/tools` routes to the listed API surface.
- §9-§11 (person sections): add the new file ownership from §C.2 of this plan to each person's "Exclusive paths" list (`core/journal.py`, `core/replay_service.py`, `core/tool_registry_service.py` under `[SD]`; `execution/signature.py` under `[KB]`; new TUI screens under `[AC]`).
- §19 "Definition of done": item 10 ("Event journal, process supervisor, filesystem tracker, tool registry, and replay are absent from code, storage, API, and claims") must be rewritten to state that process supervisor and filesystem tracker remain absent while the event journal, tool registry, and trace replay are present in their explicitly bounded form — the existing `test_no_removed_subsystem_endpoints_are_exposed` acceptance test (`backend/tests/acceptance/`) needs its assertion list narrowed to `/processes`, `/snapshots`-style filesystem/process routes only, while a new companion test asserts `/events`, `/tools`, `/replay` *are* present (mirroring the existing `test_expected_route_families_are_present` pattern already in the same file).

**`backend/app/core/capabilities.py`** (code, not a context document, but listed here since the plan otherwise leaves it unmentioned and a future implementer will need it): move `"event_journal"`, `"replay"`, and `"tool_registry"` entries from the `_REMOVED` dict to `_RETAINED`, with descriptions rewritten to match §A.7/§B.10's bounded claims exactly; `"process_supervisor"` and `"filesystem_tracker"` stay in `_REMOVED` unchanged.

---

## Summary of what this plan does and does not authorize

This plan authorizes, for a future implementation pass: a per-Change hash-chained event journal covering every mutation this backend's existing entities already model; a trace-only replay engine that reconstructs and cryptographically verifies that journal, with no re-execution; a tool registry covering the top-level launched executable and explicitly declared manifests, with a real (Windows-Authenticode, best-effort) signature check and drift-based trust invalidation; and the narrow enforcement point of refusing to launch a `DENIED` tool. It does not authorize, and explicitly forecloses, anything requiring descendant-process observation or filesystem write interception — those remain the two genuinely still-cut subsystems, and every new capability above states that boundary in its own API/CLI/TUI/Passport output rather than leaving it as an assumption a future contributor has to rediscover.
