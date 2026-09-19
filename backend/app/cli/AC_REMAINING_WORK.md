# Person 3 remaining work: AC-6 (scriptable CLI) and AC-7 (interactive terminal UI)

`[AC] CONTRACT CHANGE REQUEST to [SD]` and remaining-work record — 2026-09-19 00:50:26 -04:00

Status: AC-0 through AC-5 are complete and pushed (see `OVERALL_CONTEXT.md` and
`PROJECT_CONTEXT.md` for the full record and commit list). AC-6 and AC-7 are
**blocked**, not merely unstarted. This document is the single place that says
exactly what is missing and exactly what unblocks it, so any contributor
(including a future session of `[AC]`) can pick this up without re-deriving it.

## Why this is a document and not code

Building a placeholder CLI or a hand-rolled terminal UI just to have *something*
under `backend/app/cli/` and `backend/app/tui/` would be the "no safety theater"
violation this project explicitly forbids: it would present unsupported or
throwaway capability as if it were the real thing. This document exists instead
of that code.

## Blocker 1: missing dependencies

`pyproject.toml` currently declares only `fastapi`, `pydantic`, `uvicorn`, and
the `test` extras (`httpx`, `pytest`, `pytest-cov`). The plan (section 5) requires:

- `typer` — scriptable CLI commands and routing (AC-6).
- `rich` — colour, tables, panels, progress, status semantics (AC-6 output, AC-7 rendering).
- `textual` — the keyboard-driven interactive terminal application (AC-7).

Root dependency manifests are `[SD]`-owned per `AGENT_COORDINATION.md`
("Root configuration, dependency manifests... are single-editor resources
owned by `[SD]`... `[KB]` and `[AC]` submit requested dependency/configuration/
doc wording in a handoff"). This document **is** that handoff request:

```
[AC] CONTRACT CHANGE REQUEST to [SD]
Contract/version: pyproject.toml dependencies
Reason: AC-6/AC-7 cannot be implemented per plan section 5 without these.
Proposed compatible change:
  [project.dependencies] += "typer>=0.15,<1", "rich>=13,<15"
  a new [project.optional-dependencies] group, e.g. "tui", += "textual>=0.85,<1"
Affected consumers/tests: backend/app/cli/ and backend/app/tui/ (not yet
  created beyond this document), plus their test suites once dependencies land.
```

## Blocker 2: most of the API surface AC-6 would call does not exist yet

AC-6 requires implementing commands "through the local API client only... do
not import persistence/services to bypass authentication, policy, or lifecycle
guards." The current live API (`backend/app/core/router.py`) only exposes:

- `GET /api/v1/capabilities`
- `POST /api/v1/repositories/validate`
- `POST /api/v1/changes`, `GET /api/v1/changes`, `GET /api/v1/changes/{id}`
- `PUT /api/v1/changes/{id}/contract`
- `POST /api/v1/changes/{id}/transition`, `.../cancel`, `.../refresh`, `.../verify`
- `DELETE /api/v1/changes/{id}`

None of the AC-owned domains have routes yet: no `/api/v1/actors`,
`/api/v1/delegations`, `/api/v1/providers/github`, `/api/v1/changes/{id}/outcomes`,
`/api/v1/changes/{id}/recovery`, or `/api/v1/changes/{id}/passport`. Per the
plan's Gate 3, wiring those routes is `[SD]`'s job, and it happens only after
both `[KB]`'s and `[AC]`'s stream-complete handoffs pass independent review
(Gate 2). Concretely, today a CLI can only meaningfully wrap the 7 routes
above — `assure`, `outcome`, `recovery`, and `passport` subcommands would have
nothing to call.

## What is already reusable once both blockers clear

No new design work is needed to start AC-6/AC-7 once dependencies and routes
exist — the following are already built, tested, and just need HTTP routes in
front of them:

| AC-6/AC-7 concept | Backing implementation (already done) |
| --- | --- |
| `assure`/policy display | `backend.app.policy.service.DelegationPolicyEngine` |
| `outcome` | `backend.app.outcomes.outcome_port.GitHubOutcomeTracker` |
| `recovery preview/approve` | `backend.app.recovery.git_recovery.GitRecoveryEngine` (already returns a `RecoveryPlan` with `unsupported_effects`/`conflicts` — exactly what a preview screen renders) |
| `passport export` | `backend.app.passport.builder.PassportBuilder` (already produces byte-stable canonical JSON — exactly what `passport export --json` needs) |
| credential status | `backend.app.credentials.broker.CredentialBroker` (never exposes the raw secret — safe to surface grant metadata in a CLI/TUI) |

## Recommended order once unblocked

1. **Gate 3 wiring** (`[SD]`): add routes for identity/delegations, provider/
   outcomes, recovery, and passport to `backend/app/core/router.py`, following
   the exact same thin-transport pattern already used for `changes`.
2. **AC-6**: `backend/app/cli/client.py` — an API client. Reuse
   `backend.app.providers.http_transport.HttpTransport`/`UrllibHttpTransport`
   (already generic, not GitHub-specific) rather than writing a new HTTP layer.
3. **AC-6**: `backend/app/cli/main.py` — Typer app wrapping the client; stable
   exit codes; `--json` mode with one documented machine-readable object and no
   decoration; `NO_COLOR`/`--no-color` respected from the start, not retrofitted.
4. **AC-7**: `backend/app/tui/` — Textual app consuming the same API client as
   the CLI (never persistence/services directly), covering the screens listed
   in plan section 13.3 AC-7 (Change dashboard, lifecycle stepper, evidence
   cards, Git/dependency tables, assurance/PR/CI panels, contract/delegation
   forms, recovery preview/confirmation, Passport export).
5. **AC-8**: re-run stream hardening once AC-6/AC-7 exist, updating the
   handoff in `OVERALL_CONTEXT.md`/`PROJECT_CONTEXT.md`.

## What would NOT be a reasonable substitute

- Adding `typer`/`rich`/`textual` to `pyproject.toml` directly from this
  session: crosses `[SD]`'s exclusive ownership of root configuration and
  risks a real conflict with `[SD]`'s active commits to this same file.
- A CLI built with only stdlib `argparse` against the 7 existing routes: would
  need substantial rework once Gate 3 lands the real surface, and covers a
  small fraction of AC-6's actual scope (no `assure`/`outcome`/`recovery`/
  `passport` commands are possible without those routes regardless of CLI
  framework).
- A hand-rolled ANSI terminal screen approximating Textual's interactive
  experience: would misrepresent an unsupported capability as supported.
