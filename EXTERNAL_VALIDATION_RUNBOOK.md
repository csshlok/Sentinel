# External validation runbook (invasive tier)

These four require installing system-level monitoring software or running real attack-technique
simulations. None of them were run against the maintainer's real development machine — do these in
a disposable Windows VM, not your daily driver, since Sysmon installs a persistent kernel-mode
service and Atomic Red Team's tests genuinely perform the behaviors they simulate (registry writes,
simulated persistence, etc.), even though individual atomics are designed to be revertable.

## 1. Sysmon ground-truth comparison

**Why:** independent, Microsoft-authored process telemetry to compare Sentinel's own observation
against, instead of a list Sentinel's own author wrote.

1. Download Sysmon from [Microsoft Sysinternals](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon)
   and install with a config that logs Event ID 1 (process create) and 5 (process terminate):
   `sysmon64.exe -i -accepteula`.
2. Run a batch of real Sentinel-supervised agent launches (reuse the pattern in this repo's own
   benchmark scripts — e.g. `backend/tests/execution/test_process_supervisor.py` for the launch
   shape) — aim for hundreds of launches with varied process-tree depth and lifetime, not dozens.
3. Pull the ground truth: `Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Sysmon/Operational'; Id=1,5}`.
4. Compare Sysmon's `ProcessGuid`/`ParentProcessGuid`/`Image`/`CommandLine` per PID against
   Sentinel's `descendant_processes` for the same run window (match by PID + narrow time window,
   since PIDs are reused).
5. Report: process recall (Sentinel-observed ÷ Sysmon-observed), executable-path agreement,
   command-line agreement, parent-PID agreement, false positives (Sentinel reporting a process
   Sysmon never saw).
6. Uninstall when done: `sysmon64.exe -u`.

## 2. Process Monitor cross-check

**Why:** an independent view of filesystem/registry activity, which directly tests whether the
"no filesystem tracker" limitation is actually true rather than just documented.

1. Run [Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon)
   alongside a real Sentinel evidence-capture + agent-launch flow on the same repository.
2. Filter Procmon to the launched process tree's PIDs.
3. Compare: does every Git-tracked file mutation Procmon observed show up in Sentinel's evidence
   (checkpoint diff)? Does every *non*-Git file write Procmon observed correctly *not* appear in
   Sentinel's evidence (confirming the documented limitation empirically, not just by claim)?

## 3. Atomic Red Team evidence coverage

**Why:** standardized, MITRE ATT&CK-mapped behaviors this project didn't invent — the question
isn't "did Sentinel detect an attack" (it isn't EDR), it's "did Sentinel produce accurate evidence
of what actually happened."

1. Install [`Invoke-AtomicRedTeam`](https://github.com/redcanaryco/invoke-atomicredteam) in the VM.
2. Select a safe, non-destructive subset of Windows atomics (the project ships a `Test-AtomicsIsElevated`-style guard and per-test risk notes — read each one before running it).
3. Launch each atomic test *as a Sentinel-supervised agent run* rather than standalone.
4. For each test, record: was the process observed, was it fully attributed, was any relevant
   environment/dependency drift captured, did the journal stay verifiable, did a Passport build
   successfully afterward.
5. Report as a coverage table (tests run / process observed / fully attributed / drift captured /
   journal verified), explicitly framed as evidence-completeness, not detection efficacy.

## 4. MITRE Caldera workflow reconstruction

**Why:** multi-step adversary workflows test Sentinel's actual thesis — reconstructing what an
autonomous agent did across a whole session, not just one isolated action.

1. Stand up [Caldera](https://github.com/mitre/caldera) in the VM (server + one agent).
2. Run a handful of built-in adversary profiles as Sentinel-supervised agent sessions.
3. Report process-chain reconstruction accuracy, environment/dependency drift recall, and journal
   completeness across whole multi-stage workflows, the same shape as the Atomic Red Team table
   but for sequences instead of isolated actions.

## Also worth doing, lower urgency

- **TruffleHog-backed secret corpus**: build ~500 synthetic secrets across ~50 provider formats
  (TruffleHog's own detector list is a good source of realistic formats), run each through common
  transformations (base64, hex, URL-encoding, splitting), and measure Sentinel's redaction recall
  against that corpus instead of the 10 hand-picked strings in this page's current benchmark.
  Doesn't need a VM — safe to run anywhere.
- **OpenSSF Scorecard**: run `scorecard --local .` against this repository for an independent
  rating of its own security practices (branch protection, dependency pinning, etc.) — tests the
  project's process, not Sentinel's runtime behavior. Doesn't need a VM.
- **Independent adversarial review**: give someone who didn't write this code the threat model and
  a VM, and ask them to try to make the evidence wrong (tamper, missing descendants, PID reuse,
  secret exfiltration, journal corruption, privilege escape, malformed API calls). This is the one
  item on this list that can't be self-administered by design — it needs an actual second person.
