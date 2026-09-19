"""Pilot tests that exercise every screen's REAL (un-stubbed) worker methods
against a live server — no monkeypatching of `_load`/`_load_plan`/etc.

Every test in `test_pilot_interaction.py` stubs those methods out, which is
exactly why the `self.call_from_thread` bug (fixed separately) was invisible
to the automated suite: the stubbed tests never ran the real async worker
body. These tests exist specifically to close that gap by driving the real
data-loading and action code path on every screen, against a real API
server backed by a real disposable Git repository.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from uuid import uuid4

import pytest
import uvicorn

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.tui.app import ChangeDashboard
from backend.app.tui.contract_screen import ContractScreen
from backend.app.tui.delegation_screen import DelegationScreen
from backend.app.tui.detail_screen import DetailScreen
from backend.app.tui.evidence_screen import EvidenceScreen
from backend.app.tui.outcome_screen import OutcomeScreen
from backend.app.tui.passport_screen import PassportScreen
from backend.app.tui.recovery_screen import RecoveryScreen
from backend.app.tui.tool_trust_screen import ToolTrustScreen
from backend.tests.support_kb import make_repo


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_change(tmp_path):
    """A real live server with one real Change, Actor, and broad delegation."""

    repo = make_repo(tmp_path / "repo", {"app.py": "VALUE = 1\n"})
    port = _free_port()
    app = create_app(settings=Settings(database_path=tmp_path / "tui-real.sqlite3"))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)

    previous_token = os.environ.get("CHANGE_ASSURANCE_API_TOKEN")
    os.environ["CHANGE_ASSURANCE_API_TOKEN"] = app.state.api_token

    from backend.app.cli.client import ApiClient

    client = ApiClient(f"http://127.0.0.1:{port}")
    change = client.create_change("Real TUI flow", "Exercise every screen for real", str(repo))
    human = client.create_actor("HUMAN", "Owner")
    agent = client.create_actor("AGENT", "Agent")
    client.create_delegation(
        grantor_id=human["id"],
        grantee_id=agent["id"],
        change_id=change["id"],
        scopes=["agent.launch", "agent.stop", "assurance.run", "recovery.execute"],
        ttl_seconds=3600,
    )

    try:
        yield f"http://127.0.0.1:{port}", change["id"], agent["id"], human["id"]
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if previous_token is None:
            os.environ.pop("CHANGE_ASSURANCE_API_TOKEN", None)
        else:
            os.environ["CHANGE_ASSURANCE_API_TOKEN"] = previous_token


async def _select_first_row(pilot) -> None:
    from textual.widgets import DataTable

    table = pilot.app.query_one(DataTable)
    table.cursor_coordinate = (0, 0)
    await pilot.pause()


async def _wait_for_rows(pilot, selector: str, *, at_least: int = 1, timeout: float = 5.0) -> None:
    """Poll a DataTable's row_count with real wall-clock waits.

    A single `pilot.pause()` yields one event-loop tick, which is not
    guaranteed to be enough wall-clock time for a background-thread worker
    doing several real sequential HTTP calls (e.g. `BranchScreen._load`) to
    finish and call back into the UI thread. Polling with real `pause(delay)`
    ticks avoids both flaky under-waiting and an unbounded hang.
    """

    from textual.widgets import DataTable

    deadline = time.monotonic() + timeout
    table = pilot.app.query_one(selector, DataTable)
    while table.row_count < at_least and time.monotonic() < deadline:
        await pilot.pause(0.05)


@pytest.mark.anyio
async def test_detail_screen_real_load_and_refresh(live_change) -> None:
    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("i")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_evidence_screen_real_load_and_refresh(live_change) -> None:
    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, EvidenceScreen)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_outcome_screen_real_load_without_grant(live_change) -> None:
    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)  # no grant_id on purpose
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, OutcomeScreen)
        await pilot.press("f")  # refresh without a configured grant: must not crash
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_delegation_screen_real_load(live_change) -> None:
    api_url, change_id, actor_id, human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id, grantor_id=human_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, DelegationScreen)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_contract_screen_real_load(live_change) -> None:
    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ContractScreen)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_recovery_screen_real_load_with_no_checkpoint(live_change) -> None:
    """No Git checkpoint has been captured, so the real backend raises
    RECOVERY_NO_CHECKPOINT_EVIDENCE — the screen's real error-handling
    branch, not the success branch. Must render the error, not crash."""

    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, RecoveryScreen)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_passport_screen_real_load_when_none_exists(live_change) -> None:
    """No Passport has been built yet: the real backend returns
    PASSPORT_NOT_FOUND. Must render the honest empty state, not crash."""

    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, PassportScreen)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_tools_screen_real_load_when_no_tool_observed(live_change) -> None:
    """No tool has been observed for this Change yet: the real backend
    returns an empty list, not an error. Must render the honest empty
    state, not crash."""

    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("u")
        await pilot.pause()
        assert isinstance(app.screen, ToolTrustScreen)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_tools_screen_real_approve_decision_reaches_the_api(live_change) -> None:
    """Drives the real interactive approve flow: select the observed tool

    row, press the Approve button, and confirm the trust state shown by the
    screen actually changed via a real round trip through
    POST /tools/{id}/trust -- not a stubbed worker method.
    """

    from textual.widgets import Button, DataTable

    from backend.app.cli.client import ApiClient

    api_url, change_id, actor_id, _human_id = live_change
    client = ApiClient(api_url)
    client.launch_agent(
        change_id, actor_id=actor_id, executable="python",
        args=["-c", "print('registered')"],
    )

    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("u")
        await pilot.pause()
        assert isinstance(app.screen, ToolTrustScreen)

        table = pilot.app.query_one(DataTable)
        assert table.row_count == 1
        table.cursor_coordinate = (0, 0)
        await pilot.pause()

        approve = pilot.app.query_one("#approve", Button)
        assert approve.disabled is False
        await pilot.click("#approve")
        await pilot.pause()
        await pilot.pause()

        tools = client.list_tools_for_change(change_id)["items"]
        assert tools[0]["trust_state"] == "APPROVED"

        result_text = str(pilot.app.query_one("#result").renderable)
        assert "APPROVE" in result_text

        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_branch_screen_real_tree_with_no_forks_yet(live_change) -> None:
    """No fork exists yet: the real backend returns an empty forks list.
    Must render the honest single-node tree, not crash."""

    from backend.app.tui.branch_screen import BranchScreen

    api_url, change_id, actor_id, _human_id = live_change
    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("b")
        await pilot.pause()
        assert isinstance(app.screen, BranchScreen)
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_branch_screen_real_fork_flow(live_change) -> None:
    """Capture a baseline, open Branches, fork from the checkpoint through
    the real interactive form, and confirm a real second Change exists
    with the correct forked_from_* provenance -- not a stubbed worker."""

    from textual.widgets import Button, DataTable, Input

    from backend.app.cli.client import ApiClient
    from backend.app.tui.branch_screen import BranchScreen

    api_url, change_id, actor_id, human_id = live_change
    client = ApiClient(api_url)
    client.capture_baseline(change_id)
    client.create_delegation(
        grantor_id=human_id, grantee_id=actor_id, change_id=change_id,
        scopes=["change.fork"], ttl_seconds=3600,
    )

    app = ChangeDashboard(api_url=api_url, actor_id=actor_id)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        await pilot.press("b")
        await pilot.pause()
        assert isinstance(app.screen, BranchScreen)
        await _wait_for_rows(pilot, "#checkpoints")

        table = pilot.app.query_one("#checkpoints", DataTable)
        assert table.row_count == 1
        table.cursor_coordinate = (0, 0)
        await pilot.pause()

        pilot.app.query_one("#fork_title", Input).value = "alternate model"
        pilot.app.query_one("#fork_intent", Input).value = "compare outcomes"
        # Real button press (not a mouse click) -- the layout can push this
        # button below the default test-terminal's visible region, which
        # would make a coordinate-based pilot.click() fail with OutOfBounds
        # even though the button is a perfectly real, reachable widget.
        pilot.app.query_one("#fork", Button).press()
        await pilot.pause()

        deadline = time.monotonic() + 5.0
        forks = client.list_change_forks(change_id)
        while forks["count"] < 1 and time.monotonic() < deadline:
            await pilot.pause(0.05)
            forks = client.list_change_forks(change_id)
        assert forks["count"] == 1
        assert forks["items"][0]["title"] == "alternate model"
        assert forks["items"][0]["forked_from_change_id"] == change_id

        await pilot.press("r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.anyio
async def test_full_tour_of_every_screen_in_one_session(live_change) -> None:
    """One session visiting every screen in sequence, the way a real user
    would, rather than one isolated screen per test — catches state that
    only breaks after a prior screen has already run."""

    api_url, change_id, actor_id, human_id = live_change
    app = ChangeDashboard(
        api_url=api_url, actor_id=actor_id, grantor_id=human_id
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await _select_first_row(pilot)
        for key in ("i", "escape", "g", "escape", "o", "escape",
                    "d", "escape", "c", "escape", "v", "escape",
                    "p", "escape", "u", "escape", "b", "escape", "r"):
            await pilot.press(key)
            await pilot.pause()
        assert app.is_running
