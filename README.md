<p align="center">
  <img src="apps/desktop/public/brand/sentinel-logo.png" width="140" alt="Sentinel">
</p>

<h1 align="center">Sentinel</h1>

<h3 align="center">a change assurance runtime for AI coding agents</h3>

<p align="center">
  Give an AI agent real write access to your repository, and get back independently
  observed, tamper-evident, signed evidence of exactly what it did.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-1f2937.svg" alt="Windows">
  <img src="https://img.shields.io/badge/status-pre--release-b7791f.svg" alt="Pre-release">
  <img src="https://img.shields.io/badge/version-0.1.0-2563eb.svg" alt="Version 0.1.0">
  <img src="https://img.shields.io/badge/tests-1%2C022%20passing-2f855a.svg" alt="1,022 tests passing">
  <img src="https://img.shields.io/badge/threat--model-16%2F16%20reviewed-2f855a.svg" alt="16/16 threat-model findings reviewed">
</p>

Sentinel sits between an AI coding agent and your Git repository. It launches the agent under
real Windows process-tree supervision with reduced privileges, captures Git, environment, and
dependency evidence before and after it runs, records every mutation in a hash-chained journal,
and can produce a signed Change Passport that says — with evidence, not with the agent's own
word — exactly what happened.

It is a local-first Windows runtime: a FastAPI backend, a Textual terminal UI, a CLI, and a
native desktop app, all driven from the same frozen API contract.

