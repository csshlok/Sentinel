# Threat Model Findings — Change Assurance Runtime

Status as of 2026-09-19, against `master` @ `a73c9bc` (merge of SD's finding-fix commits with
AC's `5b257c0`). Produced by a full attack-surface review (credential broker,
identity/delegation/policy, tool registry/execution/journal/replay, recovery/passport/CLI/API
auth boundary), cross-checked against the actual source, not just docs, and reconciled against
SD's own parallel audit fixes landed during the same window.

**Owner tags follow `AGENT_COORDINATION.md`'s exclusive-path table.** Findings are grouped by
owner so each person can pick up their own section without cross-editing another owner's path.
Per that doc's rule, **do not repair another owner's defect directly** — hand back a
reproducing test/finding instead, unless you are that owner.

Legend: 🔴 Open | ✅ Fixed | ➖ Closed (accepted design, not a bug)

---

## Summary

| # | Finding | Owner | Status |
|---|---|---|---|
| 1 | `issue_grant` has no delegation/policy gate | **SD** | ✅ Fixed (`8225190`) |
| 2 | GitHub PAT exposed via CLI argv | **AC** | ✅ Fixed |
| 3 | Change deletion destroys the journal | **SD** | ✅ Fixed (`884dba1`) |
| 4 | `OutcomeService.refresh` has no actor binding | **SD** | ✅ Fixed (`b2ea9c6`) |
| 5 | Delegation creation has no grantor validation | **SD** | ✅ Fixed (`b2ea9c6`) |
| 6 | `revoke_grant` broker TOCTOU | **SD** | ✅ Fixed (`8225190`) |
| 7 | Risk-based approval gate is dead code | **AC** (engine) / **SD** (call sites) | ✅ Fixed (`3126190`) |
| 8 | Case-sensitive forbidden-path matching | **AC** | ✅ Fixed |
| 9 | Tool identity collision, `(name, version)` key | **SD** | ✅ Fixed (`4e1e00b`) |
| 10 | TOCTOU between trust-check hash and execution | **KB** | ✅ Fixed (by AC, in KB's path) |
| 11 | Naive substring-only secret redaction in captured output | **KB** | ✅ Fixed (by AC, in KB's path) |
| 12 | API bearer token file has no restrictive permissions | **SD** | ✅ Fixed (`8b4ec65`) |
| 13 | Recovery execution not bound to fresh HEAD | **AC**(engine)/**SD**(fixed it) | ✅ Fixed by SD |
| 14 | `approval_token` not a real credential | **AC** | ➖ Closed, by design |
| 15 | Legacy `/verify` had no authorization, leaked daemon env | **SD** | ✅ Fixed by SD |
| 16 | Mutation + journal write not atomic (identity/credential/recovery) | **SD** | ✅ Fixed by SD (partial — KB emission points explicitly still open, see below) |

**Net: 15 of 16 closed, 0 open, 1 accepted-by-design.** The one residual gap is not a numbered
finding of its own: #16's fix was explicitly scoped to `core/runtime_service.py` only, and the
KB-owned journal-emission points it named as still non-atomic
(`git/state.py`, `execution/launcher.py`, `environment/tracker.py`, `dependencies/tracker.py`,
`assurance/service.py`, plus `ProviderOperationRepository.create`) have not been revisited since.
That is real remaining work, just not tracked as its own numbered row here.

**Scoped for KB (investigated, not implemented):** the actual gap is concentrated in
`assurance/service.py`'s `EvidenceService`, not spread evenly across the five named files. It has
roughly 10 separate journal-emission call sites (`_journal_checkpoint_captured`,
`_journal_environment_captured`, `_journal_dependency_report_captured`, plus several direct
`_journal_append` calls for agent/assurance runs), each paired with a *different* prior write
through `assurance/store.py`'s `EvidenceStore` (e.g. `save_checkpoint`, `save_environment`). None
of those `EvidenceStore` methods currently accept an optional `connection`, unlike
`DelegationRepository.create`/`CredentialGrantRepository.create` etc., which SD's #16 fix already
threads a shared connection through. Closing this properly means: (1) adding an optional
`connection: sqlite3.Connection | None = None` parameter to each relevant `EvidenceStore` write
method (mirroring `Database.connection_or`'s existing pattern), then (2) wrapping each
write+journal pair in `assurance/service.py` in one `database.connection(immediate=True)` block,
same shape as `IdentityAdminService.create_delegation`. This is a real multi-method refactor
across two files, not a one-line fix per call site — sized similarly to SD's original #16 commit,
just on KB's side of the codebase. `execution/launcher.py`'s only journal-adjacent call
(`_record_tool_observation`) already defensively swallows persistence exceptions rather than
raising, so it may not need the same treatment; `git/state.py` and `environment/tracker.py`
themselves emit no journal events directly (their journaling happens through
`assurance/service.py`, already covered above) — the five-file list in #16's commit message is a
slight over-scoping of where the actual call sites live.

**KB follow-up — done, with one real caveat found along the way.** `EvidenceStore.save_agent_run`,
`save_checkpoint`, `save_environment`, `save_dependency_report`, `save_plan` and `save_runs` all
now accept an optional `connection` via `Database.connection_or`. `EvidenceService` wraps each
write+journal pair in one `database.connection(immediate=True)` block exactly as scoped, for:
`capture_baseline` (checkpoint + environment), `capture_current` (checkpoint + environment +
dependency report), `copy_checkpoint_baseline` (checkpoint), `plan_assurance` (plan), and
`run_assurance` (runs, batched with their per-run journal events). Verified atomic with a real
`_ExplodingJournal` double (`backend/tests/assurance/test_service_atomicity.py`, mirroring
`test_runtime_service_atomicity.py`'s pattern): a journal failure now rolls back all of these.

**Found while implementing, not originally scoped: `launch_agent`/`attach_agent`/`pause_agent`/
`resume_agent` cannot be made atomic this same way.** `AgentLauncher` persists every state
transition of a run -- including the terminal one -- through `on_update`, bound at
`EvidenceService.__init__` directly to `store.save_agent_run` with no connection parameter. Each
`_notify` call inside `launcher.launch()`/`.pause()`/`.resume()` therefore commits its own separate
transaction *before* `EvidenceService` regains control, so by the time these four methods reach
their own `save_agent_run` + journal-append pair, the row is already durably saved regardless of
what the journal append does next. Wrapping that final pair in a shared transaction (tried first,
reverted) is cosmetic: it re-writes an already-committed row and provides no rollback. Confirmed by
test (`test_agent_launch_persistence_is_not_covered_by_this_fix`): a journal failure still raises
(so the caller is never lied to about the *request* failing), but the run row is left in its
terminal state anyway. Closing this for real means `on_update` itself participating in a shared
transaction -- a change to `execution/launcher.py`'s notify/persistence wiring, not just
`assurance/service.py` and `assurance/store.py`. Left open, scoped precisely for whoever picks it
up next.

---

## Also found while completing the test suite (not threat-model findings, noted here for the record)

- **`execution/signal_control.py`'s `suspend_process`/`resume_process` do not actually suspend the
  target process on this machine**, despite `NtSuspendProcess`/`NtResumeProcess` both returning
  `STATUS_SUCCESS` (0x0). Verified three ways: (1) a print-loop child kept producing new output at
  its normal ~10 lines/sec rate throughout the "paused" window instead of going silent; (2) a
  CPU-busy-loop child's `TotalProcessorTime` showed no behavior change; (3) ruled out an
  access-rights cause by retrying with a full `PROCESS_ALL_ACCESS` handle instead of the minimal
  `PROCESS_SUSPEND_RESUME` one -- identical result. This is a real, physical machine (Dell XPS 15),
  not a VM/sandbox, so it isn't a virtualization restriction on the syscall either. Root cause is
  unknown -- possibly a Windows-build-specific change to this undocumented API's behavior, or a
  Python 3.14 ctypes/`WinDLL` interaction -- and I don't have a verified safe replacement to swap
  in. `backend/tests/execution/test_signal_control.py::test_suspend_stops_output_growth_and_resume_lets_it_continue`
  fails deterministically (not flaky) on this box. This is KB's brand-new pause/resume feature
  (`LIVE_AGENT_CONTROL_AND_BRANCHING_PLAN.md` Part A); needs KB's own environment to reproduce and
  debug further, or a from-scratch alternative implementation of process suspension.

  **KB follow-up (different machine, Lenovo, not the Dell XPS 15 above):** could not reproduce --
  both the existing test and a from-scratch repro (print-loop child, and separately a CPU-busy-loop
  child checked via `GetProcessTimes`) show genuine suspension: zero new output and zero CPU-time
  delta for the full observation window. Root cause on the original machine is still unconfirmed
  and may be host-specific (EDR/AV hooking the syscall, a Windows-build quirk, or something else
  entirely) -- not something fixable from here without access to that machine. What *is* fixable
  regardless of root cause: the module trusted `STATUS_SUCCESS` as proof of effect with no
  independent check, which is exactly how a machine where the syscall lies produces a silent
  fabricated success instead of a raised error. Fixed: `suspend_process` now samples
  `GetProcessTimes` before and ~100ms after the syscall and raises `AGENT_PAUSE_FAILED` if the
  process kept consuming CPU, rather than trusting the return code alone. Added
  `test_suspend_raises_if_ntsuspendprocess_lies_about_success` (stubs the syscall to a no-op
  returning success against a real CPU-busy child, confirms the verification catches it). This
  turns AC's exact failure mode into a raised error on any machine where it recurs, even though the
  underlying cause on the original box is still open -- KB should re-run the original test on that
  Dell XPS 15 to see whether it now fails loudly (verification working as intended) or the syscall
  genuinely suspends there too under this build (bug was possibly transient/environmental).

---

## SD — open, SD's exclusive paths (`contracts/`, `core/`, `main.py`, `migrations/`)

Do not patch these outside SD's paths. Handing off as findings per the coordination protocol.

### 1. `issue_grant` has no delegation/policy gate — HIGH
- **Location:** `core/runtime_service.py:185-199`, `CredentialAdminService.issue_grant`
- **Problem:** Only checks the target actor exists. Never checks the caller holds a `Delegation` covering the requested scope/Change. Any actor holding the shared bearer token can self-mint a `CredentialGrant` for scopes/Changes it was never delegated (no scope allowlist — any string ≤160 chars accepted).
- **Fix:** Require and consume a matching `Delegation` before minting a grant — same pattern `policy/service.py` already uses for operations.

### 3. Change deletion destroys the journal — HIGH
- **Location:** `core/change_repository.py:348-381`, `ChangeRepository.delete`; FK cascade in migrations.
- **Problem:** `DELETE /changes/{id}` cascades to `journal_events`/`journal_effects`, wiping the hash-chained audit trail — including the `CHANGE_DELETED` marker event itself. No Change-independent log records that a deletion happened.
- **Fix:** Write deletion events to a table outside the FK cascade, or make the "export-before-delete" flow the code's own comment anticipates mandatory.

### 4. `OutcomeService.refresh` has no actor binding — HIGH
- **Location:** `core/runtime_service.py:372-389`
- **Problem:** Unlike `create_pull_request` (which calls `require_grant(..., actor_id=...)` + `_enforce_policy`), `refresh` only checks `grant.change_id`. Combined with #1, any actor can read any Change's GitHub PR/CI status, unattributed in the journal.
- **Fix:** Add `actor_id` to `OutcomeRefreshRequest`, bind via `require_grant`, attribute the journal event.

### 5. Delegation creation has no grantor validation — HIGH (audit integrity) / MEDIUM (escalation)
- **Location:** `core/runtime_service.py:110-133`, `IdentityAdminService.create_delegation`
- **Problem:** Verifies the grantee exists but never validates `grantor_id` (can be a nonexistent UUID) or rejects `grantor_id == grantee_id`. An actor can self-issue an unlimited-use, year-long delegation.
- **Fix:** Resolve+validate `grantor_id`, reject self-delegation unless intentional, consider requiring `HUMAN` grantors.

### 6. `revoke_grant` broker TOCTOU — MEDIUM
- **Location:** `core/runtime_service.py:201-212`
- **Problem:** `broker.revoke(grant_id)` runs first and is inert (durable lookup always wins over the broker's in-memory write); the actual enforcement is the later `self.grants.revoke(...)` call. A concurrent `resolve_secret` landing between these two lines still succeeds. **Note:** SD's atomicity fix (#16) touched this exact function to wrap the durable write + journal append in one transaction, but did not reorder `broker.revoke()` relative to it — the window is unchanged. Cheap to close while already in this function.
- **Fix:** Call `self.grants.revoke(...)` (durable) first, then `self.broker.revoke(...)`.

### 9. Tool identity collision via `(name, version="unknown")` key — MEDIUM
- **Location:** `core/tool_registry_service.py:72-114`, `resolve_or_register`
- **Problem:** Lookup key is `WHERE name = ? AND version = ?`, looser than the schema's uniqueness constraint. Two different binaries sharing a filename stem collapse onto one manifest row; `resolve_or_register` silently overwrites the digest in place. **Note:** the newly-landed signature-revalidation fix (`503188d`) is a good complementary fix (recomputes `signature_state` when digest changes) but does not touch this lookup key — the identity-collision bug is still live underneath it.
- **Fix:** Key manifest identity on `(name, artifact_digest)` (or just `artifact_digest`), not `(name, version)`.

### 12. API bearer token file has no restrictive permissions — MEDIUM
- **Location:** `core/auth.py:41`, `load_or_create_api_token`
- **Problem:** Plain `Path.write_text`, no ACL/mode set. Another local OS account could read the file if the parent directory isn't already private.
- **Fix:** Set an explicit restrictive ACL/mode on the token file at creation.

---

## Shared — needs both AC and SD

### 7. Risk-based approval gate is dead code — MEDIUM
- **AC side (done, low value alone):** `policy/service.py::_infer_risk` is correct — it just has no caller passing a real value.
- **SD side (the actual fix):** `core/runtime_service.py:326,452` never populate `parameters["risk_level"]` for `github.pr.create`/`recovery.execute`, so `RISK_TOO_HIGH`/`required_approval` can never fire regardless of true operation risk.
- **Fix:** SD's call sites need to compute and pass an actual risk classification, or move risk classification into `_evaluate_operation` based on operation name/target rather than trusting an optional caller hint.

---

## AC — my exclusive paths (`identity/`, `policy/`, `credentials/`, `providers/`, `outcomes/`, `recovery/`, `passport/`, `cli/`, `tui/`)

### 2. GitHub PAT exposed via CLI argv — ✅ Fixed (`33edf5f`)
- `cli/main.py`, `github_connect` — no longer a positional argument. Reads `CHANGE_ASSURANCE_GITHUB_TOKEN` env var, else a hidden (`hide_input=True`) prompt. Tests added: `test_github_connect_takes_no_positional_token`, `test_github_connect_reads_token_from_env_var`.

### 8. Case-sensitive forbidden-path matching — ✅ Fixed (`a3cfd7f`)
- `policy/engine.py::_path_is_forbidden` — both sides of the comparison now `.casefold()`'d, matching NTFS's case-insensitivity. Test added: `test_forbidden_path_prefix_denies_regardless_of_case`.

### 14. `approval_token` not a real credential — ➖ Closed
- `recovery/git_recovery.py` — confirmed by SD as intentional design ("Approval is a strict precondition — empty token raises", per `OVERALL_CONTEXT.md`). Not a bug.

### 13. Recovery execution not bound to fresh HEAD — ✅ Fixed (by SD, in my path)
- `recovery/git_recovery.py` was patched directly by SD in `673bb7e`, outside the normal claim/handoff protocol (see boundary note below). The fix itself is correct and tested (`recovery/test_git_recovery.py`); no further action needed, just flagging the process gap.

---

## KB — fixed by AC at the operator's direction (`git/`, `execution/`, `environment/`, `dependencies/`, `assurance/`)

Originally deferred; the operator then explicitly directed fixing both now rather than waiting.
Landed directly in KB's exclusive path — flagged here for KB's review, same as SD's #13.

### 10. TOCTOU between trust-check hash and execution — ✅ Fixed
- **Location:** `execution/launcher.py`, `AgentLauncher.launch` / `_check_tool_trust`
- **Problem was:** the trust check hashed the executable via its own `resolve_argv` call; `launch()` independently re-resolved the same name and spawned it moments later. A file swap in between meant the hash checked wasn't guaranteed to be the bytes executed.
- **Fix:** `launch()` now resolves the executable exactly once and passes the resolved `argv` into `_check_tool_trust`, which no longer resolves at all. A resolution failure is carried as a stored `AppError` and re-raised at the original point so the existing error-handling/`AgentRun` creation path is unchanged.
- **Test:** `test_launch_resolves_the_executable_exactly_once` (spies on `resolve_argv`, asserts exactly one call per launch).
- **Residual, honestly noted:** this closes the double-resolution window entirely but does not eliminate the inherent gap between reading a file's bytes to hash it and the OS actually executing that path (no fd-based exec is used) — a swap landing inside `resolve_or_register`'s own read isn't addressed by this fix, matching the module's own "deliberately narrow, best-effort" scope.

### 11. Naive substring-only secret redaction in captured output — ✅ Fixed
- **Location:** `execution/launcher.py::AgentLauncher._text`
- **Problem was:** redaction was an exact string `.replace(secret, REDACTION)`. Any transformation (base64, hex, reversal) by a compromised agent before printing defeated it — exactly the PDF's own threat #1 ("agent process receives long-lived secret and exfiltrates it").
- **Fix:** `_text` now also redacts each secret's standard-base64, urlsafe-base64, and hex encodings. Docstring now states explicitly this is a mitigation, not a guarantee — arbitrary transformation (line-splitting, custom encoding, compression) still defeats it, and callers must not treat captured output as safe merely because it passed through here.
- **Test:** `test_encoded_secret_is_still_redacted` (a forwarded credential printed as base64/urlsafe-base64/hex, all three redacted).

---

## Already fixed by SD independently (for the record, not from this review)

- **#15 Legacy `/verify` had no authorization and leaked the daemon's environment** (`5c19c3c`) — found by SD's own parallel audit, not by any of my forks (none were scoped to `verification/`). Now gated on a `change.legacy_verify` delegation scope and uses the same bounded/minimal-environment subprocess primitive as everywhere else.
- **#16 Mutation + journal write not atomic for identity/credential/recovery** (`71da5f0`) — a journal failure could previously leave a delegation/grant durably committed while the client was told the request failed. Fixed via `Database.connection_or()` sharing one transaction between the repository write and the journal append. **Explicitly scoped to `core/runtime_service.py` only** — KB-owned emission points (`git/state.py`, `execution/launcher.py`, `environment/tracker.py`, `dependencies/tracker.py`, `assurance/service.py`) and `ProviderOperationRepository.create` remain unfixed, per SD's own commit message.

---

## Process/boundary note

Two cross-owner edits happened in this review, both worth a decision rather than letting the
pattern just accumulate silently:

- SD's `673bb7e` directly edited `recovery/git_recovery.py`, AC's exclusive path, without a
  declared integration lock.
- AC's fixes for #10/#11 directly edited `execution/launcher.py`, KB's exclusive path, at the
  operator's explicit direction rather than through a claim/handoff.

Both fixes are correct and tested, so nothing needs to be undone. Recommend formalizing that
P1 security fixes may cross owner boundaries without waiting for a claim, provided the commit
message says so explicitly (as both of these already do) and the actual owner reviews it after
the fact — rather than either blocking urgent fixes on protocol, or letting cross-owner edits
become an unremarked habit.

---

## Attack surfaces reviewed and found not exploitable

Auth boundary route coverage, constant-time token comparison, secret leakage into journal
payloads/logs/error bodies, Windows Credential Manager ctypes buffer handling, GitHub adapter
injection/header/TLS handling, subprocess argument construction (`shell=False` throughout),
environment-variable allowlisting for launched agents, output-capture bounding, hash-chain
verification, append-only journal triggers, tool-trust DENY-stickiness (the earlier drift fix),
delegation `use_limit` consume-vs-revoke race (correctly serialized), scope substring/prefix
confusion, expiry/clock backdating, temp-worktree race conditions, Passport digest spoofing,
CLI/TUI secret logging, terminal-escape injection via TUI, multi-tenant data isolation
(single-operator model is intentional, not a gap).
