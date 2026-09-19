from backend.app.tui.evidence_screen import EvidenceScreen, format_evidence


def test_format_evidence_all_missing_shows_honest_empty_states() -> None:
    text = format_evidence(None, None, None, None, None)
    assert "No Git checkpoints captured yet." in text
    assert "No environment passport captured yet." in text
    assert "No dependency changes recorded yet." in text
    assert "No assurance plan created yet." in text


def test_format_evidence_shows_checkpoints_and_dependencies() -> None:
    text = format_evidence(
        {"items": [{"name": "baseline", "branch": "main", "head_sha": "a" * 40}]},
        None,
        {"changes": [{"ecosystem": "npm", "package": "left-pad", "old_version": "1.0", "new_version": "1.1"}]},
        None,
        None,
    )
    assert "baseline" in text
    assert "left-pad" in text


def test_format_evidence_shows_assurance_facts() -> None:
    text = format_evidence(
        None,
        None,
        None,
        None,
        {
            "required_assurance_passed": True,
            "assurance_fresh": False,
            "deviations_resolved": True,
            "required_evidence_complete": False,
            "reasons": ["environment evidence is stale"],
        },
    )
    assert "environment evidence is stale" in text


def test_screen_is_constructible() -> None:
    screen = EvidenceScreen("change-1", "http://127.0.0.1:8000")
    assert screen.change_id == "change-1"
