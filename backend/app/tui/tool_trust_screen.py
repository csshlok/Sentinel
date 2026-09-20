"""Tool-trust view for a Change (Tool Registry, bounded scope:

top-level launcher executables + explicitly declared manifests only --
see EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md B.1/B.10). Renders each tool's
trust state, signature state, and drift status, and lets an authenticated
actor record an explicit APPROVE/DENY decision -- modeled on
recovery_screen.py's "preview, then explicit approval" shape: no default or
automatic approval, the operator must select a tool and press a decision
button, and a reason may be recorded. Every state uses colour-plus-symbol
(never colour alone), matching every other screen's convention -- an
UNKNOWN/DENIED/drifted tool is a first-class, clearly rendered state, not
hidden. The decision itself goes through the same POST /tools/{id}/trust
route the CLI's `tool trust` command uses, so no policy/authority boundary
is bypassed by using the TUI instead.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

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
        "  ! Process-tree supervision does not intercept descendant tool calls: "
        "only the top-level launched executable or a declared manifest enters this registry."
    )
    return "\n".join(lines)


class ToolTrustScreen(Screen):
    """List tools observed for a Change and record explicit trust decisions."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str, actor_id: str | None = None) -> None:
        super().__init__()
        self.change_id = change_id
        self.actor_id = actor_id
        self.client = ApiClient(api_url)
        self._tool_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Loading tools...", id="status"),
            DataTable(id="tools"),
            Horizontal(
                Input(placeholder="Reason (optional)", id="reason"),
                Input(placeholder="Scope", value="exact_version", id="scope"),
            ),
            Horizontal(
                Button("Approve Selected", id="approve", variant="success", disabled=True),
                Button("Deny Selected", id="deny", variant="error", disabled=True),
            ),
            Static("", id="result"),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "Version", "Trust", "Signature", "Drifted")
        table.cursor_type = "row"
        if not self.actor_id:
            self.query_one("#status", Static).update(
                "[yellow]No actor id configured; trust decisions require an "
                "authenticated actor. Launch the TUI with --actor-id.[/yellow]"
            )
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        status = self.query_one("#status", Static)
        table = self.query_one(DataTable)
        try:
            payload = self.client.list_tools_for_change(self.change_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(status.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(status.update, f"[red]x {error.code}: {error.message}[/red]")
            return

        items = payload.get("items", []) if payload else []
        self.app.call_from_thread(table.clear)
        self._tool_ids = [item["id"] for item in items]
        self.app.call_from_thread(
            status.update,
            f"{len(items)} tool(s) observed for this Change."
            if items else "No tools observed for this Change yet.",
        )
        for item in items:
            self.app.call_from_thread(
                table.add_row,
                item.get("name", ""),
                item.get("version", ""),
                _trust_badge(item.get("trust_state", "UNKNOWN")),
                _signature_badge(item.get("signature_state", "unknown")),
                "yes" if item.get("drifted") else "no",
            )
        self.app.call_from_thread(self._update_decision_buttons)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        del event
        self._update_decision_buttons()

    def _update_decision_buttons(self) -> None:
        table = self.query_one(DataTable)
        has_selection = bool(self._tool_ids) and table.cursor_row is not None
        enabled = has_selection and bool(self.actor_id)
        self.query_one("#approve", Button).disabled = not enabled
        self.query_one("#deny", Button).disabled = not enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve":
            self._decide("APPROVE")
        elif event.button.id == "deny":
            self._decide("DENY")

    def _decide(self, decision: str) -> None:
        table = self.query_one(DataTable)
        if not self.actor_id or not self._tool_ids or table.cursor_row is None:
            return
        try:
            tool_id = self._tool_ids[table.cursor_row]
        except IndexError:
            return
        scope = self.query_one("#scope", Input).value.strip() or "exact_version"
        reason = self.query_one("#reason", Input).value.strip() or None
        self.query_one("#approve", Button).disabled = True
        self.query_one("#deny", Button).disabled = True
        self.run_worker(
            lambda: self._submit_decision(tool_id, decision, scope, reason),
            thread=True, exclusive=True,
        )

    def _submit_decision(
        self, tool_id: str, decision: str, scope: str, reason: str | None
    ) -> None:
        result = self.query_one("#result", Static)
        try:
            updated = self.client.decide_tool_trust(
                tool_id, actor_id=self.actor_id, decision=decision, scope=scope,
                reason=reason, change_id=self.change_id,
            )
        except ApiConnectionError as error:
            self.app.call_from_thread(result.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(result.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.app.call_from_thread(
            result.update, f"Recorded {updated.get('decision', decision)} for {tool_id}."
        )
        self._load()
