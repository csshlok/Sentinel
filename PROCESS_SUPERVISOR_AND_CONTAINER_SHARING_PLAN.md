# Process Supervisor Reversal + Signed Export + Cross-Agent Container Sharing

## 0. Authority and status of this document

`AGENT_COORDINATION.md`'s scope guardrails and `PROJECT_CONTEXT.md`'s "Approved cuts" currently
forbid the process supervisor beyond one narrow exception already granted:
`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A reversed only top-level suspend/resume of the
single launched process. **The user has now explicitly reversed the process-supervisor cut more
broadly**, asking for real process-tree supervision to be restored to the scope the original
proposal specified (`Change_Assurance_Runtime_Project_Proposal (2).pdf` §6, §12, §17 P1, §20,
§27), plus a new capability the proposal never specified: signed, portable export of a Change's
evidence, and (as a separate, higher-risk idea) a way for an external agent to receive and act on
a shared "container" of that evidence.

This document has two different kinds of content, deliberately not the same maturity level:

- **Part A** is an implementation plan, ready to build, following this repository's established
  reversal precedent (`EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md`,
  `LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md`). It restores real process-tree supervision and adds
  signed Passport export.
- **Part B is a threat model only, not an implementation plan.** The user asked to begin
  threat-modeling cross-agent container sharing now, in parallel with Part A, explicitly *before*
  committing to a design. Nothing in Part B is authorized for implementation by this document; a
  separate Part C build plan is required after Part B's open questions are resolved.

The filesystem tracker remains cut. Nothing in this document reopens it, macOS/Linux support, or
any claim beyond what is stated as in-scope below.

Source authority order, matching this project's own convention: `Change_Assurance_Runtime_Project_Proposal (2).pdf`
→ `BACKEND_IMPLEMENTATION_PLAN.md` → the current codebase → this document.

---

## PART A — Process Supervisor Reversal (real process-tree supervision)

### A.1 Exact scope, stated up front

The proposal's Process Supervisor component (§6: "Track child processes, resource use,
termination, orphan cleanup," initial form "Windows Job Objects") was cut entirely at project
start, then narrowed (not reversed) to top-level-only suspend/resume by
`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A. This part reverses the cut for real: every
descendant process of a launched top-level agent is tracked, attributed back to the Change, and
terminated on demand — matching the proposal's own non-negotiable, restated at §27 G1 Acceptance
Criteria: *"All descendant processes are either attributed or explicitly marked unattributed with
reason."*

**What changes:** a Windows Job Object owns every process tree a launch starts (§12.1); every
descendant PID is enumerated, resolved to an executable path/command line, and attributed to the
`AgentRun`; the top-level process (and, where feasible, its descendants) run under an
authority-reduced token (§12, §20: "restricted tokens/AppContainer where appropriate"); recovery
can terminate a Change-owned process tree on Undo (§27); and a Change Passport can be
cryptographically signed for export (new — not in the original proposal, added because the richer
evidence this part produces is exactly what is worth exporting first).

**What does not change:** the filesystem tracker stays cut (no before/after file-content tracking
beyond existing Git checkpoints); no macOS/Linux; no claim of a full sandbox (a lowered-integrity
restricted token is a meaningfully reduced privilege set, not namespace/mount isolation — this
project has never claimed Docker-equivalence and the proposal explicitly says it shouldn't, §2
Principle 3, §24.1).

### A.2 Data model

```
AgentRun gains:
    descendant_control_available: bool   # was Literal[False]; now True when supervised by a Job Object
    descendant_processes: list[DescendantProcess] = []

DescendantProcess (new):
    pid: int
    parent_pid: int | None
    executable_path: str | None          # None when resolution failed -- disclosed, not guessed
    command_line: str | None             # redacted the same way stdout/stderr already are
    started_at: datetime
    terminated_at: datetime | None
    exit_code: int | None
    attributed: bool
    attribution_reason: str | None       # populated when attributed=False
```

