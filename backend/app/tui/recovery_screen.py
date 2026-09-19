"""Recovery preview/confirmation screen (AC-7 item 7).

Preview shows exactly what `GitRecoveryEngine.plan()` found: supported
actions, real conflicts, and explicit unsupported effects — never a
fabricated "safe to recover" summary. Approval is never inferred: the
operator must type a non-empty token and press Confirm; there is no
default or automatic approval path, matching `RecoveryPort`'s own
mandatory-approval-token contract.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError


def format_plan(plan: dict[str, Any]) -> str:
    """Pure formatting so the rendering logic is testable without Textual."""

    lines = [f"Recovery plan {plan['id']}", f"Status: {plan['status']}", ""]
    actions = plan.get("actions", [])
    if not actions:
        lines.append("No supported recovery actions.")
    for action in actions:
        marker = "[green]supported[/green]" if action["supported"] else "[red]blocked[/red]"
        lines.append(f"- {action['kind']} ({marker}): {action['description']}")
        for limitation in action.get("limitations", []):
            lines.append(f"    ! {limitation}")
    if plan.get("conflicts"):
        lines.append("")
        lines.append("[red]Conflicts:[/red]")
        for conflict in plan["conflicts"]:
            lines.append(f"  x {conflict}")
    if plan.get("unsupported_effects"):
        lines.append("")
        lines.append("[yellow]Unsupported (never claimed as recovered):[/yellow]")
        for item in plan["unsupported_effects"]:
            lines.append(f"  o {item}")
    return "\n".join(lines)


class RecoveryScreen(Screen):
    """Preview a Change's recovery plan and, on explicit approval, execute it."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, change_id: str, api_url: str, actor_id: str | None) -> None:
        super().__init__()
        self.change_id = change_id
        self.actor_id = actor_id
        self.client = ApiClient(api_url)
        self.plan: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Loading recovery preview...", id="plan_view"),
            Input(
                placeholder="Type an explicit approval token to enable Confirm",
                id="approval_token",
            ),
            Button("Confirm Recovery", id="confirm", variant="error", disabled=True),
            Button("Cancel", id="cancel"),
            Static("", id="result"),
        )
        yield Footer()

    def on_mount(self) -> None:
        if not self.actor_id:
            self.query_one("#plan_view", Static).update(
                "[red]No actor id configured; recovery requires an authenticated "
                "actor. Launch the TUI with --actor-id.[/red]"
            )
            self.query_one("#approval_token", Input).disabled = True
            return
        self.run_worker(self._load_plan, thread=True)

    def _load_plan(self) -> None:
        view = self.query_one("#plan_view", Static)
        try:
            plan = self.client.preview_recovery(self.change_id)
        except ApiConnectionError as error:
            self.app.call_from_thread(view.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(view.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.plan = plan
        self.app.call_from_thread(view.update, format_plan(plan))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "approval_token":
            self.query_one("#confirm", Button).disabled = not event.value.strip() or self.plan is None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
        elif event.button.id == "confirm":
            self._confirm()

    def _confirm(self) -> None:
        token = self.query_one("#approval_token", Input).value.strip()
        if not token or self.plan is None:
            return
        self.query_one("#confirm", Button).disabled = True
        self.run_worker(lambda: self._execute(token), thread=True)

    def _execute(self, token: str) -> None:
        result_widget = self.query_one("#result", Static)
        assert self.plan is not None
        try:
            result = self.client.execute_recovery(
                self.change_id, self.plan["id"], actor_id=self.actor_id, approval_token=token
            )
        except ApiConnectionError as error:
            self.app.call_from_thread(result_widget.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.app.call_from_thread(result_widget.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.app.call_from_thread(result_widget.update, f"Recovery status: {result['status']}")
