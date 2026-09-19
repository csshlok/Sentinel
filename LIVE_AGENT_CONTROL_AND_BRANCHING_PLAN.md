# Live Agent Control, Checkpoint Branching, and Real-Time TUI — Reversal + Addition Plan

## 0. Authority and status of this document

This document is a plan, not an implementation, following this repository's own established
convention for a scope reversal (`EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` is the precedent for
both the process and the writing style used here). It authorizes three things for a future
implementation pass:

- **Part A** — a narrow, explicit reversal of one slice of the "process supervisor" cut: the
  ability to **suspend and resume the top-level launched process** (not observe, not attribute,
  not control its descendants). Everything else about the process-supervisor cut stays cut.
- **Part B** — a new, purely additive capability: **forking a Change at a captured checkpoint**,
  so an alternate agent run (different prompt, different model, different parameters) can be
  tried from that exact evidence state and compared against the original without losing either
  branch's evidence trail.
- **Part C** — a new, purely additive capability: **incremental evidence capture and TUI
  polling**, so a running agent's output becomes visible while it runs, not only after it
  finishes.

Source authority order, matching this project's own convention: `Change_Assurance_Runtime_Project_Proposal (2).pdf`
→ `BACKEND_IMPLEMENTATION_PLAN.md` → the current codebase → this document.

---

## PART A — Live Agent Control (top-level suspend/resume)

### A.1 Exact scope, stated up front

The **process supervisor** cut means: no descendant-process observation, no process-tree
attribution, no orphan cleanup, no Windows Job Object enforcement. **None of that is reversed
here.** What is added is narrower and different in kind: the ability to suspend and later resume
the *single top-level process* `AgentLauncherPort.launch` already started and already tracks by
PID (`AgentRun.top_level_pid` already exists). Suspending a process's threads is not the same
claim as supervising its process tree — it requires no knowledge of what descendants exist, and
grants no attribution or cleanup capability over them. `AgentRun.descendant_control_available`
stays `Literal[False]`; nothing about descendant processes becomes true here.

