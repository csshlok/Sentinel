from backend.app.cli.client import ApiClient
from backend.app.tui.app import ChangeDashboard, state_label


def test_state_label_always_pairs_colour_with_text() -> None:
    label = state_label("ACTIVE")
    assert "ACTIVE" in label
    assert "*" in label


def test_unknown_state_falls_back_without_crashing() -> None:
    label = state_label("SOME_FUTURE_STATE")
    assert "SOME_FUTURE_STATE" in label


def test_dashboard_constructs_a_client_for_the_given_api_url() -> None:
    app = ChangeDashboard(api_url="http://127.0.0.1:9999")
    assert isinstance(app.client, ApiClient)
    assert app.client.base_url == "http://127.0.0.1:9999"
