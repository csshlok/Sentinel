# Benchmarks

Every number on this page came from actually running Sentinel — nothing here is estimated,
modeled, or carried over from a vendor claim. Where a number is *cited* rather than measured
(one is, below), it says so and links its source.

Speed is reassuring, but it isn't the point. The numbers that actually matter for a tool like this
are whether it sees what an agent does and whether its record of that can be trusted — so this
page leads with correctness and tamper-resistance, and puts latency last.

## Methodology and honest limits

- **One machine, one run.** All numbers below come from a single developer laptop (12th Gen
  Intel Core i7-12700H, 14 cores / 20 threads, 16 GB RAM, Windows 11 Home), not a controlled
  benchmarking rig, not an average across multiple machines, and not a CI runner. Treat these as
  "what Sentinel costs on ordinary hardware," not as guaranteed production SLAs.
- **Real backend, real repository, real subprocesses.** Every timed operation is a real HTTP
  call against a real `uvicorn`-served FastAPI backend, against a real (non-toy) local Git
  repository with two commits and 20 tracked Python files, over loopback HTTP. Agent launches
  spawn real Windows processes — no mocks, no fakes, no `page.route` interception.
- **n and spread are reported, not just an average.** Each figure below is `median` over the
  stated sample size, with `min`/`max` shown so a one-off outlier is visible rather than hidden
  inside a mean.
- **What isn't measured here:** multi-user concurrency, a large monorepo (thousands of files),
  network latency to a remote backend (everything above is loopback), and Linux/macOS (the
  process-tree supervision and restricted-token features are Windows-only by design).

## Correctness: does it actually catch what it claims to?

### Dependency drift detection

A real `requirements.txt` was changed between two evidence captures — one package's version
bumped, one package removed, one new package added — and compared against what Sentinel's
dependency report actually recorded.

**3 out of 3 injected changes detected, exactly (no false positives, no misses):**
`requests==2.31.0 → 2.32.0` (version bump), `flask==2.3.0 → removed`, `click → 8.1.0 added`.

### Credential redaction, honestly measured by attack type

`AgentLauncher._text` — the real function every launched agent's captured stdout/stderr passes
through — was called directly with a known secret transformed ten different ways, and checked for
whether its `[REDACTED]` marker actually appeared (not just whether the literal substring vanished,
which gives false credit to things like a reversed string that a human could still trivially read):

| Attack | Redacted? |
|---|---|
| Plain | ✅ |
| Base64 (standard) | ✅ |
| Base64 (URL-safe) | ✅ |
| Hex | ✅ |
| Surrounded by other text | ✅ |
| Split across a newline | ❌ |
| Reversed | ❌ |
| URL-encoded | ❌ |
| Inserted whitespace | ❌ |
| Double base64 | ❌ |

**5 out of 10 (50%) redacted.** The module's own docstring already states this scope honestly —
"arbitrary transformation (splitting across lines, a custom encoding, compression) by a compromised
agent can still defeat it" — this benchmark just puts a number on exactly which attacks that
covers and which it doesn't, rather than leaving the boundary vague.

### Journal tamper detection — two independent layers, both tested

Three real tampering attempts were made directly against the SQLite file behind a Change with a
real journal: editing an event's payload, deleting a middle event, and corrupting a stored hash.

**3 out of 3 were rejected outright by the database's own append-only triggers** — `journal_events
is append-only` — before the edit could take effect at all, let alone need detecting afterward.

To test the *second* layer independently, the trigger was deliberately dropped for one edit (as
if an attacker bypassed the database engine's own enforcement entirely, e.g. by editing the raw
file with the process stopped), the payload was corrupted, and the trigger restored:

**The hash-chain replay verification caught it and named the exact broken sequence number** —
`verified: false`, `first_break_seq: 1`, `reason: "event_hash does not match its recomputed
value."` Two independent defenses, both confirmed to actually work, not just assumed to.

### Privilege reduction — concrete, named privileges, not just "lower"

The same `whoami /priv` command was run from inside a real Sentinel-supervised (restricted-token)
launch and from a real unsupervised launch, and the resulting Windows token privileges were diffed:

