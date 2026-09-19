"""Real Textual `Pilot` interaction tests (AC-7 item 9).

Uses `anyio`'s pytest plugin, already installed transitively via
FastAPI — no new dependency was needed, contrary to this file's
earlier absence. Covers keyboard navigation, screen push/pop, and the
plan's 80x24/120x30 terminal-size acceptance requirement (item 10's
resize aspect; real human keyboard/visual verification at a physical
terminal is still outside what an automated test can prove).
"""

from __future__ import annotations

import pytest

from backend.app.tui.app import ChangeDashboard
from backend.app.tui.detail_screen import DetailScreen
from backend.app.tui.recovery_screen import RecoveryScreen


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _stub_no_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.tui.app.ChangeDashboard._load_changes", lambda self: None
    )


def _stub_one_change(monkeypatch: pytest.MonkeyPatch, change_id: str = "c1") -> None:
    from textual.widgets import DataTable

    def fake_load(self):
        self._change_ids = [change_id]
        self._change_revisions = {change_id: 1}
        table = self.query_one(DataTable)
        table.add_row("Test change", "ACTIVE", "NO_CHANGES", "C:\\repo")

    monkeypatch.setattr("backend.app.tui.app.ChangeDashboard._load_changes", fake_load)


@pytest.mark.anyio
async def test_dashboard_mounts_at_80x24(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_no_changes(monkeypatch)
    app = ChangeDashboard()
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.is_running
        await pilot.pause()


@pytest.mark.anyio
async def test_dashboard_mounts_at_120x30(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_no_changes(monkeypatch)
    app = ChangeDashboard()
    async with app.run_test(size=(120, 30)) as pilot:
        assert app.is_running
        await pilot.pause()


@pytest.mark.anyio
async def test_refresh_binding_triggers_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def fake_load(self):
        calls["count"] += 1

    monkeypatch.setattr("backend.app.tui.app.ChangeDashboard._load_changes", fake_load)
    app = ChangeDashboard()
    async with app.run_test() as pilot:
        await pilot.pause()
        before = calls["count"]
        await pilot.press("r")
        await pilot.pause()
        assert calls["count"] > before


@pytest.mark.anyio
async def test_enter_pushes_detail_screen_and_escape_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_one_change(monkeypatch)
    monkeypatch.setattr(
        "backend.app.tui.detail_screen.DetailScreen._load", lambda self: None
    )
    app = ChangeDashboard()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DetailScreen)


@pytest.mark.anyio
async def test_v_pushes_recovery_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_one_change(monkeypatch)
    monkeypatch.setattr(
        "backend.app.tui.recovery_screen.RecoveryScreen._load_plan", lambda self: None
    )
    app = ChangeDashboard(actor_id="actor-1")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)


@pytest.mark.anyio
async def test_quit_binding_exits_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_no_changes(monkeypatch)
    app = ChangeDashboard()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running
