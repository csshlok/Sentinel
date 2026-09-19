# Person 2 foundation hardening handoff

`[kb] HANDOFF to [SD]` — reviewed 2026-09-19 00:01 -04:00

Status: existing-port hardening ready for independent review; KB-1 through KB-6
are **not** stream-complete. The five new shared ports remain absent.

The user confirmed that this session is Person 2 and instructed it to continue
owned work. This is not an invented `[SD]` comprehension acknowledgement. The
comprehension statement and requested shared contracts are in `PROJECT_CONTEXT.md`.

## Claimed implementation

- `backend/app/git/adapter.py`
- `backend/app/execution/__init__.py`
- `backend/app/execution/_process.py`
- `backend/app/execution/runner.py`
- `backend/tests/git/test_git_adapter.py`
- `backend/tests/git/test_hardening.py`
- `backend/tests/execution/__init__.py`
- `backend/tests/execution/test_runner.py`
- This owner-local handoff document.

The context documents were updated under the user's original explicit request.
Existing Git startup-error edits were preserved; their regression test now mocks
`Popen`, matching the new process boundary. The user subsequently requested removal
of `.vscode/settings.json`; it was deleted locally and was never tracked. No shared
contracts, core, migrations, composition, dependency manifests, or other person's
feature code were edited. The reviewed work is split into three commits:

1. `5bf01cb` — `[kb] 2026-09-19T00:01:24-04:00 Add bounded execution foundation`.
2. `47ea584` — `[kb] 2026-09-19T00:01:32-04:00 Harden read-only Git evidence`.
3. The documentation commit containing this handoff and both context updates.

## Assigned-work review and milestones

The user requested `[kb]` tags, timestamps, and milestone progress reports for
subsequent Person 2 work. This preference applies to this contributor's updates
and commit messages; it does not change other contributors' ownership.

| Assignment | Reviewed state | Remaining work |
| --- | --- | --- |
| KB-0 architecture audit | Partial: proposal mapping, compatibility audit and Git/process fixtures present | New-port contract fakes and multi-ecosystem fixtures after interface freeze |
| KB-1 Git checkpoints | Partial: existing inspector hardened and tested | `GitStatePort`, persisted checkpoint identity, comparisons and full freshness model |
| KB-2 Agent Launcher | Partial: bounded execution primitive tested | `AgentLauncherPort`, generic/Codex/Claude adapters, attach/cancel, authority and idempotency |
| KB-3 Environment Passport | Not implemented; shared contract absent | `EnvironmentPort`, collectors, redaction/fingerprint policy and drift models |
| KB-4 Dependency Tracker | Not implemented; shared contract absent | `DependencyPort`, frozen manifest/lock formats, parsers, comparison and risk |
| KB-5 Assurance engine | Not implemented; shared contract absent | `AssurancePort`, discovery, selection, reporters, freshness, deviations and coverage |
| KB-6 stream hardening | Existing-port tests/review complete | Full-stream tests and `[SD]` acceptance after the remaining work |

Review milestone 1 completed 2026-09-19 00:00 -04:00: assignment audit and settings
removal. Numeric-bound review found fractional byte limits and non-finite timeouts
were not consistently rejected. The collector now requires finite positive timeouts
up to 300 seconds and integer byte limits up to eight MiB; public verification and
patch limits remain zero through one MiB. Booleans, strings, null and fractional
byte counts fail before process startup. Regression tests cover these cases.

Review milestone 2 completed 2026-09-19 00:01 -04:00: the complete suite passed
with the coverage below. Review milestone 3 groups the verified implementation and
documentation into the three requested commits. This self-review is not independent
`[SD]` acceptance or a claim of complete retained-proposal functionality.

## Consumed interfaces

- `GitInspectionPort.validate_repository` and `.inspect`.
- `VerificationPort.run` and existing Pydantic request/result models.
- `AppError` for safe domain failures.
- `ports.py` SHA-256: `5e17c9dc1544944ff96eacecbd396ba6d315b0ce682aab2e07e35606461fa0ee`.
- `models.py` SHA-256: `a469512f3b3e60dc94a4d2106afa47adc5ce94d5ac38b73bb9334c8debe532f7`.

`CapturedProcess` is a private subprocess implementation detail. It is not a new
shared domain model or an alternative to `AgentLauncherPort`.

## Implemented behavior

Git captures now have bounded in-memory output and full streaming diff hashes.
Metadata above eight MiB fails explicitly rather than returning partial state;
patch prefixes support zero through one MiB. Malformed records, invalid numeric
statistics, duplicate paths, bad encodings and unsupported repository identities
have stable domain failures. Untracked file contents remain unread.

