"""Change dashboard: list Changes and view lifecycle/review state.

First vertical slice of the interactive terminal UI (AC-7). Sources
state only through `ApiClient`, the same client the CLI uses.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError
from backend.app.tui.contract_screen import ContractScreen
from backend.app.tui.delegation_screen import DelegationScreen
from backend.app.tui.detail_screen import DetailScreen
from backend.app.tui.evidence_screen import EvidenceScreen
from backend.app.tui.outcome_screen import OutcomeScreen
from backend.app.tui.passport_screen import PassportScreen
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
        ("enter", "detail", "Detail"),
        ("v", "recover", "Recovery preview"),
        ("p", "passport", "Passport"),
        ("g", "evidence", "Evidence"),
        ("o", "outcomes", "Outcomes"),
        ("d", "delegations", "Delegations"),
        ("c", "contract", "Edit contract"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:8000",
        actor_id: str | None = None,
        grant_id: str | None = None,
        grantor_id: str | None = None,
    ) -> None:
        super().__init__()
        self.api_url = api_url
        self.actor_id = actor_id
        self.grant_id = grant_id
        self.grantor_id = grantor_id
        self.client = ApiClient(api_url)
        self._change_ids: list[str] = []
        self._change_revisions: dict[str, int] = {}

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
        self._change_revisions = {item["id"]: item.get("revision", 1) for item in items}
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

    def action_passport(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        self.push_screen(PassportScreen(change_id, self.api_url))

    def action_detail(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        self.push_screen(DetailScreen(change_id, self.api_url))

    def action_contract(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        revision = self._change_revisions.get(change_id, 1)
        self.push_screen(ContractScreen(change_id, self.api_url, revision))

    def action_evidence(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        self.push_screen(EvidenceScreen(change_id, self.api_url))

    def action_outcomes(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        self.push_screen(OutcomeScreen(change_id, self.api_url, grant_id=self.grant_id))

    def action_delegations(self) -> None:
        table = self.query_one(DataTable)
        if not self._change_ids or table.cursor_row is None:
            return
        try:
            change_id = self._change_ids[table.cursor_row]
        except IndexError:
            return
        self.push_screen(DelegationScreen(change_id, self.api_url, grantor_id=self.grantor_id))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="change-assurance-tui")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--actor-id", default=None, help="Actor UUID authorizing recovery execution."
    )
    parser.add_argument(
        "--grant-id", default=None, help="Credential grant UUID enabling outcome refresh."
    )
    parser.add_argument(
        "--grantor-id", default=None, help="Actor UUID authorizing new delegations."
    )
    args = parser.parse_args()
    ChangeDashboard(
        api_url=args.api_url,
        actor_id=args.actor_id,
        grant_id=args.grant_id,
        grantor_id=args.grantor_id,
    ).run()


if __name__ == "__main__":
    main()
