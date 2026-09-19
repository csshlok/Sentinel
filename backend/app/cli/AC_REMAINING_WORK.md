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

**Not yet done**, in the order the plan lists them (section 13.3 AC-7):

1. Change **detail** view (drill into one row: full evidence, contract, delegations).
2. Lifecycle **stepper** widget reflecting `ChangeLifecycleState`/`LifecycleFacts`.
3. Git/dependency evidence **tables** (checkpoints, dependency changes).
4. Assurance progress/results panel.
5. PR/CI **outcome** panel (`OutcomeListResponse`).
6. Guided **Change Contract** and **delegation** creation forms (currently CLI-only via `delegation create`).
7. **Recovery preview/confirmation** screen — this is the highest-value remaining piece: `GitRecoveryEngine` already returns a `RecoveryPlan` with `unsupported_effects`/`conflicts`/`actions[].supported`, which is exactly the data a confirmation screen needs; it just needs a Textual screen with an explicit approve/cancel action wired to `POST .../recovery/{plan_id}/execute`.
8. **Passport export** screen/keybinding (`PassportBuilder` already produces byte-stable canonical JSON).
9. Interaction-test coverage with Textual's `Pilot`/`run_test()` — **not yet added** because this project has no async pytest runner configured (`pytest-asyncio`/`anyio` pytest mode is not in `pyproject.toml`'s test extras). Adding that is a small, safe dependency addition `[SD]` can make alongside any future `pyproject.toml` change; until then, TUI testing is limited to synchronous unit tests of pure logic and construction, not actual keyboard/rendering interaction.
10. Small-terminal/resize, `NO_COLOR`/`--no-color`, and plain non-TTY behavior for the TUI specifically (the CLI already has this; the TUI inherits Textual's own terminal-capability detection but this has not been manually verified at 80x24/120x30 per the plan's acceptance requirement).

## Recommended next step

Pick up at item 7 (recovery preview/confirmation) — it is the single
screen with the highest product value per the "killer demo" framing in
the original proposal, and every piece of backend logic it needs
already exists and is tested.
