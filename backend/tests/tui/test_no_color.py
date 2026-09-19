"""NO_COLOR verification (AC-7 item 10, automatable part).

Textual sets `App.no_color` from the `NO_COLOR` env var at
construction and applies a `Monochrome` filter to all rendered output
automatically (`textual/app.py`) - no code of ours is needed for the
mechanism itself. What we're responsible for, and what this verifies,
is that (a) the app still mounts and runs correctly under that filter
at both plan-required sizes, and (b) every status indicator we render
pairs a text symbol with its colour, so nothing becomes unreadable
once colour is stripped. A human's subjective visual check at a real
terminal is the only piece this cannot replace.
"""

from __future__ import annotations

import pytest

from backend.app.tui.app import ChangeDashboard, state_label
from backend.app.tui.outcome_screen import outcome_status_label


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_no_color_env_var_sets_app_flag_and_applies_a_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    app = ChangeDashboard()
    assert app.no_color is True
    assert any(type(f).__name__ in ("Monochrome", "NoColor") for f in app._filters)


def test_without_no_color_the_flag_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = ChangeDashboard()
    assert app.no_color is False


@pytest.mark.anyio
async def test_dashboard_mounts_under_no_color_at_both_plan_sizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        "backend.app.tui.app.ChangeDashboard._load_changes", lambda self: None
    )
    for size in [(80, 24), (120, 30)]:
        app = ChangeDashboard()
        async with app.run_test(size=size) as pilot:
            assert app.is_running
            assert app.no_color is True
            await pilot.pause()


@pytest.mark.parametrize(
    "label_fn",
    [state_label, outcome_status_label],
)
@pytest.mark.parametrize("value", ["ACTIVE", "PASSED", "FAILED", "SOME_UNKNOWN_STATE"])
def test_every_status_label_carries_a_text_symbol_not_just_colour(label_fn, value: str) -> None:
    """The real, durable guarantee: strip the colour markup and text remains."""

    label = label_fn(value)
    import re

    plain = re.sub(r"\[/?[a-z0-9_]*\]", "", label)
    assert value in plain
    assert plain.strip() != value  # a symbol character precedes the state name
