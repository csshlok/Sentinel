from backend.app.tui.outcome_screen import OutcomeScreen, outcome_status_label


def test_outcome_status_label_pairs_colour_with_text() -> None:
    label = outcome_status_label("PASSED")
    assert "PASSED" in label
    assert "*" in label


def test_unknown_status_falls_back_without_crashing() -> None:
    label = outcome_status_label("SOME_FUTURE_STATUS")
    assert "SOME_FUTURE_STATUS" in label


def test_screen_is_constructible_without_grant_id() -> None:
    screen = OutcomeScreen("change-1", "http://127.0.0.1:8000")
    assert screen.grant_id is None
