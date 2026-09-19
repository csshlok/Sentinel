"""Read-only causal timeline (trace-only replay) for a Change.

Renders every `journal_events` row for the Change in `seq` order with a
persistent chain-verification badge. `chain_verified: false` is a first-class,
clearly rendered state (colour-plus-symbol, matching every other screen's
convention), never hidden -- honesty about tamper detection is the entire
point of this screen.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError


def _verified_badge(chain_verified: bool, first_break_seq: int | None) -> str:
    if chain_verified:
        return "[green]* verified[/green]"
    detail = f" (first break at seq {first_break_seq})" if first_break_seq is not None else ""
    return f"[red]x TAMPER DETECTED{detail}[/red]"


def format_timeline(timeline: dict[str, Any] | None) -> str:
    if not timeline:
        return "No timeline available (the Change may not exist, or the API could not be reached)."

    lines = [
        f"[bold]Causal timeline[/bold]  {_verified_badge(timeline.get('chain_verified', False), timeline.get('first_break_seq'))}",
        "",
    ]
    events = timeline.get("events", [])
    if not events:
        lines.append("No events recorded for this Change yet.")
    for event in events:
        actor = f" actor={event['actor_id']}" if event.get("actor_id") else ""
        subject = f" {event['subject_type']}={event['subject_id']}" if event.get("subject_type") else ""
        lines.append(f"  [{event['seq']:>4}] {event['event_type']}{actor}{subject}")
    if timeline.get("effects"):
        lines.append("")
        lines.append("[bold]Effects[/bold]")
        for effect in timeline["effects"]:
            lines.append(
                f"  - {effect['resource_type']} {effect['resource_id']}: "
                f"{effect['restoration_class']} "
                f"({effect.get('before_digest') or '-'} -> {effect.get('produced_digest') or '-'})"
            )
    if timeline.get("limitations"):
        lines.append("")
        lines.append("[bold]Limitations[/bold]")
        for limitation in timeline["limitations"]:
            lines.append(f"  ! {limitation}")
    return "\n".join(lines)


class TimelineScreen(Screen):
    """Scrollable causal timeline with a persistent chain-verification badge."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str) -> None:
        super().__init__()
        self.change_id = change_id
        self.client = ApiClient(api_url)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static("Loading timeline...", id="timeline_view"))
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        view = self.query_one("#timeline_view", Static)
        try:
            timeline = self.client.get_replay(self.change_id)
        except (ApiConnectionError, ApiError):
            timeline = None
        text = format_timeline(timeline)
        self.app.call_from_thread(view.update, text)
