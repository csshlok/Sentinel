"""Passport view/export screen (AC-7 item 8).

Shows the real `ChangePassport` — the same byte-stable canonical JSON
`PassportBuilder` produces — and writes it to a local file on export.
Never fabricates a passport locally: "no passport yet" is shown as an
explicit empty state (`PASSPORT_NOT_FOUND`), and building one always
goes through the real `POST .../passport` route.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError


def format_passport(passport: dict[str, Any]) -> str:
    """Pure formatting so the rendering logic is testable without Textual."""

    lines = [
        f"Passport {passport['id']} (schema v{passport.get('schema_version', 1)})",
        f"Change: {passport['change_id']}",
        f"Lifecycle state: {passport['lifecycle_state']}",
        f"Generated at: {passport['generated_at']}",
        f"Canonical digest: {passport['canonical_digest']}",
        "",
    ]

    actor_ids = passport.get("actor_ids", [])
    lines.append(f"Actors: {len(actor_ids)}")
    for authority in passport.get("authority_summary", []):
        lines.append(f"  - {authority}")

    evidence = passport.get("evidence", [])
    lines.append("")
    lines.append(f"Evidence references: {len(evidence)}")
    for item in evidence:
        lines.append(f"  - {item['kind']}: {item['status']}")

    outcomes = passport.get("outcomes", [])
    lines.append("")
    lines.append(f"Outcomes: {len(outcomes)}")

    recovery_status = passport.get("recovery_status")
    lines.append("")
    lines.append(f"Recovery status: {recovery_status or 'none'}")

    limitations = passport.get("limitations", [])
    if limitations:
        lines.append("")
        lines.append("[yellow]Limitations (never hidden):[/yellow]")
        for limitation in limitations:
            lines.append(f"  o {limitation}")

    return "\n".join(lines)


def export_path(change_id: str, export_dir: Path | None = None) -> Path:
    directory = export_dir or Path.cwd()
    return directory / f"passport-{change_id}.json"


class PassportScreen(Screen):
    """View the latest Change Passport, build a fresh one, or export it to disk."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("b", "build", "Build fresh passport"),
        ("e", "export", "Export to file"),
    ]

    def __init__(self, change_id: str, api_url: str, export_dir: Path | None = None) -> None:
        super().__init__()
        self.change_id = change_id
        self.client = ApiClient(api_url)
        self.export_dir = export_dir
        self.passport: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Loading passport...", id="passport_view"),
            Static("", id="export_status"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load_latest, thread=True)

    def _load_latest(self) -> None:
        view = self.query_one("#passport_view", Static)
        try:
            passport = self.client.get_latest_passport(self.change_id)
        except ApiConnectionError as error:
            self.call_from_thread(view.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            if error.code == "PASSPORT_NOT_FOUND":
                self.call_from_thread(
                    view.update, "No passport has been built for this Change yet. Press 'b' to build one."
                )
                return
            self.call_from_thread(view.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.passport = passport
        self.call_from_thread(view.update, format_passport(passport))

    def action_build(self) -> None:
        self.run_worker(self._build, thread=True)

    def _build(self) -> None:
        view = self.query_one("#passport_view", Static)
        try:
            passport = self.client.build_passport(self.change_id)
        except ApiConnectionError as error:
            self.call_from_thread(view.update, f"[red]x Could not reach the API: {error}[/red]")
            return
        except ApiError as error:
            self.call_from_thread(view.update, f"[red]x {error.code}: {error.message}[/red]")
            return
        self.passport = passport
        self.call_from_thread(view.update, format_passport(passport))

    def action_export(self) -> None:
        status = self.query_one("#export_status", Static)
        if self.passport is None:
            status.update("[yellow]Nothing to export yet; build a passport first.[/yellow]")
            return
        path = export_path(self.change_id, self.export_dir)
        path.write_text(
            json.dumps(self.passport, sort_keys=True, indent=2), encoding="utf-8"
        )
        status.update(f"[green]Exported to {path}[/green]")
