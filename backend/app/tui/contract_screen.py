"""Guided Change Contract editing form (AC-7 item 6, second half).

Wraps the same `PUT .../contract` route and `ApiClient.update_change_contract`
method the CLI's `change contract-update` command already uses.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError


class ContractScreen(Screen):
    """Guided form for updating a Change's Contract."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, change_id: str, api_url: str, current_revision: int) -> None:
        super().__init__()
        self.change_id = change_id
        self.client = ApiClient(api_url)
        self.current_revision = current_revision

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static(f"Editing contract at revision {self.current_revision}", id="status"),
            Input(placeholder="Allowed paths, comma-separated (default **)", id="allowed"),
            Input(placeholder="Forbidden paths, comma-separated", id="forbidden"),
            Input(placeholder="Required checks, comma-separated", id="checks"),
            Input(placeholder="Authority ceiling scopes, comma-separated", id="authority"),
            Input(placeholder="Max risk (LOW/MEDIUM/HIGH/CRITICAL)", id="max_risk", value="MEDIUM"),
            Button("Save Contract", id="save"),
        )
        yield Footer()

    @staticmethod
    def _split(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save":
            return
        allowed = self._split(self.query_one("#allowed", Input).value) or ["**"]
        forbidden = self._split(self.query_one("#forbidden", Input).value)
        checks = self._split(self.query_one("#checks", Input).value)
        authority = self._split(self.query_one("#authority", Input).value)
        max_risk = self.query_one("#max_risk", Input).value.strip() or "MEDIUM"
        self.run_worker(
            lambda: self._save(allowed, forbidden, checks, authority, max_risk),
            thread=True,
            exclusive=True,
        )

    def _save(
        self,
        allowed: list[str],
        forbidden: list[str],
        checks: list[str],
        authority: list[str],
        max_risk: str,
    ) -> None:
        status = self.query_one("#status", Static)
        try:
            updated = self.client.update_change_contract(
                self.change_id,
                expected_revision=self.current_revision,
                allowed_paths=allowed,
                forbidden_paths=forbidden,
                required_checks=checks,
                authority_ceiling=authority,
                max_risk=max_risk,
            )
        except ApiConnectionError as error:
            self.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.current_revision = updated.get("revision", self.current_revision)
        self.call_from_thread(
            status.update, f"[green]Saved. New revision: {self.current_revision}[/green]"
        )