Git disables optional index writes, external diff, text conversion, filesystem
monitor commands, and configured content-filter commands. Inherited Git overrides
cannot redirect the selected repository. Normal Git configuration, including
Windows line-ending rules, remains effective. Active content filters and submodules
are explicitly rejected: disabling filters can change diff semantics, and nested
repository configuration can execute independent commands. The legacy summary
cannot describe those incomplete evidence states honestly.

Inspection compares repository identity, porcelain status, numstat and full patch
hashes across repeated reads. Observed movement returns an error requiring refresh.
This is a best-effort instability check, **not an atomic checkpoint**. Concurrent
changes that return to the same observable state, binary-content changes with an
unchanged textual diff, and index-only content changes with identical summaries
cannot be ruled out by this legacy model.

`BoundedVerificationRunner` implements the existing verification port. It validates
commands, arguments, directory and output limits; removes inherited credential and
interpreter-injection variables; resolves native executables outside the selected
repository; and pins Python to the daemon interpreter. Repository and relative PATH
entries are removed. Windows `.cmd`/`.bat` wrappers are rejected pending reviewed
native adapters.

The pipe reader uses a single shared retention budget and hashes stdout while
discarding excess bytes. It does not use output files, reader threads, or
`communicate()` buffers. Stdout/stderr are separate bounded prefixes, not an
interleaved execution timeline. Timeout terminates only the direct child. If a
descendant keeps a pipe open after the direct child exits, the call ends at its
deadline with incomplete/error evidence rather than hanging or claiming cleanup.
Startup/read/setup failures are sanitized. Invalid UTF-8 is visibly marked as
truncated/lossy.

This is an execution primitive for explicitly authorized checks, not the completed
Agent Launcher. It does not provide launch/attach/cancel APIs, delegations,
idempotency, durable run storage, credential brokering, a sandbox, or unrestricted
output-secret detection. Callers must not submit secrets as command arguments;
commands still have the current user's filesystem and OS privileges.

## Verification

Baseline before this continuation: `python -m pytest` — 49 passed.

Final command:

```text
python -m coverage run --branch --source=backend/app/git,backend/app/execution -m pytest
python -m coverage report -m
```

Result after re-review: **150 passed in 28.96 seconds**, no skipped or xfailed tests. Both owner
packages have **100% statement and 100% branch coverage**: 445 statements and
178 branches combined, no exclusions. Coverage was installed in the local Python
environment; no root dependency configuration was changed.

Real Windows boundaries exercised: disposable committed repositories, staged and
unstaged changes, rename/delete/binary files, Unicode and spaced paths, a real
merge conflict, detached/unborn repositories, submodules, filter/hook suppression,
byte-and-mtime comparison of all fixture files, concurrent edit injection, and
native Python subprocesses with pass/fail/timeout/large-output behavior. Synthetic
secret canaries prove removal of inherited environment keys. Fault injections
cover malformed Git output, startup errors, missing tools, bad encodings and
partial subprocess evidence.

The owner-local API flow injects the new runner via the existing `create_app`
factory, exercises create -> edit -> refresh -> verify, reopens SQLite through a
second app instance, and proves refresh clears the saved verification. It uses
real Git, subprocesses and SQLite, not production success fakes. This verifies the
existing review workflow, not the retained proposal's complete lifecycle.

Platform: Windows, Python 3.14. No Linux/macOS, interactive terminal, real agent,
provider account, environment collector, or Node reporter smoke test is claimed.

## Integration and remaining gates

1. Independently review the existing-port changes and add acceptance probes.
2. To evaluate the new runner, inject
   `backend.app.execution.runner.BoundedVerificationRunner()` through
   `create_app(verification=...)`; its constructor takes no arguments. Production
   composition still uses the older runner and was not edited here.
3. Freeze `GitStatePort`, `AgentLauncherPort`, `EnvironmentPort`, `DependencyPort`
   and `AssurancePort`, their immutable evidence/authority models and contract tests.
4. Supply authority/idempotency and persistence boundaries; specify supported
   manifest/lock versions, structured reporters and attach/cancel semantics.
5. Person 2 can then complete checkpoint persistence/comparison, agent adapters,
   environment passports, dependency analysis, assurance selection/deviation and
   the complete stream handoff without inventing private integration contracts.

No independent `[SD]` acceptance or whole-stream readiness is claimed.

Implementation references: [Python nonblocking pipes](https://docs.python.org/3/library/os.html#os.set_blocking),
[Git diff command controls](https://git-scm.com/docs/git-diff),
and [Git environment controls](https://git-scm.com/docs/git).
