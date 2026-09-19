"""Interactive terminal UI (AC-7) — initial vertical slice: Change dashboard.

Sources all state through `backend.app.cli.client.ApiClient` only, the
same client the CLI uses, so the TUI never bypasses authentication,
policy, or lifecycle guards, and never invents readiness the API did
not report. This is a deliberately scoped first screen (Change list +
detail), not the full 8-panel spec in plan section 13.3 AC-7 — see
`backend/app/cli/AC_REMAINING_WORK.md` for exactly what remains.
"""