**What changes:** a new `AgentRunStatus.PAUSED` state, a `POST /changes/{id}/agents/{run_id}/pause`
and `.../resume` route pair, and a real, bounded Windows implementation using the same
ctypes-to-a-system-DLL pattern this codebase already trusts (`WindowsCredentialStore` binds
`advapi32.dll`; `execution/signature.py` shells out to `signtool.exe`). Pause/resume binds
`ntdll.dll`'s `NtSuspendProcess`/`NtResumeProcess` — undocumented but stable, load-bearing APIs
used by mainstream Windows tooling (Process Explorer, Visual Studio's "Break All") for exactly
this operation, the same honesty tier as this project's other "real but platform-scoped"
choices. Non-Windows platforms get an honest `AppError` (`AGENT_PAUSE_UNSUPPORTED`), never a
fabricated success — matching the Authenticode precedent's `signature_state = "unknown"` rather
than lying.

### A.2 Data model

```
AgentRunStatus gains PAUSED (existing: RUNNING, PASSED, FAILED, TIMED_OUT, CANCELLED, ERROR,
                              ATTACHED)

AgentRun gains:
    paused_at: datetime | None = None
    resumed_at: datetime | None = None
```

No new table. `agent_runs` already stores the full `AgentRun` payload as JSON
(`assurance/store.py::EvidenceStore`); the two new fields are additive to that same payload.

### A.3 Port contract

```python
class AgentLauncherPort(Protocol):
    ...  # launch, attach, stop unchanged
    def pause(self, run_id: UUID) -> AgentRun:
        """Suspend the top-level process's execution. Descendants are not
        suspended (no process-tree enumeration is performed); a descendant
        that has already spawned its own children continues running.
        Windows only; AGENT_PAUSE_UNSUPPORTED elsewhere."""

    def resume(self, run_id: UUID) -> AgentRun:
        """Resume a paused top-level process."""
```

### A.4 `execution/signal_control.py` (new, `[KB]`-owned)

```python
import ctypes

_ntdll = ctypes.WinDLL("ntdll") if sys.platform == "win32" else None

def suspend_process(pid: int) -> None:
    """Raises AppError('AGENT_PAUSE_FAILED', ...) on failure, never silently no-ops."""
    if _ntdll is None:
        raise AppError("AGENT_PAUSE_UNSUPPORTED", "Pausing a process is only supported on Windows.")
    handle = _open_process(pid)  # PROCESS_SUSPEND_RESUME only, least privilege
    try:
        status = _ntdll.NtSuspendProcess(handle)
        if status != 0:
            raise AppError("AGENT_PAUSE_FAILED", f"NtSuspendProcess returned {status:#x}.")
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

def resume_process(pid: int) -> None: ...  # mirror, NtResumeProcess
```

Bounded, narrow-privilege handle (`PROCESS_SUSPEND_RESUME = 0x0800`, not `PROCESS_ALL_ACCESS`),
matching this codebase's least-privilege convention already established for subprocess
execution (`shell=False`, argument arrays, minimal environment).

### A.5 `AgentLauncher.pause`/`.resume` (`execution/launcher.py`)

- Look up `_State` by `run_id`; require `status is RUNNING` for pause (a `PAUSED`,
  `PASSED`/`FAILED`/etc. run is rejected with a stable `AGENT_RUN_NOT_PAUSABLE` error — pausing
  something already finished is a caller bug, not silently accepted).
- Call `suspend_process(state.record.top_level_pid)`; on success, update the stored record to
  `PAUSED` with `paused_at=now`, call `self._notify(paused)` (the existing `on_update` hook —
  EvidenceService already subscribes, so the persisted row updates with no new plumbing).
- **The capture() read loop must not treat a paused process as timed out or dead.** `capture()`
  (execution/_process.py) already polls in a loop with a deadline; while paused, `os.read` on the
  pipes will simply return nothing (`BlockingIOError`) since the suspended process cannot write —
  indistinguishable from "no output yet" from the reader's perspective. The existing deadline
  logic would eventually fire a false timeout for a long pause. Fix: `capture()` gains an optional
  `paused: threading.Event` (mirroring the existing `cancel: threading.Event`); while set, the
  deadline check is skipped (paused time does not count against the timeout budget). `pause()`
  sets it, `resume()` clears it.
- `resume()` mirrors `pause()`: requires `status is PAUSED`, calls `resume_process`, updates to
  `RUNNING` with `resumed_at=now`, clears the `paused` event, notifies.

### A.6 API, CLI, TUI

- `POST /api/v1/changes/{id}/agents/{run_id}/pause`, `.../resume` — policy-gated on
  `agent.pause`/`agent.resume` scopes (same `_enforce_policy` pattern as `stop`), journaled as
  new `JournalEventType.AGENT_PAUSED` / `AGENT_RESUMED` events.
- CLI: `agent pause RUN_ID --actor-id`, `agent resume RUN_ID --actor-id`.
- TUI: the evidence screen (Part C) gains Pause/Resume buttons alongside the existing Stop,
  enabled only when `status` is `RUNNING`/`PAUSED` respectively — same enable-on-selection pattern
  already proven in `recovery_screen.py`/`tool_trust_screen.py`.

### A.7 Explicit non-goals (stated in API/CLI/TUI copy, matching every other bounded capability)

- No descendant-process suspension. A multi-process agent whose top-level process spawned
  children before being paused does not pause those children.
- No cross-platform support. `AGENT_PAUSE_UNSUPPORTED` on non-Windows, never a fabricated
  success.
- No indefinite-pause guarantees against OS resource reclamation (a suspended process can still
  be killed by the OS, e.g. under memory pressure); this is disclosed, not hidden.

---

## PART B — Checkpoint Branching (fork-and-compare)

### B.1 Concept

From any captured `GitCheckpoint` (or, more generally, any point in a Change's journal), create
a **new, independent child Change** whose baseline evidence is seeded from that checkpoint's
state — same repository, same starting commit/environment/dependency snapshot — so a different
model, prompt, or parameter set can be tried from that exact point without disturbing the
original Change's own history. Both the parent and the fork keep their own complete, independent
evidence trail, journal, and lifecycle. This is deliberately **not** a Git branch (it does not
touch the repository); it is a Change Assurance Runtime concept layered on top of Git, exactly
like everything else in this product's evidence model.

### B.2 Data model

```
ChangeView gains:
    forked_from_change_id: UUID | None = None
    forked_from_checkpoint_id: UUID | None = None

ChangeCreateRequest gains (optional):
    fork_from_checkpoint_id: UUID | None = None
```

`changes` table gains two nullable columns (additive migration), no FK cascade concerns beyond
the existing `changes.id` self-reference pattern already used elsewhere in this schema
(`ON DELETE SET NULL`, so deleting a parent Change does not cascade-delete its forks — forks are
independent, first-class Changes, not owned children).

### B.3 `ChangeService.fork(source_change_id, checkpoint_id, *, title, intent) -> ChangeView`

- Validate the source checkpoint belongs to `source_change_id` (existing `CHECKPOINT_REPOSITORY_MISMATCH`-style
  check).
- Create a new Change row exactly like `create()`, with `forked_from_change_id`/`forked_from_checkpoint_id`
  set.
- Seed the fork's own `git_checkpoints`/`environment_passports`/`dependency_reports` with **copies**
  of the source checkpoint's evidence (new IDs, same `change_id` = the fork's own id, same
  `repository_root`/`head_sha`/payload content) — the fork gets its own baseline exactly as if it
  had captured that evidence itself, honestly re-attributed to the fork's own Change, not a
  cross-Change reference (this matters for the journal: the fork's own hash chain starts clean,
  describing evidence *this Change* holds, not borrowed evidence).
- Emit `JournalEventType.CHANGE_FORKED` on both the source Change (payload: `{forked_change_id}`)
  and the new fork (payload: `{forked_from_change_id, forked_from_checkpoint_id}`), so the
  relationship is independently auditable from either side.

### B.4 API, CLI, TUI

- `POST /api/v1/changes/{id}/fork` — body `{checkpoint_id, title, intent}` → `ChangeView`.
- `GET /api/v1/changes/{id}/forks` — list Changes with `forked_from_change_id == id`.
- CLI: `change fork CHANGE_ID CHECKPOINT_ID --title ... --intent ...`, `change forks CHANGE_ID`.
- TUI: a "Fork from checkpoint" action on the evidence screen's checkpoint list (reuses the
  existing checkpoint table already rendered there); a "View forks" action on the dashboard row
  showing a Change's fork count and letting the operator jump between a Change and its forks —
  this is the "branch out, change the model, run it, compare" workflow the operator described,
  built from evidence Changes already model, not a new comparison engine.

