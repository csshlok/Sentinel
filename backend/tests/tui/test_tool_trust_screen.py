from backend.app.tui.tool_trust_screen import ToolTrustScreen, format_tools


def test_format_tools_missing_shows_honest_empty_state() -> None:
    text = format_tools(None)
    assert "No tools available" in text


def test_format_tools_empty_list_shows_honest_empty_state() -> None:
    text = format_tools([])
    assert "No tools observed" in text


def test_format_tools_shows_approved_badge() -> None:
    text = format_tools([{
        "id": "tool-1", "name": "Codex CLI", "version": "1.0.0", "publisher": "OpenAI",
        "trust_state": "APPROVED", "signature_state": "valid",
    }])
    assert "Codex CLI" in text
    assert "APPROVED" in text
    assert "signed" in text


def test_format_tools_shows_denied_and_unsigned_never_hidden() -> None:
    text = format_tools([{
        "id": "tool-2", "name": "Unknown MCP", "version": "0.0.1", "publisher": None,
        "trust_state": "DENIED", "signature_state": "unsigned",
    }])
    assert "DENIED" in text
    assert "unsigned" in text


def test_screen_is_constructible() -> None:
    screen = ToolTrustScreen("change-1", "http://127.0.0.1:8000")
    assert screen.change_id == "change-1"
