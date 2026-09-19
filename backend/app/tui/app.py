"""Change dashboard: list Changes and view lifecycle/review state.

First vertical slice of the interactive terminal UI (AC-7). Sources
state only through `ApiClient`, the same client the CLI uses.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError
from backend.app.tui.recovery_screen import RecoveryScreen

_STATE_SYMBOLS = {
    "DRAFT": ("o", "white"),
    "ACTIVE": ("*", "cyan"),
    "BLOCKED": ("#", "red"),
    "FAILED": ("x", "red"),
    "CANCELLED": ("x", "grey50"),
    "STABLE": ("*", "green"),
    "REVIEW_READY": ("*", "yellow"),
}


def state_label(state: str) -> str:
    """Pair a colour with a text symbol so colour is never the only signal."""

    symbol, color = _STATE_SYMBOLS.get(state, ("o", "white"))
    return f"[{color}]{symbol} {state}[/{color}]"


class ChangeDashboard(App):
    """Change list dashboard sourced entirely through the local API."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("v", "recover", "Recovery preview"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, api_url: str = "http://127.0.0.1:8000", actor_id: str | None = None) -> None:
        super().__init__()
        self.api_url = api_url
        self.actor_id = actor_id
        self.client = ApiClient(api_url)
        self._change_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading changes...", id="status")
        yield DataTable(id="changes")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Title", "Lifecycle", "Review", "Repository")
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load_changes, thread=True, exclusive=True)

    def _load_changes(self) -> None:
        status = self.query_one("#status", Static)
        table = self.query_one(DataTable)
        try:
            payload = self.client.list_changes()
        except ApiConnectionError as error:
            self.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return

        items = payload.get("items", [])
        self.call_from_thread(table.clear)
        self._change_ids = [item["id"] for item in items]
        if not items:
            self.call_from_thread(
                status.update, "No Changes yet. Create one with the CLI: `change create`."
            )
            return
        self.call_from_thread(status.update, f"{len(items)} Change(s)")
        for item in items:
            self.call_from_thread(
                table.add_row,
                item.get("title", ""),
                state_label(item.get("lifecycle_state", "DRAFT")),
                item.get("review_state", ""),
                item.get("repository_path", ""),
            )

    def action_recover(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        self.push_screen(RecoveryScreen(change_id, self.api_url, self.actor_id))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="change-assurance-tui")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--actor-id", default=None, help="Actor UUID authorizing recovery execution."
    )
    args = parser.parse_args()
    ChangeDashboard(api_url=args.api_url, actor_id=args.actor_id).run()


if __name__ == "__main__":
    main()