> [!IMPORTANT]
> Sentinel is pre-release, hackathon-stage software. It has no installer, no code signing, and no
> production deployment story yet. See [Known limits](#known-limits) before relying on it for
> anything you can't afford to lose.

## Why Sentinel exists

An AI agent with write access to your repository can run arbitrary code, install dependencies,
call your credentials, and open pull requests — usually with nothing but its own transcript as a
record of what it actually did. That transcript is not evidence: it's the agent's self-report,
produced by the same process whose behavior you're trying to verify.

Sentinel is not another agent framework, and it doesn't try to make an agent smarter or safer to
prompt. It sits at the process boundary and observes independently, so trust in what an agent
did doesn't depend on trusting the agent's account of itself.

| Without Sentinel | With Sentinel |
| --- | --- |
| Trust the agent's own transcript for what it ran | Independently observed process-tree evidence: every spawned process, its PID, image path, command line, and lifetime |
| No record of the environment or dependencies before/after | Environment and dependency passports captured automatically and diffed for drift |
| The agent runs with your full account privileges | Restricted-token launch strips maximum privileges before the agent's code ever executes |
| "Trust me" that a credential didn't leak into output | Minimal-environment subprocess execution plus output redaction, tested against encoded exfiltration attempts |
| An audit trail that could be edited after the fact | An append-only, hash-chained event/effect journal with end-to-end replay verification |
| Ad hoc review of a diff after the agent is done | A signed Change Passport: intent, authority, evidence, outcomes, and tool trust at one verifiable moment |
| Hope you can undo it if something goes wrong | A previewed recovery plan on a dedicated branch, executed only after a typed approval tied to that exact plan |

## What you can do

- **Wrap a real Git repository as a Change** with an explicit lifecycle (Draft → Active →
  Recovered/Verified, and others) and a contract: allowed/forbidden paths, required checks,
  maximum risk, and an authority ceiling.
- **Launch a top-level agent** — Claude, Codex, or any generic executable — under a kill-on-close
  Windows Job Object with a restricted access token (maximum privileges disabled). Every
  descendant process it spawns is attributed: PID, parent, image path, command line, lifetime,
  exit code.
- **Pause, resume, or stop a running agent.** Pause and resume act on the run's entire supervised
  process tree (not just the top-level PID), and stop terminates the whole tree as a unit.
- **Capture evidence before and after an agent runs**: a Git checkpoint (branch, head SHA, status
  digest, diff), an environment passport (tool versions, key facts, drift from baseline), and a
  dependency report (what changed, by ecosystem).
- **Discover and run an assurance plan** built from that real evidence, with coverage gaps
  reported honestly rather than a fabricated pass.
- **Delegate scoped, time-limited authority** between actors, and issue credential grants that
  are gated by an actual delegation — not just checked for the target existing.
- **Connect GitHub deliberately** (an environment variable or a hidden prompt, never a CLI
  argument) and open or close pull requests under a credential grant, with outcomes refreshed
  under the same authority model.
- **Register and trust tools** by exact version or publisher policy, with Authenticode signature
  verification and drift detection if a trusted tool's digest changes underneath it.
- **Build a Change Passport** — intent, authority, evidence, outcomes, tool trust, and a
  replay-verified trace, all in one canonical, digestible document — and **export it signed**
  with this operator's own Ed25519 key.
- **Preview a recovery plan** before anything happens, and execute it only after a human types an
  approval phrase tied to that specific plan, on a dedicated branch that never touches your
  current one.
- **Verify the entire event/effect journal's hash chain** end to end, on demand.
- **Drive all of the above from three clients** — a Textual terminal UI, a scriptable CLI, or a
  native Windows desktop app — against the same frozen OpenAPI contract, so nothing one client can
  do is a special case the others can't see.

## A typical workflow

1. Point Sentinel at a real Git repository and create a Change describing what you intend the
   agent to do.
2. Capture a baseline: Git checkpoint, environment, and dependency evidence, before anything runs.
3. Delegate the scopes an agent needs (launch, pause, resume) from a human actor, time-limited.
4. Launch the agent under process-tree supervision and restricted-token privilege reduction.
5. Capture current evidence and see exactly what changed against the baseline — Git diff,
   environment drift, dependency changes, every descendant process observed.
6. Discover and run an assurance plan; read the honestly reported facts, not an optimistic summary.
7. Build a Change Passport and export it signed, so anyone who trusts your public key can verify
   it wasn't altered afterward.
8. If something needs undoing, preview a recovery plan, approve it explicitly by name, and execute
   it on a dedicated branch — never silently, never on your current branch.

```text
Your repository + intent
    ↓
Change (lifecycle + contract)
    ↓
Baseline evidence (Git + environment + dependencies)
    ↓
Supervised agent launch (restricted token + Job Object, every descendant attributed)
    ↓
Current evidence + drift comparison
    ↓
Assurance plan + honestly-scored lifecycle facts
    ↓
Hash-chained journal (every mutation, tamper-evident, replay-verified)
    ↓
Signed Change Passport  ←――――――→  Recovery (previewed, approved, undone on a branch)
```

## Interfaces

Every interface below talks to the same backend through the same frozen contract — 66 operations
across 61 routes, described by 110 typed schemas.

- **Backend** (`backend/app`) — a local FastAPI service and the single source of truth. SQLite in
  WAL mode, bearer-token authenticated, loopback by default.
- **CLI** (`backend/app/cli`) — scriptable access to every operation, for automation and CI.
- **Terminal UI** (`backend/app/tui`, built with [Textual](https://textual.textualize.io/)) —
  full-screen control: evidence, agent runs (with live output and pause/resume), a branch/fork
  tree for checkpoint forking, passport, recovery, delegation, tool trust, and the event timeline.
- **Desktop app** (`apps/desktop`, Electron + React) — a native Windows shell with a bespoke
  screen for every one of the 66 API operations; contextually isolated, sandboxed, with the API
  token owned by the main process and never exposed to the renderer.

## Security posture

Sentinel's authority model isn't a formality bolted on afterward. A full attack-surface review
(credential broker, identity/delegation/policy, tool registry, execution/journal/replay,
recovery/passport, API auth boundary) covers 16 findings: 15 fixed and one closed as an accepted
design decision, with zero left open (see [`THREAT_MODEL_FINDINGS.md`](THREAT_MODEL_FINDINGS.md)).
A few of the load-bearing decisions:

- **No unrestricted authority by default.** Minting a credential grant requires a delegation that
  actually covers the requested scope and Change — not just a check that the target actor exists.
- **Restricted-token launch.** An agent's process starts with maximum privileges disabled via
  `CreateRestrictedToken`, and this is never silently skipped in favor of an unrestricted retry.
- **Never a fabricated success.** Suspend/resume independently verifies a process actually stopped
  consuming CPU rather than trusting the syscall's return code; an unsupported platform raises a
  stable error instead of pretending to succeed.
- **Tamper-evident by construction.** Every mutation and its journal event commit or roll back
  together in one transaction; the journal itself is append-only, hash-chained, and independently
  replay-verifiable.
- **Honest boundaries, stated as such.** Restricted-token privilege reduction is real but is
  explicitly never described as a sandbox or isolation boundary anywhere in this codebase's own
  copy — the difference between "meaningfully lowered privilege" and "cannot escape" is not
  blurred for marketing effect.

## Known limits

- **Windows-only** for process-tree supervision, restricted-token launch, and process
  suspend/resume. Other platforms get a stable, honest error — never a fabricated success.
- **No filesystem tracker.** File writes outside Git are not independently observed; this was a
  deliberate scope cut, not an oversight.
- **Not a sandbox (restricted-token mode).** Privilege reduction lowers what an agent's process
  can do; it provides no filesystem or network isolation and makes no such claim.
- **Container isolation exists for a narrow set of executables only.** An opt-in Docker-backed
  isolation mode (`execution/container_supervisor.py`) gives real filesystem isolation (only the
  repository is mounted in) and real network isolation (`--network none` by default), but only for
  executables with a configured Linux image (`python`/`node` today) — not the Windows-native
  `claude`/`codex` CLIs, which have no Linux equivalent here. It has no live output during a run
  and no pause/resume/stop support yet, and requires Docker installed and reachable; if it isn't,
  requesting container isolation fails with a stable error rather than silently using
  restricted-token instead.
- **No cross-agent container sharing.** A separate, unrelated idea from the isolation mode above —
  an external party receiving and acting on a Change's evidence or execution state. Threat-modeled
  but not implemented — no code, no routes, no new tables exist for it.
- **No MCP or descendant tool-call interception.** Only the top-level launched executable and
  explicitly declared tool manifests are tracked.
- **Descendant-process evidence is best-effort.** A process that starts and exits between two
  supervision polls can be missing from the attributed list.
- **Agent-run persistence isn't yet atomic with its journal write** the way most other mutations
  are — a documented, scoped architectural gap (see `THREAT_MODEL_FINDINGS.md`).
- **No TUI surface for launching or attaching an agent yet** — that path is CLI/API-only today;
  the TUI can view, pause, resume, and stop a run once it exists.
- **The desktop app is unsigned**, has no installer, and is Windows x64 only.
- **Single-operator model.** No multi-tenant data isolation — this is intentional, not a gap.
