from backend.app.tui.detail_screen import DetailScreen, format_change


def _change(**overrides) -> dict:
    base = {
        "id": "change-1",
        "title": "My change",
        "intent": "Do a thing",
        "repository_path": "C:\\repo",
        "lifecycle_state": "ACTIVE",
        "review_state": "MISSING_EVIDENCE",
        "risk_level": "LOW",
        "revision": 2,
        "contract": {
            "allowed_paths": ["**"],
            "forbidden_paths": ["secrets"],
            "authority_ceiling": ["github.pr.create"],
            "max_risk": "MEDIUM",
            "required_checks": ["pytest"],
        },
        "git_summary": None,
        "verification": None,
    }
    base.update(overrides)
    return base


def test_format_change_includes_core_fields() -> None:
    text = format_change(_change())
    assert "My change" in text
    assert "ACTIVE" in text
    assert "MISSING_EVIDENCE" in text


def test_format_change_shows_contract_details() -> None:
    text = format_change(_change())
    assert "secrets" in text
    assert "github.pr.create" in text


def test_format_change_handles_missing_git_and_verification() -> None:
    text = format_change(_change())
    assert "No Git evidence captured yet." in text
    assert "No verification result recorded yet." in text


def test_format_change_shows_git_and_verification_when_present() -> None:
    text = format_change(
        _change(
            git_summary={
                "branch": "main",
                "head_sha": "a" * 40,
                "is_clean": False,
                "total_additions": 3,
                "total_deletions": 1,
            },
            verification={"status": "PASSED", "exit_code": 0},
        )
    )
    assert "main" in text
    assert "dirty" in text
    assert "PASSED" in text


def test_screen_is_constructible() -> None:
    screen = DetailScreen("change-1", "http://127.0.0.1:8000")
    assert screen.change_id == "change-1"
