# Threat Model Findings — Change Assurance Runtime

Status as of 2026-09-19, against `master` @ `cf1b00b`. Produced by a full attack-surface
review (credential broker, identity/delegation/policy, tool registry/execution/journal/replay,
recovery/passport/CLI/API auth boundary), cross-checked against the actual source, not just
docs, and reconciled against SD's own parallel audit fixes landed during the same window.

**Owner tags follow `AGENT_COORDINATION.md`'s exclusive-path table.** Findings are grouped by
owner so each person can pick up their own section without cross-editing another owner's path.
Per that doc's rule, **do not repair another owner's defect directly** — hand back a
reproducing test/finding instead, unless you are that owner.

Legend: 🔴 Open | ✅ Fixed | ➖ Closed (accepted design, not a bug)

---

## Summary

| # | Finding | Owner | Status |
|---|---|---|---|
| 1 | `issue_grant` has no delegation/policy gate | **SD** | 🔴 Open |
| 2 | GitHub PAT exposed via CLI argv | **AC** | ✅ Fixed |
| 3 | Change deletion destroys the journal | **SD** | 🔴 Open |
| 4 | `OutcomeService.refresh` has no actor binding | **SD** | 🔴 Open |
| 5 | Delegation creation has no grantor validation | **SD** | 🔴 Open |
| 6 | `revoke_grant` broker TOCTOU | **SD** | 🔴 Open |
| 7 | Risk-based approval gate is dead code | **AC** (engine) / **SD** (call sites) | 🔴 Open — needs both |
| 8 | Case-sensitive forbidden-path matching | **AC** | ✅ Fixed |
| 9 | Tool identity collision, `(name, version)` key | **SD** | 🔴 Open |
| 10 | TOCTOU between trust-check hash and execution | **KB** | 🔴 Open — deferred |
| 11 | Naive substring-only secret redaction in captured output | **KB** | 🔴 Open — deferred |
| 12 | API bearer token file has no restrictive permissions | **SD** | 🔴 Open |
| 13 | Recovery execution not bound to fresh HEAD | **AC**(engine)/**SD**(fixed it) | ✅ Fixed by SD |
| 14 | `approval_token` not a real credential | **AC** | ➖ Closed, by design |
| 15 | Legacy `/verify` had no authorization, leaked daemon env | **SD** | ✅ Fixed by SD |
| 16 | Mutation + journal write not atomic (identity/credential/recovery) | **SD** | ✅ Fixed by SD (partial — KB emission points explicitly still open) |

**Net: 5 of 16 closed. 11 open** — 7 SD, 2 KB, 1 shared AC/SD, 1 AC-portion of the shared item.

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

### 2. GitHub PAT exposed via CLI argv — ✅ Fixed
- `cli/main.py`, `github_connect` — no longer a positional argument. Reads `CHANGE_ASSURANCE_GITHUB_TOKEN` env var, else a hidden (`hide_input=True`) prompt. Tests added: `test_github_connect_takes_no_positional_token`, `test_github_connect_reads_token_from_env_var`. Not yet committed — pending your approval.

### 8. Case-sensitive forbidden-path matching — ✅ Fixed
- `policy/engine.py::_path_is_forbidden` — both sides of the comparison now `.casefold()`'d, matching NTFS's case-insensitivity. Test added: `test_forbidden_path_prefix_denies_regardless_of_case`. Not yet committed — pending your approval.

### 14. `approval_token` not a real credential — ➖ Closed
- `recovery/git_recovery.py` — confirmed by SD as intentional design ("Approval is a strict precondition — empty token raises", per `OVERALL_CONTEXT.md`). Not a bug.

### 13. Recovery execution not bound to fresh HEAD — ✅ Fixed (by SD, in my path)
- `recovery/git_recovery.py` was patched directly by SD in `673bb7e`, outside the normal claim/handoff protocol (see boundary note below). The fix itself is correct and tested (`recovery/test_git_recovery.py`); no further action needed, just flagging the process gap.

---

## KB — deferred, to fix together next (`git/`, `execution/`, `environment/`, `dependencies/`, `assurance/`)

Not touched. Per your instruction, holding these for a joint session rather than either of us patching KB's paths solo.

### 10. TOCTOU between trust-check hash and execution — MEDIUM
- **Location:** `execution/launcher.py:140` (`_check_tool_trust`) vs. `:168` (`launch`'s own separate `resolve_argv`)
- **Problem:** The trust check hashes the executable once; `launch()` independently re-resolves the same path and spawns it moments later. A file swap in between means the hash checked isn't guaranteed to be the bytes executed.
- **Fix:** Hash and execute from the same resolved path/handle, or re-verify immediately before spawn with no intervening work.

### 11. Naive substring-only secret redaction in captured output — MEDIUM
- **Location:** `execution/launcher.py:388-425` (`_environment`, `_text`)
- **Problem:** Redaction is an exact string `.replace(secret, REDACTION)`. Any transformation (base64, reversal, line-splitting) by a compromised agent before printing defeats it — exactly the PDF's own threat #1 ("agent process receives long-lived secret and exfiltrates it").
- **Fix:** Best-effort mitigation should be documented as such; consider entropy/pattern-based output scanning as defense in depth.

---

## Already fixed by SD independently (for the record, not from this review)

- **#15 Legacy `/verify` had no authorization and leaked the daemon's environment** (`5c19c3c`) — found by SD's own parallel audit, not by any of my forks (none were scoped to `verification/`). Now gated on a `change.legacy_verify` delegation scope and uses the same bounded/minimal-environment subprocess primitive as everywhere else.
- **#16 Mutation + journal write not atomic for identity/credential/recovery** (`71da5f0`) — a journal failure could previously leave a delegation/grant durably committed while the client was told the request failed. Fixed via `Database.connection_or()` sharing one transaction between the repository write and the journal append. **Explicitly scoped to `core/runtime_service.py` only** — KB-owned emission points (`git/state.py`, `execution/launcher.py`, `environment/tracker.py`, `dependencies/tracker.py`, `assurance/service.py`) and `ProviderOperationRepository.create` remain unfixed, per SD's own commit message.

---

## Process/boundary note

SD's `673bb7e` directly edited `recovery/git_recovery.py`, which is AC's exclusive path per
`AGENT_COORDINATION.md`, without a declared integration lock. The fix itself is correct and
well-tested, so nothing needs to be undone — but for P1 security fixes that land fast, worth
agreeing explicitly whether cross-owner hotfixes are allowed with a follow-up notification, or
whether they should always come back as a handoff even under time pressure. Recommend the
former (allow, but always leave a commit-message trail like this one already does) rather than
blocking urgent security fixes on protocol — just flagging so it's a decision, not a drift.

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
