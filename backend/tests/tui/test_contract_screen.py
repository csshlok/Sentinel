from backend.app.tui.contract_screen import ContractScreen


def test_screen_is_constructible_with_revision() -> None:
    screen = ContractScreen("change-1", "http://127.0.0.1:8000", current_revision=3)
    assert screen.current_revision == 3


def test_split_ignores_blank_entries() -> None:
    assert ContractScreen._split("a, b, , c") == ["a", "b", "c"]
    assert ContractScreen._split("") == []
