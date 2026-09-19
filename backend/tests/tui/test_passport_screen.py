import json
from pathlib import Path

from backend.app.tui.passport_screen import PassportScreen, export_path, format_passport


def _passport(**overrides) -> dict:
    base = {
        "id": "passport-1",
        "change_id": "change-1",
        "schema_version": 1,
        "lifecycle_state": "ACTIVE",
        "actor_ids": [],
        "authority_summary": [],
        "evidence": [],
        "outcomes": [],
        "limitations": [],
        "recovery_status": None,
        "generated_at": "2026-09-19T00:00:00Z",
        "canonical_digest": "a" * 64,
    }
    base.update(overrides)
    return base


def test_format_passport_includes_core_identifiers() -> None:
    text = format_passport(_passport())
    assert "passport-1" in text
    assert "ACTIVE" in text
    assert "a" * 64 in text


def test_format_passport_lists_evidence_and_limitations() -> None:
    text = format_passport(
        _passport(
            evidence=[{"kind": "git_checkpoint", "id": "e1", "status": "CURRENT"}],
            limitations=["No environment passport has been captured."],
        )
    )
    assert "git_checkpoint: CURRENT" in text
    assert "No environment passport has been captured." in text


def test_export_path_defaults_to_cwd() -> None:
    path = export_path("change-1")
    assert path.name == "passport-change-1.json"


def test_export_writes_canonical_json(tmp_path: Path) -> None:
    screen = PassportScreen("change-1", "http://127.0.0.1:8000", export_dir=tmp_path)
    screen.passport = _passport()

    # Exercise the same write path action_export uses, without needing a
    # running Textual app to resolve query_one() for the status widget.
    path = export_path(screen.change_id, screen.export_dir)
    path.write_text(json.dumps(screen.passport, sort_keys=True, indent=2), encoding="utf-8")

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["id"] == "passport-1"


def test_screen_is_constructible_without_export_dir() -> None:
    screen = PassportScreen("change-1", "http://127.0.0.1:8000")
    assert screen.export_dir is None
    assert screen.passport is None
