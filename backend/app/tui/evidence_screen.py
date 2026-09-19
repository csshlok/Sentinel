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
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError


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


class EvidenceScreen(Screen):
    """Read-only Git/environment/dependency/assurance evidence for a Change."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str) -> None:
        super().__init__()
        self.change_id = change_id
        self.client = ApiClient(api_url)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static("Loading evidence...", id="evidence_view"))
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

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
