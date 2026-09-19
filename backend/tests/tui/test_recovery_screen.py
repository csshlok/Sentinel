from backend.app.tui.recovery_screen import RecoveryScreen, format_plan


def _plan(**overrides) -> dict:
    base = {
        "id": "plan-1",
        "status": "PLANNED",
        "actions": [],
        "unsupported_effects": [],
        "conflicts": [],
    }
    base.update(overrides)
    return base


def test_format_plan_with_no_actions() -> None:
    text = format_plan(_plan())
    assert "No supported recovery actions." in text


def test_format_plan_shows_supported_action() -> None:
    text = format_plan(
        _plan(
            actions=[
                {
                    "kind": "git.revert_commits",
                    "description": "Revert 2 commits",
                    "supported": True,
                    "limitations": [],
                }
            ]
        )
    )
    assert "supported" in text
    assert "Revert 2 commits" in text


def test_format_plan_shows_blocked_action_and_limitation() -> None:
    text = format_plan(
        _plan(
            actions=[
                {
                    "kind": "git.revert_commits",
                    "description": "Revert 2 commits",
                    "supported": False,
                    "limitations": ["A merge conflict was detected."],
                }
            ]
        )
    )
    assert "blocked" in text
    assert "A merge conflict was detected." in text


def test_format_plan_shows_conflicts_and_unsupported_effects() -> None:
    text = format_plan(
        _plan(
            conflicts=["Revert produced a merge conflict."],
            unsupported_effects=["Uncommitted files are not restorable."],
        )
    )
    assert "Revert produced a merge conflict." in text
    assert "Uncommitted files are not restorable." in text


def test_screen_without_actor_id_is_constructible() -> None:
    screen = RecoveryScreen("change-1", "http://127.0.0.1:8000", None)
    assert screen.actor_id is None
    assert screen.plan is None
