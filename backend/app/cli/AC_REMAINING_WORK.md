# Person 3 remaining work: AC-6 (scriptable CLI) and AC-7 (interactive terminal UI)

Updated 2026-09-19 — both original blockers are resolved. `[SD]`'s
`c616f37` added `typer`/`rich`/`textual` to `pyproject.toml` per the
contract-change request below and wired Gate 3 routes for every AC
domain. AC-6 is now complete. AC-7 has a real, working first screen;
the rest of its spec is what remains.

## AC-6: complete

`backend/app/cli/`:

- `client.py` — `ApiClient`, a thin JSON client over the generic
  `HttpTransport` seam from `backend.app.providers` (no new HTTP
  dependency). Every CLI command goes through this client and the real
  API only.
- `main.py` — Typer app: `capabilities`, `validate`, and `change`/
  `actor`/`delegation`/`github`/`outcome`/`recovery`/`passport`
  command groups, one per Gate-3 route. Stable exit codes (0 success,
  1 API error, 2 connection error). `--json` prints exactly one
  machine-readable object. `--no-color`/`NO_COLOR`/non-TTY output all
  disable Rich styling from a single `_console()` helper.
- Run with `python -m backend.app.cli` (see `__main__.py`).

Tests: `backend/tests/cli/` — `test_client.py` (success, error-envelope
mapping, connection-timeout mapping, 204 handling, idempotency header),
`test_main.py` (JSON output, API-error exit code 1, connection-error
exit code 2, `NO_COLOR` disabling ANSI codes, a full create→list flow,
recovery-execute argument passing), and `test_smoke.py` — one real
end-to-end test against a live `uvicorn` server (ephemeral port, real
temporary Git repo, real SQLite), not a fake, proving the CLI actually
works against the real Gate-3-wired API.

## AC-7: first vertical slice done, most of the spec remains

`backend/app/tui/app.py` — `ChangeDashboard`, a working Textual app:
lists Changes via the same `ApiClient` (never persistence/services
directly), with a lifecycle-state column that pairs a symbol with a
colour (`state_label()`; colour is never the only signal), a refresh
binding (`r`), and honest empty/error/connection-failure states — no
fabricated data. `backend/tests/tui/test_app.py` covers the pure
`state_label()` formatting and app/client construction.

**Done since the last update:**

7. **Recovery preview/confirmation** screen — `backend/app/tui/recovery_screen.py`'s `RecoveryScreen`. Pressing `v` on a selected row in `ChangeDashboard` pushes it. It previews the real `RecoveryPlan` (`format_plan()`, a pure/tested function: supported vs. blocked actions, conflicts, unsupported effects — never a fabricated "safe" summary), requires a non-empty typed approval token before "Confirm Recovery" enables (approval is never inferred), and calls the real `POST .../recovery/{plan_id}/execute` on confirm. `ChangeDashboard` now takes an `actor_id` (via `--actor-id` on `python -m backend.app.tui.app`); without one, the screen shows an explicit unsupported-state message instead of silently proceeding. Tests: `backend/tests/tui/test_recovery_screen.py` (5 tests, all on the pure `format_plan()` logic and construction).

**Still not done**, in the order the plan lists them (section 13.3 AC-7):

1. Change **detail** view (drill into one row: full evidence, contract, delegations).
2. Lifecycle **stepper** widget reflecting `ChangeLifecycleState`/`LifecycleFacts`.
3. Git/dependency evidence **tables** (checkpoints, dependency changes).
4. Assurance progress/results panel.
5. PR/CI **outcome** panel (`OutcomeListResponse`).
6. Guided **Change Contract** and **delegation** creation forms (currently CLI-only via `delegation create`).
7. ~~Recovery preview/confirmation screen~~ — done, see above.
8. ~~Passport export screen/keybinding~~ — done: `backend/app/tui/passport_screen.py`'s `PassportScreen`, pushed via a new `p` binding on the dashboard. Loads the latest passport (honest `PASSPORT_NOT_FOUND` empty state, not an error, when none exists yet), `b` builds a fresh one through the real `POST .../passport` route, `e` exports the exact payload the API returned to `passport-<change_id>.json` as canonical indented JSON. `format_passport()` is a pure, tested formatting function. Tests: `backend/tests/tui/test_passport_screen.py` (5 tests).
9. Interaction-test coverage with Textual's `Pilot`/`run_test()` — **still not added** because this project has no async pytest runner configured (`pytest-asyncio`/`anyio` pytest mode is not in `pyproject.toml`'s test extras). All TUI tests so far (dashboard, recovery screen, passport screen) are synchronous unit tests of pure logic and construction, not actual keyboard/rendering interaction — that remains an honest, documented gap.
10. Small-terminal/resize, `NO_COLOR`/`--no-color`, and plain non-TTY behavior for the TUI specifically (the CLI already has this; the TUI inherits Textual's own terminal-capability detection but this has not been manually verified at 80x24/120x30 per the plan's acceptance requirement).

## Recommended next step

Item 6 (guided Change Contract / delegation creation forms) is the
largest remaining functional gap — everything else left is either a
read-only evidence panel (items 1-5) or cross-cutting test/terminal
hardening (items 9-10).
