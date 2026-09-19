"""Change detail view (AC-7 item 1).

Shows the full `ChangeView` returned by the real API for one Change:
intent, lifecycle/review state, risk, Change Contract, and the latest
Git/verification evidence when present. Never fabricates a field that
the API did not return.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError

__all__ = ["DetailScreen", "format_change", "lifecycle_stepper"]


_MAIN_LIFECYCLE_PATH = [
    "DRAFT",
    "ACTIVE",
    "LOCALLY_VERIFIED",
    "REVIEW_READY",
    "PR_OPEN",
    "CI_VERIFIED",
    "ARTIFACT_BUILT",
    "DEPLOYED",
    "OBSERVING",
    "STABLE",
]

_SIDE_STATES = {
    "PAUSED",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "RECOVERY_PENDING",
    "RECOVERING",
    "RECOVERED_VERIFIED",
    "RECOVERY_CONFLICT",
    "RECOVERY_FAILED",
}


def lifecycle_stepper(state: str) -> str:
    """One-line stepper: the main happy path, with the current state marked.

    A state off the main path (paused/blocked/failed/recovery-*) is
    shown on its own line instead of silently forcing it onto the path
    it isn't on.
    """

    if state in _SIDE_STATES:
        return f"[yellow]<< {state} (off the main path) >>[/yellow]"
    segments = []
    for step in _MAIN_LIFECYCLE_PATH:
        if step == state:
            segments.append(f"[bold green][{step}][/bold green]")
        else:
            segments.append(step)
    return " -> ".join(segments)


def format_change(change: dict[str, Any]) -> str:
    """Pure formatting so the rendering logic is testable without Textual."""

    lifecycle_state = change.get("lifecycle_state", "DRAFT")
    lines = [
        f"{change['title']}  ({change['id']})",
        f"Intent: {change['intent']}",
        f"Repository: {change['repository_path']}",
        "",
        lifecycle_stepper(lifecycle_state),
        "",
        f"Lifecycle: {lifecycle_state}",
        f"Review state: {change.get('review_state', 'NO_CHANGES')}",
        f"Risk level: {change.get('risk_level', 'UNKNOWN')}",
        f"Revision: {change.get('revision', 1)}",
    ]

    contract = change.get("contract") or {}
    if contract:
        lines.append("")
        lines.append("Change Contract:")
        lines.append(f"  Allowed paths: {', '.join(contract.get('allowed_paths', [])) or '(none)'}")
        lines.append(f"  Forbidden paths: {', '.join(contract.get('forbidden_paths', [])) or '(none)'}")
        lines.append(f"  Authority ceiling: {', '.join(contract.get('authority_ceiling', [])) or '(none)'}")
        lines.append(f"  Max risk: {contract.get('max_risk', 'MEDIUM')}")
        lines.append(f"  Required checks: {', '.join(contract.get('required_checks', [])) or '(none)'}")

    git_summary = change.get("git_summary")
    lines.append("")
    if git_summary is None:
        lines.append("[yellow]No Git evidence captured yet.[/yellow]")
    else:
        lines.append(
            f"Git: branch {git_summary.get('branch')} @ {git_summary.get('head_sha')} "
            f"({'clean' if git_summary.get('is_clean') else 'dirty'}), "
            f"+{git_summary.get('total_additions', 0)}/-{git_summary.get('total_deletions', 0)}"
        )

    verification = change.get("verification")
    if verification is None:
        lines.append("[yellow]No verification result recorded yet.[/yellow]")
    else:
        lines.append(
            f"Verification: {verification.get('status')} "
            f"(exit {verification.get('exit_code')})"
        )

    return "\n".join(lines)


class DetailScreen(Screen):
    """Full detail view for one Change, sourced only through `ApiClient`."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh", "Refresh")]

    def __init__(self, change_id: str, api_url: str) -> None:
        super().__init__()
        self.change_id = change_id
        self.client = ApiClient(api_url)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(Static("Loading...", id="detail_view"))
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()

    def action_refresh(self) -> None:
        self.run_worker(self._load, thread=True, exclusive=True)

    def _load(self) -> None:
        view = self.query_one("#detail_view", Static)
        try:
            change = self.client.get_change(self.change_id)
        except ApiConnectionError as error:
            self.call_from_thread(view.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.call_from_thread(view.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.call_from_thread(view.update, format_change(change))