### B.5 Explicit non-goals

- Not a Git branch or Git merge. No repository mutation happens as part of forking.
- No automatic "diff the two branches' outcomes" UI in this pass — the operator compares two
  ordinary Change Passports side by side (both already exportable); a dedicated comparison view
  is a natural but separate follow-up, not promised here.

---

## PART C — Incremental Evidence Capture and TUI Live View

### C.1 Concept

`execution/_process.py::capture` already reads process output incrementally in its polling loop
(`os.read(..., 65_536)` inside a `while` loop) — the data exists moment-to-moment inside that
function's local buffers, but is only returned to the caller once, at the end, when `launch()`
finally returns. Making it visible "live" means persisting partial output as it accumulates, not
building a new transport.

### C.2 `capture()` gains an optional `on_chunk: Callable[[bytes, bytes], None]`

Called from inside the existing read loop with `(stdout_delta, stderr_delta)` whenever new bytes
are read (before truncation is applied to the retained buffers, so the callback always sees the
same bytes that were actually produced, bounded by the same overall budget the final result
already enforces). No new thread, no new primitive — an additional parameter to a loop that
already runs.

### C.3 `AgentLauncher.launch` wires `on_chunk` to a bounded, rate-limited persistence callback

- Accumulate into `state.record`'s `stdout`/`stderr` (through the existing redaction pass,
  `self._text(...)`, so a secret appearing mid-stream is redacted the same way the final result
  already is — this is not a new redaction path, it reuses the existing one per chunk).
- Call `self._notify(...)` (existing hook) **at most once per configurable interval** (default
  500ms), not per chunk — a chatty process must not flood the journal/store with an update per
  byte. This is a simple monotonic-clock gate in the callback, not a new scheduler.
- `EvidenceService.save_agent_run` (existing `on_update` subscriber) already `UPDATE`s the stored
  row; no store-side change needed, it already handles receiving multiple updates for one
  `run_id` (proven today by the existing start → complete two-update sequence).

### C.4 API: nothing new required

`GET /changes/{id}/agents` already returns the current stored `AgentRun` list; a running agent's
row now has real, growing `stdout`/`stderr` instead of empty strings until completion. No new
route.

### C.5 TUI: the evidence screen polls on a shorter interval while a run is active

