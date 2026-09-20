"""Git/environment/dependency/assurance evidence panel (AC-7 items 3-4).

Consolidated into one screen (rather than four) to keep the surface
small while still covering every read-only evidence source `[KB]`'s
stream exposes. Each section renders "not captured yet" honestly when
the underlying route returns nothing, rather than omitting the section
silently.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError

_ACTIVE_STATUSES = {"RUNNING", "PAUSED"}
# How often the screen re-polls agent runs while this screen is open, so
# incrementally-captured stdout/stderr (Part C), a launch/pause/resume made
# elsewhere, and a brand-new run that didn't exist yet at the last poll all
# become visible without a manual refresh. Deliberately unconditional: an
# earlier version only re-polled once a run was *already* known to be
# RUNNING/PAUSED, which meant a run that started after this screen opened
# but before its first poll observed it was never noticed again without a
# manual refresh -- polling one open Change's evidence view every couple of
# seconds is cheap enough that the honesty is worth the requests.
_LIVE_POLL_INTERVAL_SECONDS = 2.0
_OUTPUT_TAIL_LINES = 20


def format_evidence(
    checkpoints: dict[str, Any] | None,
    environment: dict[str, Any] | None,
    dependencies: dict[str, Any] | None,
    assurance_plan: dict[str, Any] | None,
    assurance_facts: dict[str, Any] | None,
) -> str:
    lines = ["[bold]Git checkpoints[/bold]"]
    items = (checkpoints or {}).get("items", [])
    if not items:
        lines.append("  No Git checkpoints captured yet.")
    for item in items:
        lines.append(f"  - {item['name']}: {item['branch']} @ {item['head_sha'][:12]}")

    lines.append("")
    lines.append("[bold]Environment[/bold]")
    passport = (environment or {}).get("passport")
    if not passport:
        lines.append("  No environment passport captured yet.")
    else:
        drift = (environment or {}).get("drift")
        if drift:
            lines.append(
                f"  Drift: +{len(drift.get('added', []))} -{len(drift.get('removed', []))} "
                f"~{len(drift.get('changed', []))} ?{len(drift.get('unknown', []))}"
            )
        else:
            lines.append("  Passport captured; no drift comparison yet.")

    lines.append("")
    lines.append("[bold]Dependencies[/bold]")
    dep_changes = (dependencies or {}).get("changes", [])
    if not dep_changes:
        lines.append("  No dependency changes recorded yet.")
    for change in dep_changes:
        lines.append(
            f"  - {change['ecosystem']}/{change['package']}: "
            f"{change.get('old_version')} -> {change.get('new_version')}"
        )
    for eco in (dependencies or {}).get("unsupported_ecosystems", []):
        lines.append(f"  [yellow]! unsupported ecosystem: {eco}[/yellow]")

    lines.append("")
    lines.append("[bold]Assurance[/bold]")
    checks = (assurance_plan or {}).get("checks", [])
    if not checks:
        lines.append("  No assurance plan created yet.")
    for check in checks:
        marker = "(required)" if check.get("required") else "(optional)"
        lines.append(f"  - {check['name']} {marker}: {check.get('rationale', '')}")
    for gap in (assurance_plan or {}).get("coverage_gaps", []):
        lines.append(f"  [yellow]! coverage gap: {gap}[/yellow]")

    if assurance_facts:
        lines.append("")
        lines.append("[bold]Lifecycle-gating facts (from fresh evidence only)[/bold]")
        for key in (
            "required_assurance_passed",
            "assurance_fresh",
            "deviations_resolved",
            "required_evidence_complete",
        ):
            value = assurance_facts.get(key, False)
            marker = "[green]yes[/green]" if value else "[red]no[/red]"
            lines.append(f"  {key}: {marker}")
        for reason in assurance_facts.get("reasons", []):
            lines.append(f"    ! {reason}")

    return "\n".join(lines)


def _tail(text: str, lines: int) -> str:
    if not text:
        return "(no output yet)"
    parts = text.splitlines()
    shown = parts[-lines:]
    prefix = f"... ({len(parts) - len(shown)} earlier line(s) omitted) ...\n" if len(parts) > lines else ""
    return prefix + "\n".join(shown)


def _run_status_label(status: str) -> str:
    color = {"RUNNING": "cyan", "PAUSED": "yellow", "PASSED": "green",
             "FAILED": "red", "ERROR": "red", "TIMED_OUT": "red",
             "CANCELLED": "grey50", "ATTACHED": "white"}.get(status, "white")
    return f"[{color}]{status}[/{color}]"


class EvidenceScreen(Screen):
    """Git/environment/dependency/assurance evidence plus agent-run control.

    Agent runs are listed with a live-updating output tail (Part C: the
    screen polls on its own at a fixed interval regardless of run state --
    no push/streaming transport, matching the operator's own scoping
    decision -- so a run started, paused, or resumed from elsewhere is
    always noticed without a manual refresh) and Pause/Resume/Stop actions
    (Part A: when the run has a supervised Job Object, pause/resume acts on
    every process currently in it, not the top-level PID alone -- see
    `AgentLauncher._tree_pids`. Stop terminates the whole supervised Job
    Object tree when available; the run detail discloses both descendant
    evidence and the restricted-token boundary.
    """

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str, actor_id: str | None = None) -> None:
        super().__init__()
        self.change_id = change_id
        self.actor_id = actor_id
        self.client = ApiClient(api_url)
        self._run_ids: list[str] = []
        self._runs_by_id: dict[str, dict[str, Any]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Loading evidence...", id="evidence_view"),
            Static("[bold]Agent runs[/bold]"),
            DataTable(id="agent_runs"),
            Static("", id="agent_output"),
            Horizontal(
                Button("Pause", id="pause", disabled=True),
                Button("Resume", id="resume", disabled=True),
                Button("Stop", id="stop", variant="error", disabled=True),
            ),
            Static("", id="agent_result"),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#agent_runs", DataTable)
        table.add_columns("Adapter", "Status", "PID", "Desc.", "Exit", "Duration (ms)")
        table.cursor_type = "row"
        if not self.actor_id:
            self.query_one("#agent_result", Static).update(
                "[yellow]No actor id configured; pause/resume/stop require an "
                "authenticated actor. Launch the TUI with --actor-id.[/yellow]"
            )
        self.action_refresh()
        self.set_interval(_LIVE_POLL_INTERVAL_SECONDS, self._poll_tick)

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    def _poll_tick(self) -> None:
        self.action_refresh()

    def _fetch_or_none(self, call) -> Any:
        try:
            return call()
        except (ApiConnectionError, ApiError):
            return None

    def _load(self) -> None:
        view = self.query_one("#evidence_view", Static)
        checkpoints = self._fetch_or_none(lambda: self.client.list_git_checkpoints(self.change_id))
        environment = self._fetch_or_none(lambda: self.client.get_environment(self.change_id))
        dependencies = self._fetch_or_none(lambda: self.client.get_dependencies(self.change_id))
        assurance_plan = self._fetch_or_none(
            lambda: self.client.get_latest_assurance_plan(self.change_id)
        )
        assurance_facts = self._fetch_or_none(
            lambda: self.client.get_assurance_facts(self.change_id)
        )
        text = format_evidence(checkpoints, environment, dependencies, assurance_plan, assurance_facts)
        self.app.call_from_thread(view.update, text)

        runs_payload = self._fetch_or_none(lambda: self.client.list_agent_runs(self.change_id))
        runs = (runs_payload or {}).get("items", [])
        self.app.call_from_thread(self._render_runs, runs)

    def _render_runs(self, runs: list[dict[str, Any]]) -> None:
        table = self.query_one("#agent_runs", DataTable)
        previous_selection = self._run_ids[table.cursor_row] if (
            self._run_ids and table.cursor_row is not None and table.cursor_row < len(self._run_ids)
        ) else None
        table.clear()
        self._run_ids = [run["id"] for run in runs]
        self._runs_by_id = {run["id"]: run for run in runs}
        for run in runs:
            table.add_row(
                run.get("adapter", ""), _run_status_label(run.get("status", "")),
                run.get("top_level_pid") or "-", len(run.get("descendant_processes", [])),
                run.get("exit_code") if run.get("exit_code") is not None else "-",
                run.get("duration_ms") if run.get("duration_ms") is not None else "-",
            )
        if previous_selection in self._run_ids:
            table.cursor_coordinate = (self._run_ids.index(previous_selection), 0)
        self._render_selected_output()
        self._update_run_buttons()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        del event
        self._render_selected_output()
        self._update_run_buttons()

    def _selected_run(self) -> dict[str, Any] | None:
        table = self.query_one("#agent_runs", DataTable)
        if not self._run_ids or table.cursor_row is None:
            return None
        try:
            return self._runs_by_id.get(self._run_ids[table.cursor_row])
        except IndexError:
            return None

    def _render_selected_output(self) -> None:
        run = self._selected_run()
        output = self.query_one("#agent_output", Static)
        if run is None:
            output.update("")
            return
        stdout_tail = _tail(run.get("stdout", ""), _OUTPUT_TAIL_LINES)
        stderr_tail = run.get("stderr", "")
        text = f"[bold]stdout (last {_OUTPUT_TAIL_LINES} lines)[/bold]\n{stdout_tail}"
        if stderr_tail:
            text += f"\n\n[bold]stderr[/bold]\n{_tail(stderr_tail, _OUTPUT_TAIL_LINES)}"
        control = "available" if run.get("descendant_control_available") else "unavailable"
        text += f"\n\n[bold]Process-tree supervision[/bold]: {control}"
        if run.get("authority_reduction"):
            text += f"\n{run['authority_reduction']}"
        descendants = run.get("descendant_processes", [])
        if descendants:
            text += "\n[bold]Observed descendants[/bold]"
            for process in descendants:
                identity = process.get("executable_path") or process.get("attribution_reason") or "unknown"
                text += f"\n  - PID {process['pid']} (parent {process.get('parent_pid') or '-'}): {identity}"
        output.update(text)

    def _update_run_buttons(self) -> None:
        run = self._selected_run()
        status = run.get("status") if run else None
        have_actor = bool(self.actor_id)
        self.query_one("#pause", Button).disabled = not (have_actor and status == "RUNNING")
        self.query_one("#resume", Button).disabled = not (have_actor and status == "PAUSED")
        self.query_one("#stop", Button).disabled = not (have_actor and status in _ACTIVE_STATUSES)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("pause", "resume", "stop"):
            self._control_selected(event.button.id)

    def _control_selected(self, action: str) -> None:
        run = self._selected_run()
        if run is None or not self.actor_id:
            return
        self.run_worker(
            lambda: self._submit_control(run["id"], action), thread=True, exclusive=True
        )

    def _submit_control(self, run_id: str, action: str) -> None:
        result = self.query_one("#agent_result", Static)
        try:
            if action == "pause":
                self.client.pause_agent(self.change_id, run_id, actor_id=self.actor_id)
            elif action == "resume":
                self.client.resume_agent(self.change_id, run_id, actor_id=self.actor_id)
            else:
                self.client.stop_agent(self.change_id, run_id, actor_id=self.actor_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(result.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(result.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.app.call_from_thread(result.update, f"{action.capitalize()} requested for {run_id}.")
        self._load()
