"""Guided delegation creation/list/revoke form (AC-7 item 6, partial).

Covers delegations (scoped authority grants); Change Contract editing
is not covered here (still CLI-only via `change contract update` —
not yet implemented in the CLI either, see AC_REMAINING_WORK.md).
Every mutation goes through the real API, so policy/lifecycle guards
are never bypassed.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError


class DelegationScreen(Screen):
    """List, create, and revoke delegations for a Change."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, change_id: str, api_url: str, grantor_id: str | None = None) -> None:
        super().__init__()
        self.change_id = change_id
        self.grantor_id = grantor_id
        self.client = ApiClient(api_url)
        self._delegation_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Loading delegations...", id="status"),
            DataTable(id="delegations"),
            Horizontal(
                Input(placeholder="Grantee actor UUID", id="grantee_id"),
                Input(placeholder="Scopes, comma-separated", id="scopes"),
                Input(placeholder="TTL seconds", id="ttl", value="3600"),
                Button("Create Delegation", id="create"),
            ),
            Button("Revoke Selected", id="revoke", variant="error"),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Grantee", "Scopes", "Expires", "Revoked")
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        status = self.query_one("#status", Static)
        table = self.query_one(DataTable)
        try:
            payload = self.client.list_delegations(self.change_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return

        items = payload.get("items", [])
        self.app.call_from_thread(table.clear)
        self._delegation_ids = [item["id"] for item in items]
        self.app.call_from_thread(status.update, f"{len(items)} delegation(s)")
        for item in items:
            self.app.call_from_thread(
                table.add_row,
                item.get("grantee_id", ""),
                ", ".join(item.get("scopes", [])),
                item.get("expires_at", ""),
                "yes" if item.get("revoked_at") else "no",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create":
            self._create()
        elif event.button.id == "revoke":
            self._revoke_selected()

    def _create(self) -> None:
        status = self.query_one("#status", Static)
        if not self.grantor_id:
            status.update(
                "[yellow]No grantor id configured; launch with --grantor-id to enable creation.[/yellow]"
            )
            return
        grantee_id = self.query_one("#grantee_id", Input).value.strip()
        scopes = [s.strip() for s in self.query_one("#scopes", Input).value.split(",") if s.strip()]
        ttl_raw = self.query_one("#ttl", Input).value.strip()
        if not grantee_id or not scopes or not ttl_raw.isdigit():
            status.update("[yellow]Grantee id, at least one scope, and a numeric TTL are required.[/yellow]")
            return
        self.run_worker(
            lambda: self._submit_create(grantee_id, scopes, int(ttl_raw)), thread=True, exclusive=True
        )

    def _submit_create(self, grantee_id: str, scopes: list[str], ttl_seconds: int) -> None:
        status = self.query_one("#status", Static)
        try:
            self.client.create_delegation(
                grantor_id=self.grantor_id,
                grantee_id=grantee_id,
                change_id=self.change_id,
                scopes=scopes,
                ttl_seconds=ttl_seconds,
            )
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self._load()

    def _revoke_selected(self) -> None:
        table = self.query_one(DataTable)
        if not self._delegation_ids or table.cursor_row is None:
            return
        try:
            delegation_id = self._delegation_ids[table.cursor_row]
        except IndexError:
            return
        self.run_worker(lambda: self._submit_revoke(delegation_id), thread=True, exclusive=True)

    def _submit_revoke(self, delegation_id: str) -> None:
        status = self.query_one("#status", Static)
        try:
            self.client.revoke_delegation(delegation_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self._load()
