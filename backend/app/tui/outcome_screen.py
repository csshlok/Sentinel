"""PR/CI outcome panel (AC-7 item 5).

Lists real `Outcome` records for a Change and can trigger a refresh
through the real `POST .../outcomes/refresh` route. Never fabricates a
status: an empty list is shown as "no outcomes recorded yet", not as
success or failure.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError

_STATUS_SYMBOLS = {
    "PASSED": ("*", "green"),
    "FAILED": ("x", "red"),
    "PENDING": ("o", "yellow"),
    "CANCELLED": ("x", "grey50"),
    "UNAVAILABLE": ("?", "grey50"),
    "UNKNOWN": ("?", "white"),
}


def outcome_status_label(status: str) -> str:
    symbol, color = _STATUS_SYMBOLS.get(status, ("?", "white"))
    return f"[{color}]{symbol} {status}[/{color}]"


class OutcomeScreen(Screen):
    """View recorded provider outcomes for a Change and refresh them."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("f", "refresh_outcomes", "Refresh from GitHub")]

    def __init__(
        self, change_id: str, api_url: str, grant_id: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        super().__init__()
        self.change_id = change_id
        self.grant_id = grant_id
        self.actor_id = actor_id
        self.client = ApiClient(api_url)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static("Loading outcomes...", id="status"), DataTable(id="outcomes"))
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Kind", "Status", "Repository", "Head SHA", "Observed at")
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        status = self.query_one("#status", Static)
        table = self.query_one(DataTable)
        try:
            payload = self.client.list_outcomes(self.change_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return

        items = payload.get("items", [])
        self.app.call_from_thread(table.clear)
        if not items:
            self.app.call_from_thread(
                status.update, "No outcomes recorded yet. Press 'f' to refresh from GitHub."
            )
            return
        self.app.call_from_thread(status.update, f"{len(items)} outcome(s)")
        for item in items:
            self.app.call_from_thread(
                table.add_row,
                item.get("kind", ""),
                outcome_status_label(item.get("status", "UNKNOWN")),
                item.get("repository", ""),
                item.get("head_sha", "")[:12],
                item.get("observed_at", ""),
            )

    def action_refresh_outcomes(self) -> None:
        status = self.query_one("#status", Static)
        if not self.grant_id:
            status.update(
                "[yellow]No grant id configured; launch with --grant-id to enable refresh.[/yellow]"
            )
            return
        if not self.actor_id:
            status.update(
                "[yellow]No actor id configured; launch with --actor-id to enable refresh.[/yellow]"
            )
            return
        self.run_worker(self._refresh, thread=True, exclusive=True)

    def _refresh(self) -> None:
        status = self.query_one("#status", Static)
        try:
            self.client.refresh_outcomes(
                self.change_id, actor_id=self.actor_id, grant_id=self.grant_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self._load()