- `evidence_screen.py` already has a manual refresh action; add an automatic timer
  (`set_interval`, Textual's existing primitive) that polls only while the screen shows a
  `RUNNING`/`PAUSED` agent run for the current Change, stopping once the run reaches a terminal
  state (no wasted polling once nothing is changing).
- Render stdout/stderr as a live-updating panel (last N lines, matching the existing bounded
  -output-display convention already used elsewhere in the TUI), with a persistent "still
  running" indicator, never inventing progress-percentage or ETA the backend cannot honestly
  provide.

### C.6 Explicit non-goals

- Not a push/streaming transport (SSE/WebSocket). Polling only, per the operator's own scoping
  decision — a future upgrade if true push semantics are wanted later, not promised here.
- Not real-time for the browser frontend, which remains deferred per every existing context
  document; this part is TUI-only, per the operator's explicit instruction.

---

## PART D — Cross-cutting

### D.1 Migration ordering

```
Migration(8, "agent_run_pause_fields", ...)      # additive AgentRun JSON fields need no schema change
                                                    (payload_json already stores the full model)
Migration(9, "change_fork_columns", ...)          # changes.forked_from_change_id / _checkpoint_id
```

Migration 8 is a no-op at the SQL level (the new `AgentRun` fields live inside the existing
`payload_json` blob in `agent_runs`), listed here only for changelog completeness; migration 9
is the only real schema change in this plan.

### D.2 Ownership (per `AGENT_COORDINATION.md`'s exclusive-path table)

| Path | Owner | What goes here |
| --- | --- | --- |
| `contracts/models.py`, `contracts/ports.py` | `[SD]` | `AgentRunStatus.PAUSED`, `AgentRun.paused_at`/`resumed_at`, `ChangeView.forked_from_*`, `AgentLauncherPort.pause`/`.resume` signatures |
| `migrations/versions.py` | `[SD]` | Migrations 8, 9 |
| `core/change_service.py` | `[SD]` | `ChangeService.fork` |
| `core/router.py`, `main.py` | `[SD]` | New routes: pause/resume, fork, forks-list |
| `execution/signal_control.py` (new), `execution/launcher.py`, `execution/_process.py` | `[KB]` | Pause/resume implementation, `on_chunk` capture parameter |
| `assurance/service.py`, `assurance/store.py` | `[KB]` | Incremental `save_agent_run` handling (already works; verify under the new multi-update-per-run volume) |
| `cli/main.py`, `cli/client.py`, `tui/evidence_screen.py`, new fork-related TUI affordance | `[AC]` | CLI commands, TUI pause/resume/fork/live-tail UI |

### D.3 Required edits to existing context documents (this section performed as part of this same
change, per the operator's explicit instruction — unlike the journal/tool-registry precedent,
where context-doc edits were deferred and had to be reconciled later, causing real drift)

- **`AGENT_COORDINATION.md`** "Scope guardrails": clarify that top-level process suspend/resume
  is in bounded scope; descendant-process control remains forbidden.
- **`OVERALL_CONTEXT.md`** "Product direction"/"Current product scope"/architecture diagram: note
  the narrow pause/resume reversal, checkpoint forking, and incremental capture as retained
  capabilities with their stated boundaries.
- **`PROJECT_CONTEXT.md`** "Approved cuts"/"Necessary consequences"/"Product language": same
  reconciliation pattern used for the journal/tool-registry reversal.
- **`BACKEND_IMPLEMENTATION_PLAN.md`**: add the new routes to §8, the new ownership paths to
  §9-11, note the process-supervisor cut is now "narrowed" rather than absolute in §2/§3.1.

### D.4 Test strategy

- **Part A**: a real Windows subprocess (e.g. `python -c "import time; time.sleep(5)"`) paused
  mid-run, proven paused by observing no further stdout growth for a bounded wait window, then
  resumed and proven to complete; `AGENT_PAUSE_UNSUPPORTED` on a non-Windows CI runner if one is
  ever added; pausing an already-terminal run is rejected.
- **Part B**: fork a real disposable Git repository's Change at a real checkpoint; assert the
  fork's own baseline checkpoint has independent evidence rows (different IDs, same content);
  assert the source Change's own history is untouched; assert `GET .../forks` lists it.
- **Part C**: a real subprocess that prints incrementally with sleeps between prints; assert the
  stored `AgentRun.stdout` grows across polls before the process exits (not only visible after
  completion).

## Summary of what this plan authorizes and does not

Authorizes: top-level-only process suspend/resume (Windows-first, honestly unsupported
elsewhere), Change forking from a checkpoint with fully independent evidence trails, and
incremental agent-output capture surfaced via TUI polling. Does not authorize: descendant-process
observation/control/cleanup, filesystem tracking, Git branching/merging, a push/streaming
transport, or browser-frontend real-time views — all of those remain out of scope exactly as
every existing context document already states.
