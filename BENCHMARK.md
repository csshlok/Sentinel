# Benchmarks

Every number on this page came from actually running Sentinel and timing it — nothing here is
estimated, modeled, or carried over from a vendor claim. Where a number is *cited* rather than
measured (one is, below), it says so and links its source.

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