- **Plain launch:** `SeChangeNotifyPrivilege`, `SeIncreaseWorkingSetPrivilege`,
  `SeShutdownPrivilege`, `SeTimeZonePrivilege`, `SeUndockPrivilege` (5 total)
- **Restricted-token launch:** `SeChangeNotifyPrivilege` only (1 total)

**4 named privileges concretely removed**: the ability to shut down or undock the system, change
the system clock, and increase its own working-set quota are gone before the agent's code ever
runs — not a vague claim of "lower privilege," a specific, checkable list.

## Known limits, quantified rather than hidden

This documentation already states that descendant-process observation is best-effort and that
Sentinel doesn't independently observe filesystem writes outside Git. Rather than leave those as
vague caveats, here's what's actually been measured and what hasn't yet:

- **Process capture across a range of real lifetimes** (1ms–500ms buckets, 30 trials each, on a
  Sentinel-supervised Job Object polling roughly every 50ms) was run for this page. A first attempt
  showed 100% capture at every bucket, but that run turned out to be confounded: the interpreter
  used for the launched processes was itself a Windows-venv launcher stub (see the pause/resume
  fix earlier in this project's history), which meant each "single child" was actually two or three
  overlapping processes, making the true single-process capture rate impossible to read off that
  run honestly. A corrected re-run against an unwrapped interpreter was still in progress at the
  time this page was written and its result is intentionally left out rather than reported before
  it's confirmed. What's real and unambiguous either way: Windows Job Object membership queries
  return every PID ever assigned to the job, including ones that have already exited, which is why
  a short-lived *direct* child has a real chance of survival even between ~50ms polls; a process
  nested several levels deep that starts and fully exits inside one polling window is the
  harder, not-yet-isolated case the documentation's own caveat is actually about.
- **Pause/resume reliability across many repeated trials with real nested process trees** was
  attempted for this page but the specific run produced a measurement artifact (inconsistent
  worker-PID identification across trials, not a reliability failure) rather than a clean result,
  and was dropped rather than published as if it were trustworthy. The single, carefully isolated
  verification earlier in this project's own history stands as real evidence instead: a 4-process
  supervised tree (top-level plus three nested layers) showed completely flat CPU time across a
  full 6-second observation window while paused, with zero exceptions across the trial. A clean
  statistical version of this at higher N is real, valuable future work.
- **Recovery success/safety across many injected bad changes, a large-scale (1K/10K/100K-file)
  repository test, journal verification at scale, and an adversarial head-to-head comparing an
  agent's own self-report against Sentinel's independently captured evidence** were all judged
  worth doing (see the project's own benchmark-planning discussion) but were not completed for
  this page in the time available. Naming them here, unfinished, is more honest than omitting them
  silently or filling them with invented numbers.

## Operation latency

| Operation | n | median | min | max |
|---|---|---|---|---|
| Create a Change | 15 | 198.8 ms | 163.7 ms | 231.4 ms |
| Capture baseline evidence (git status + diff + environment facts) | 15 | 1871.4 ms | 1774.9 ms | 2066.9 ms |
| Capture current evidence (+ dependency scan + baseline comparison) | 15 | 2344.7 ms | 2212.3 ms | 2537.5 ms |
| Discover an assurance plan | 15 | 167.7 ms | 145.3 ms | 195.4 ms |
| Build a Change Passport (assembles all evidence + replay verification) | 15 | 51.4 ms | 33.7 ms | 86.0 ms |
| Sign + export a Passport (Ed25519) | 15 | 29.4 ms | 11.4 ms | 47.2 ms |
| Preview a recovery plan | 15 | 33.9 ms | 14.0 ms | 61.6 ms |
| Launch a trivial agent, full request path (HTTP + policy + persistence + journal + real process) | 10 | 236.3 ms | 223.6 ms | 277.2 ms |
| Verify a hash-chained journal (9 events) | 15 | 26.1 ms | 14.3 ms | 46.2 ms |

The evidence-capture operations are the slowest in the table (1.9–2.3 seconds) because they run
several real external tool checks in sequence (`git`, environment fact collection, dependency
manifest parsing) rather than because of anything specific to Sentinel's own logic — this is a
known, honest cost of gathering *real* evidence instead of a cached or simulated summary, and the
biggest lever for a future optimization pass would be parallelizing those checks.

## The cost of the safety mechanism itself

The "launch a trivial agent" row above includes a full HTTP round trip, policy evaluation, SQLite
persistence, and a journal write — comparing it directly to a bare `subprocess.Popen()` call would
overstate what the actual security mechanism costs, since most of that time isn't the process
launch at all. So we measured the launch mechanism in isolation instead, same process, same
Python interpreter, nothing else running:

| Spawn method | n | median | min | max |
|---|---|---|---|---|
| Plain `subprocess.Popen`, no supervision | 20 | 81.7 ms | 73.7 ms | 102.9 ms |
| Restricted-token + Windows Job Object supervised spawn | 20 | 103.6 ms | 87.5 ms | 131.3 ms |

**The full safety mechanism — a restricted token with maximum privileges disabled, a kill-on-close
Job Object, and real-time descendant-process attribution — costs about 22ms (27%) over a bare,
unsupervised spawn.** In exchange, every process an agent starts is tracked (PID, parent, image
path, command line, lifetime, exit code) and gets terminated as a unit on stop, and the agent
itself runs with reduced Windows privileges instead of full inherited authority.

## Coverage numbers

These aren't timings — they're what actually exists and passes, counted directly rather than
claimed:

- **1,022 tests total** across the project: 785 backend (Python, including 74 real-process TUI
  tests that exercise a live `textual` app against a live backend), 46 frontend unit tests, 98
  Electron main-process tests, and 93 Playwright end-to-end specs (desktop UI against both a real
  backend and a scripted fake one). All green as of this writing.
- **66 API operations across 61 routes**, described by 110 typed schemas in the frozen OpenAPI
  contract that both the desktop app and the TUI/CLI consume from the same source of truth.
- **16 threat-model findings from a full attack-surface review** (credential broker, identity/
  delegation/policy, tool registry, execution/journal/replay, recovery/passport, API auth
  boundary): 15 fixed, 1 closed as accepted-by-design, **0 open**.
- **~18,100 lines of backend application code** and **~14,100 lines of backend test code** —
  roughly three-quarters of a line of test for every line of product code. The desktop frontend
  adds **~12,300 lines of TypeScript/TSX** plus **~2,800 lines of Electron main-process code**.

## Why this matters, with an honest comparison

Sentinel doesn't replace code review, and it doesn't find defects — it automates the *evidence
gathering* around a change (what actually ran, what the environment looked like, what dependencies
moved, whether the process tree behaved) so a human reviewer's time goes toward judgment instead
of manual reconstruction. For scale, the widely-cited SmartBear/Cisco study of 2,500 code reviews
covering 3.2 million lines found that effective manual review tops out around 200–400 lines of
code per hour to catch 70–90% of defects
([SmartBear, "Best Practices for Peer Code Review"](https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/)).
Reconstructing the equivalent of one review's worth of environment, dependency, and process-tree
evidence by hand — the part Sentinel automates, not the defect-finding itself — took under 2.5
seconds against the 20-file repository used above.

## Reproducing these numbers

Every figure here comes from `backend/` running behind `uvicorn` and a disposable local Git
repository — no fixtures, no synthetic data generator, no numbers pulled from a spreadsheet. Start
a backend against a real repository and time the same nine operations with a short script against
`/api/v1/changes`, `/evidence/{baseline,current}`, `/assurance/plan`, `/passport`,
`/passport/export`, and `/recovery/preview`; the isolated spawn comparison calls
`backend.app.execution.process_supervisor.spawn_restricted_supervised` directly against
`subprocess.Popen` with the same argv, no HTTP involved. Coverage numbers come from
`pytest --collect-only -q` per test directory and `wc -l` over `backend/app`, `backend/tests`,
`apps/desktop/src`, and `apps/desktop/electron`.
