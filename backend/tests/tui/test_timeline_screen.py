from backend.app.tui.timeline_screen import TimelineScreen, format_timeline


def test_format_timeline_missing_shows_honest_empty_state() -> None:
    text = format_timeline(None)
    assert "No timeline available" in text


def test_format_timeline_shows_verified_badge() -> None:
    text = format_timeline({
        "chain_verified": True, "first_break_seq": None,
        "events": [{"seq": 1, "event_type": "change.created", "actor_id": None, "subject_type": None}],
        "effects": [], "limitations": [],
    })
    assert "verified" in text
    assert "change.created" in text


def test_format_timeline_shows_tamper_detected_never_hidden() -> None:
    text = format_timeline({
        "chain_verified": False, "first_break_seq": 3,
        "events": [], "effects": [], "limitations": [],
    })
    assert "TAMPER DETECTED" in text
    assert "seq 3" in text


def test_format_timeline_shows_effects_and_limitations() -> None:
    text = format_timeline({
        "chain_verified": True, "first_break_seq": None,
        "events": [],
        "effects": [{"resource_type": "git_checkpoint", "resource_id": "r1",
                     "restoration_class": "none", "before_digest": None,
                     "produced_digest": "a" * 64}],
        "limitations": ["Trace-only replay: no re-execution of any kind."],
    })
    assert "git_checkpoint" in text
    assert "Trace-only replay" in text


def test_screen_is_constructible() -> None:
    screen = TimelineScreen("change-1", "http://127.0.0.1:8000")
    assert screen.change_id == "change-1"
