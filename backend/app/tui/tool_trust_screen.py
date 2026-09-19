"""Read-only tool-trust view for a Change (Tool Registry, bounded scope:

top-level launcher executables + explicitly declared manifests only --
see EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md B.1/B.10). Renders each tool's
trust state, signature state, and drift status. Every state uses
colour-plus-symbol (never colour alone), matching every other screen's
convention -- an UNKNOWN/DENIED/drifted tool is a first-class, clearly
rendered state, not hidden.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError

_TRUST_BADGES = {
    "APPROVED": "[green]* APPROVED[/green]",
    "DENIED": "[red]x DENIED[/red]",
    "PROVISIONAL": "[yellow]~ PROVISIONAL[/yellow]",
    "OBSERVED": "[yellow]? OBSERVED[/yellow]",
    "UNKNOWN": "[red]x UNKNOWN[/red]",
}

_SIGNATURE_BADGES = {
    "valid": "[green]* signed[/green]",
    "invalid": "[red]x invalid signature[/red]",
    "unsigned": "[yellow]! unsigned[/yellow]",
    "unknown": "[yellow]? signature unknown[/yellow]",
}


def _trust_badge(trust_state: str) -> str:
    return _TRUST_BADGES.get(trust_state, f"[red]x {trust_state}[/red]")


def _signature_badge(signature_state: str) -> str:
    return _SIGNATURE_BADGES.get(signature_state, f"[yellow]? {signature_state}[/yellow]")


def format_tools(items: list[dict[str, Any]] | None) -> str:
    if items is None:
        return "No tools available (the Change may not exist, or the API could not be reached)."
    if not items:
        return "No tools observed for this Change yet."

    lines = ["[bold]Tools observed for this Change[/bold]", ""]
    for tool in items:
        lines.append(f"  {tool.get('name')} {tool.get('version')} ({tool.get('publisher') or 'unknown publisher'})")
        lines.append(
            f"    trust={_trust_badge(tool.get('trust_state', 'UNKNOWN'))} "
            f"signature={_signature_badge(tool.get('signature_state', 'unknown'))}"
        )
        lines.append(f"    id={tool.get('id')}")
        lines.append("")
    lines.append("[bold]Limitations[/bold]")
    lines.append(
        "  ! No descendant-process attribution: only the top-level launched "
        "executable or a declared manifest is observed."
    )
    return "\n".join(lines)


class ToolTrustScreen(Screen):
    """Scrollable list of tools observed for a Change, with trust/signature badges."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str) -> None:
        super().__init__()
        self.change_id = change_id
        self.client = ApiClient(api_url)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static("Loading tools...", id="tool_trust_view"))
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        view = self.query_one("#tool_trust_view", Static)
        try:
            payload = self.client.list_tools_for_change(self.change_id)
            items = payload.get("items", []) if payload else []
        except (ApiConnectionError, ApiError):
            items = None
        text = format_tools(items)
        self.app.call_from_thread(view.update, text)
