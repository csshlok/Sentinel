from backend.app.tui.delegation_screen import DelegationScreen


def test_screen_is_constructible_without_grantor_id() -> None:
    screen = DelegationScreen("change-1", "http://127.0.0.1:8000")
    assert screen.grantor_id is None
    assert screen._delegation_ids == []


def test_screen_stores_grantor_id_when_given() -> None:
    screen = DelegationScreen("change-1", "http://127.0.0.1:8000", grantor_id="actor-1")
    assert screen.grantor_id == "actor-1"