`descendant_control_available` flipping from `Literal[False]` to `bool` is a real, honesty-critical
model change: every existing limitation string and test asserting unconditional `False` must be
updated to reflect that supervision is now real when a Job Object is in use, and only `False`
falls back to the pre-existing honest disclosure when it is not (e.g. `attach`, which still
observes nothing).

### A.3 `execution/process_supervisor.py` (new, `[KB]`-owned)

Windows Job Object bindings via `ctypes`, matching the established pattern
(`credentials/windows_store.py`'s `advapi32.dll` binding, `execution/signal_control.py`'s
`ntdll.dll` binding):

```python
def create_job() -> int:                         # CreateJobObjectW, then
                                                    # SetInformationJobObject(..., JobObjectExtendedLimitInformation,
                                                    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
                                                    # -- the whole tree dies if this handle is ever closed
                                                    # (process or thread crash), which is the orphan-cleanup
                                                    # guarantee the proposal asks for, enforced by the OS
                                                    # rather than by our own cleanup code running successfully.

def assign_process(job: int, pid: int) -> None:   # AssignProcessToJobObject -- called immediately after
                                                    # CreateProcess, before the child can spawn anything,
                                                    # to avoid a race where an early grandchild escapes the job.

def list_pids(job: int) -> list[int]:             # QueryInformationJobObject(JobObjectBasicProcessIdList)

def terminate_job(job: int) -> None:              # TerminateJobObject

def close_job(job: int) -> None:                  # CloseHandle
```

Polling (`list_pids` on the same cadence as the existing output-capture loop), not a completion
port. Windows' "correct" answer for job-object notifications is
`SetInformationJobObject(JobObjectAssociateCompletionPortInformation)` with an I/O completion port,
which is lower-latency and more correct under load, but adds real complexity (a completion-port
read loop on its own thread) for a benefit (a few hundred ms of attribution latency) this project
does not need yet. Documented here as a known, deliberate first-pass simplification and a natural
future upgrade — not silently permanent.

For each newly observed PID, resolve identity via `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`
+ `QueryFullProcessImageNameW` (narrow-privilege handle, matching this codebase's established
least-privilege convention for every other process handle it opens) and, where obtainable, the
command line. A PID that disappears before it can be resolved is recorded with
`executable_path=None`, `attributed=False`, `attribution_reason="process exited before identity could be resolved"`
— disclosed, never guessed.

### A.4 `execution/launcher.py` wiring

- `launch()` creates a Job Object before spawning, assigns the top-level process to it
  immediately, and polls `list_pids` alongside the existing `capture()` read loop (same thread,
  same cadence — no new thread).
- On completion, close the Job Object (which the `KILL_ON_JOB_CLOSE` flag turns into the orphan
  -cleanup guarantee) and do one final `list_pids` call to prove no descendant PID was left
  unaccounted for; if the OS ever disagrees (should not happen given
  `KILL_ON_JOB_CLOSE`, but the proposal's own honesty bar requires checking, not assuming), record
  it as an explicitly unattributed, not silently dropped, entry.
- `AgentRun.descendant_control_available = True` whenever a Job Object was successfully created
  and assigned; `False` on the (rare, disclosed) path where Job Object creation itself fails, with
  a limitation string explaining why — mirroring the existing `AGENT_PAUSE_UNSUPPORTED` honesty
  pattern rather than silently claiming supervision that did not happen.
- `stop()`/`pause()`/`resume()` continue to act on the top-level PID only for suspend/resume
  (Part A of the prior plan is unchanged), but `stop()` now additionally calls `terminate_job()` so
  a stop request actually cleans up the whole tree, not just the direct child — closing a real gap
  the pre-reversal `DESCENDANT_LIMITATION` string used to disclose as a known limitation.

### A.5 Restricted execution authority (highest implementation risk in this plan)

The proposal's "restricted tokens/AppContainer where appropriate" (§12, §20, §31) is the piece
most likely to be gotten subtly wrong in a way that *looks* like a security boundary but is not —
exactly the failure mode this project's "no safety theater" principle exists to prevent (PDF §2
Principle 6; every prior reversal in this codebase has been careful to disclose partial claims
honestly rather than overstate them).

