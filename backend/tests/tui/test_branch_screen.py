from backend.app.tui.branch_screen import BranchScreen, _node_label


def test_screen_is_constructible_without_actor_id() -> None:
    screen = BranchScreen("change-1", "http://127.0.0.1:8000")
    assert screen.actor_id is None
    assert screen._checkpoint_ids == []


def test_screen_stores_actor_id_when_given() -> None:
    screen = BranchScreen("change-1", "http://127.0.0.1:8000", actor_id="actor-1")
    assert screen.actor_id == "actor-1"


def test_node_label_marks_the_current_change() -> None:
    change = {"id": "abc12345-0000-4000-8000-000000000000", "title": "t", "lifecycle_state": "ACTIVE"}
    current = _node_label(change, is_current=True)
    other = _node_label(change, is_current=False)
    assert "HERE" in current
    assert "HERE" not in other