First-pass scope, stated as a bounded claim: `CreateRestrictedToken` on a duplicate of the
launching process's own token, lowering the integrity level via
`SetTokenInformation(TokenIntegrityLevel)` to Low, and launching the top-level process with
`CreateProcessAsUser` using that token instead of the current plain `subprocess.Popen`. This is
**meaningfully reduced privilege** (a Low-integrity process cannot write to Medium-or-higher
-integrity objects under Windows Mandatory Integrity Control, cannot inject into non-Low
processes, and a browser-class attacker researching Windows sandboxing would recognize this as a
real, load-bearing restriction) but it is **not a full AppContainer** (no capability SIDs, no
package identity, no per-resource ACL) and **not a sandbox** in the Docker/namespace sense (no
filesystem or network isolation). Every surface that reports this (API response, CLI/TUI copy)
must say exactly this — "reduced privilege via a low-integrity restricted token," never
"sandboxed" or "isolated."

Explicit follow-up required before this piece can be called done: **adversarial testing**, per the
proposal's own §19 test family ("Adversarial tests: Agent attempts to escape supervision or invoke
untrusted tools"). A restricted-token launch that silently fails to restrict anything meaningful
(e.g. because a needed capability was accidentally left on the token, or `CreateProcessAsUser`
silently fell back to unrestricted spawn on a permission error) must fail loudly, not launch
unrestricted while claiming otherwise. This is the one piece of Part A I would stage as its own
dedicated verification sub-phase rather than shipping alongside A.3/A.4 in the same pass.

### A.6 Process-tree-aware recovery

`recovery/git_recovery.py` (or a new sibling module, `[KB]`-owned since it consumes
`execution/process_supervisor.py`) gains: on `execute()`, if the Change has a Job Object handle
still open in this process's memory (the launcher's own in-memory state — does not survive a
restart, same honestly-disclosed limitation already accepted for `AgentLauncher._runs`),
`terminate_job()` it before/alongside the Git-native revert, and report
`processes_terminated: int` in the recovery result, matching the proposal's Target Passport
("3/3 child processes terminated," §30). Explicitly disclosed: this can only terminate a tree this
same process instance launched and is still tracking; a tree from before a restart cannot be
recovered this way (same class of limitation the existing `stop_agent` restart case already
discloses).

### A.7 Signed Passport export (added now, per the user's explicit choice, ahead of any
cross-agent sharing design)

- New `passport/signing.py` (`[AC]`-owned, alongside the rest of `passport/`): generate an Ed25519
  keypair for "this operator" on first use, persisted via the existing
  `WindowsCredentialStore`-backed credential store (reusing the precedent rather than inventing new
  key storage), never exported in plaintext by any route.
- `sign(passport: ChangePassport) -> SignedPassportExport` — signs the canonical JSON bytes
  (`model_dump_json` with sorted keys, matching the existing hash-chaining canonicalization
  convention already used for `journal_events`) with the operator's private key.
- `SignedPassportExport { passport: ChangePassport, signature: str, signer_public_key: str, signed_at: datetime }`.
- New route: `POST /changes/{id}/passport/export` → `SignedPassportExport` (reuses the existing
  `/passport` build/read path, adds signing).
- New route: `GET /identity/signing-key` → this operator's own public key, so it can be handed to
  a future verifier out of band (email, a paste, a QR code — transport is not this project's
  concern).
- A `verify(bundle, expected_public_key) -> bool` function ships alongside `sign`, proven by a real
  round-trip test, but is not itself exposed as an API surface — the recipient of an export is,
  by definition, not us.
- **Explicit non-goal for this sub-part:** no other party's public key is stored, trusted, or
  looked up anywhere in this codebase yet. This is "we can sign what we already export," nothing
  about a second party's access to anything. That is Part B.

### A.8 Journal + migrations

- New `JournalEventType`: `AGENT_DESCENDANT_OBSERVED`, `AGENT_DESCENDANT_TERMINATED`,
  `AGENT_PROCESS_TREE_TERMINATED` (recovery-driven), `PASSPORT_EXPORT_SIGNED`.
- Migration N: `descendant_processes` table (`agent_run_id`, `pid`, `parent_pid`,
  `executable_path`, `command_line`, `started_at`, `terminated_at`, `exit_code`, `attributed`,
  `attribution_reason`), FK to `agent_runs(id) ON DELETE CASCADE` matching the existing evidence
  -table pattern.
- Migration N+1: no schema change — `SignedPassportExport` is computed on demand from existing
  `ChangePassport` data plus a key that lives in the credential store, not a new table; listed for
  changelog completeness matching the `agent_run_pause_fields` precedent.

### A.9 Explicit non-goals for Part A

- No claim of a formal sandbox or OS-level isolation boundary (namespaces, containers, VMs).
  "Reduced privilege," never "isolated" or "sandboxed," in any surfaced copy.
- No filesystem-level before/after tracking beyond existing Git checkpoints (filesystem tracker
  stays cut).
- No macOS/Linux.
- No cross-machine or cross-agent sharing of anything (Part B, unimplemented).
- No claim that restricted-token authority reduction has been adversarially verified until the
  dedicated A.5 verification sub-phase actually runs and passes.

### A.10 Ownership (per `AGENT_COORDINATION.md`'s exclusive-path table)

| Path | Owner | What goes here |
| --- | --- | --- |
| `contracts/models.py`, `contracts/ports.py` | `[SD]` | `DescendantProcess`, `AgentRun.descendant_processes`/`descendant_control_available` widening, `SignedPassportExport`, new `JournalEventType` members |
| `migrations/versions.py` | `[SD]` | `descendant_processes` table migration |
| `core/router.py`, `main.py` | `[SD]` | New routes: `passport/export`, `identity/signing-key` |
| `execution/process_supervisor.py` (new), `execution/launcher.py`, `execution/_process.py` | `[KB]` | Job Object supervision, descendant attribution, restricted-token launch |
| `recovery/git_recovery.py` or a new sibling | `[KB]` (consumes `[KB]`'s own new supervisor module) | Process-tree-aware recovery |
| `passport/signing.py` (new), `passport/service.py` | `[AC]` | Signing/verification, key generation via the existing credential store |
| `cli/`, `tui/` | `[AC]` | CLI/TUI surfacing of descendant lists, restricted-execution disclosure copy, export command |

### A.11 Test strategy

- A real subprocess that spawns a real grandchild (e.g. `cmd /c start /wait ...` or a small
  Python helper that itself launches another Python process) — assert both PIDs are attributed,
  both terminate when the top-level is stopped, and the Job Object's `KILL_ON_JOB_CLOSE` guarantee
  actually holds (kill the *launcher process's own reference* and confirm the OS, not our code,
  cleans up).
- A real restricted-token launch attempting an action a normal child could do but a Low-integrity
  process cannot (e.g. writing to a Medium-integrity-protected location) — assert it is refused by
  the OS, not merely "assumed" refused.
- Recovery: a real Change with a still-running supervised process tree; call recovery `execute()`;
  assert the tree is actually gone (poll for the PIDs, not just check a return value) and
  `processes_terminated` matches reality.
- Signed export: sign a real `ChangePassport`, verify it with the correct public key (passes),
  verify it with a different key (fails), tamper one byte of the passport JSON after signing
  (fails) — proving the signature is actually checking content, not just present.

---

## PART B — Cross-Agent Container Sharing: Threat Model (not an implementation plan)

### B.1 What is actually being proposed

The operator's own words: an agent's actions/tool calls get "containerized," an outside agent can
"get that container and run it," gated by a public/private keypair exchange so "only the correct
person has access." Decomposed into concrete claims:

1. Something beyond a Passport gets bundled ("containerized") — evidence plus enough state to
   "run."
2. A party outside this operator's local trust boundary receives that bundle.
3. That outside party can "run" — meaning *something* executes, somewhere, using that bundle.
4. Access is gated by asymmetric cryptography: each party has their own keypair; only public keys
   are exchanged.

Claim 4's mechanism, corrected (see the reply that accompanied this document): sign with your own
private key so a holder of your public key can verify authenticity; encrypt to the recipient's
public key so only their private key can open the payload. Both parties keep their own private key
secret forever; only public keys are ever exchanged. This is a solved, composable pattern (PDF §2
Principle 7: "existing standards should be composed, not reinvented") — likely a hybrid scheme
(e.g. age or PGP-style: encrypt payload with a random symmetric key, encrypt that key to the
recipient's public key, sign the whole envelope with the sender's private key), not a new protocol.

### B.2 The one fact that changes everything about scope: which direction does "run" go?

This is the single highest-leverage open question, and nothing past this point can be scoped
safely without an answer:

- **Direction 1 — they run it on their machine.** We export a portable bundle (evidence +
  environment passport + Change Contract + maybe a recipe: "here is the repo state, toolchain
  versions, and dependency lockfile this Change started from"), signed and encrypted to them. They
  use it as a *reference* to reproduce a comparable environment on their own hardware and continue
  independently. This is not fundamentally different in kind from sharing a signed Docker image
  digest or a `pyproject.toml` plus a lockfile — the risk is bounded to "we disclosed evidence and
  environment fingerprints to a party we chose to trust with a decryption key." No code of theirs
  ever runs on our machine; no code of ours ever runs on theirs beyond what a Change Passport
  already contains.
- **Direction 2 — we run something of theirs, or they act on our machine.** An outside agent
  gains the ability to drive, resume, fork, or otherwise act on a live process on *our* machine
  using *our* authority. This is remote code execution granted to an external party, gated only by
  possession of a key. This is categorically different from every threat this product has modeled
  so far (PDF §8.1's entire threat model is about *our own* agent misusing *our own* delegated
  authority — never about a second, external principal acting on our machine at all) and would be
  the single highest-risk feature this codebase has ever added, by a wide margin over the
  Windows-process-supervisor work in Part A.
- **A third, hybrid direction** is also possible and worth naming: we host something (a paused
  Change, a forked branch of it) and grant a *time-boxed, narrowly scoped* remote capability to
  inspect or step through it — read-only or step-approval-gated, never raw shell/file access. This
  would need its own capability model on top of the existing `Delegation`/`CredentialGrant`
  machinery, extended to a non-local principal for the first time.

**This document does not choose between these.** Direction 1 is a bounded, natural extension of
work already planned in Part A.7 and could reasonably follow the same reversal-plan process this
repository already uses. Direction 2, as literally described, would need a threat model and review
at least as rigorous as the original credential-broker design (PDF §8) before a single line of
code — and arguably contradicts the proposal's own stated identity ("the moat is not a sandbox,"
§24.1; "native first," §2 Principle 3) if it makes the product's core promise "we grant strangers
execution on your machine" rather than "we help you supervise your own agent."

### B.3 Assets

- **Change evidence** (Passport, journal, checkpoints, environment passport, tool trust decisions)
  — already redacted of raw secrets, but reveals repository structure, toolchain fingerprints, and
  business logic if shared broadly. Sensitivity: moderate, bounded by existing redaction.
- **Live execution state** (a running/paused `AgentRun`, its PID, its ability to be resumed or
  forked) — if this is ever reachable by an external principal, sensitivity is severe: pausing,
  resuming, or forking someone's real running agent is direct interference with their machine.
- **Signing/encryption keys** (Part A.7's operator key, plus any new per-sharing keypair) —
  compromise lets an attacker forge provenance or read anything encrypted to that key.
- **The local repository and filesystem** — must never become reachable by an external principal
  under any version of this feature without a separate, explicit, later decision. Not in scope
  here under any interpretation.

### B.4 Actors and the trust-boundary problem

Every actor this codebase currently models (`Actor { kind: human | agent | process | tool | service }`,
`Delegation`) is **locally rooted** — created by, and only meaningful within, this one operator's
own database, under this one operator's own authority chain (PDF §8.2: `Human identity -> Change
authorization -> Agent actor -> ...`). An "outside agent" has no such record and, under the
current model, cannot be reasoned about at all — there is no scope, no expiry, no revocation
mechanism that applies to a principal our `identity` module has never seen.

This means any version of Part B needs a genuinely new concept — an **external principal**,
identified only by a public key we did not issue and do not control the lifecycle of — bolted onto
a model that has never had to reason about anyone outside a single local identity chain. This is
the real complexity center of the feature, independent of which execution direction (B.2) is
chosen.

### B.5 Attack scenarios and candidate mitigations (not yet a design — a checklist any future
design must answer)

| # | Scenario | Candidate mitigation, pending direction (B.2) |
| --- | --- | --- |
| 1 | Direction ambiguity is never resolved and code ships that quietly does Direction 2 while believed to be Direction 1 | Direction must be an explicit, named field/mode in any future contract, never implicit; loudly reject an attempt to use Direction-2-shaped capabilities under a Direction-1 export |
| 2 | Recipient's private key leaks; attacker impersonates the recipient | Time-boxed validity + explicit revocation list, mirroring `Delegation.expires_at`/`revoked_at` exactly |
| 3 | Our own signing key leaks; attacker forges "this came from us" | Key stored only in the existing OS-protected credential store (never on disk in plaintext, never in the journal); a documented, tested rotation path |
| 4 | Shared bundle is replayed after the sharing operator intended it to have expired | Every export carries an explicit `expires_at`; a verifier that ignores it is a defect, tested as such |
| 5 | Shared bundle unintentionally carries brokered credential material | Explicit exclusion, enforced by a real test that constructs a Passport containing credential-shaped data and asserts none of it survives into the signed export |
| 6 | A dispute later arises about what was actually shared and when | Reuse the existing journal hash-chaining: emit `PASSPORT_EXPORT_SIGNED` (already in Part A.8) with the exported content's own digest, so the journal is independently checkable evidence of exactly what left the building |
| 7 (Direction 2/3 only) | External principal uses a legitimately-issued capability to do more than intended (e.g. asked for read-only inspection, actually gets pause/resume/fork) | A capability model at least as narrow as today's `CapabilityScope` strings, evaluated by the same default-deny `PolicyPort` machinery already governing every other operation — no new, parallel authorization path invented for this one feature |
| 8 (Direction 2/3 only) | External principal's own compromised environment is now a pivot point into ours | This is the scenario that makes Direction 2 categorically different from everything else in this codebase; no mitigation short of "never grant raw execution, only narrowly scoped, individually-authorized operations identical in shape to what `PolicyPort` already enforces for local agents" makes this safe, and even that requires far more scrutiny than this document can give it |

### B.6 Open questions requiring a product decision before any Part C build plan

1. **Direction (B.2)** — this is the blocking one. Everything else is drafting until this is
   answered.
2. If Direction 1: what, precisely, goes in the bundle beyond the existing signed Passport (A.7)?
   Environment passport and Contract are natural (already redacted); does anything else belong?
3. If Direction 2 or 3 is ever pursued: does an external principal get its own row in a
   (necessarily new) table, separate from the existing locally-rooted `actors` table, or does the
   `Actor` model itself need widening to represent a principal we did not create? This is a
   contract-level decision (`[SD]`'s domain) that should not be made incidentally inside a feature
   build.
4. Key transport: how does a public key actually reach the other party the first time (out of
   band, by design — but "out of band" needs at least a documented recommendation so users do not
   improvise something worse, e.g. pasting a key into an unencrypted channel next to the very
   secret it is meant to protect access to).
5. Revocation UX: mirroring `Delegation.revoked_at` is easy at the data layer; what does the
   *operator* actually do, concretely, when they want to cut off a party they previously shared
   with? Needs a CLI/TUI action before this can be called complete, not just a database column.

### B.7 Explicit non-goals until Part C exists

- No code. No routes. No new tables. No key-exchange implementation. This document is the
  threat model only, per the user's explicit choice to threat-model now and design later.
- No claim anywhere in product copy that cross-agent sharing exists until it does.
- Direction 2/3 in particular must not be implied as "coming soon" in any user-facing surface
  until B.6.1 is answered and a dedicated Part C plan — reviewed with the same rigor as this
  section — exists.
