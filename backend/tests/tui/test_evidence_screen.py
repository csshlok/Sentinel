from backend.app.tui.evidence_screen import EvidenceScreen, format_evidence, format_run_detail


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


def test_run_detail_shows_each_boundary_in_its_own_colour() -> None:
    """Plan 02-04 (SC4): the TUI alone tells an AppContainer run from a reduced-token run."""

    box = format_run_detail({"execution_boundary": {
        "kind": "APPCONTAINER", "capabilities": ["internetClient"], "integrity_rid": "0x1000",
        "job_verified": True, "workspace_drive": "Z:"}})
    reduced = format_run_detail({"execution_boundary": {"kind": "RESTRICTED_TOKEN"}})
    unknown = format_run_detail({})
    assert "[bold green]Boundary: AppContainer (capabilities: internetClient" in box
    assert "[bold yellow]Boundary: reduced token only" in reduced and "AppContainer" not in reduced
    assert "[bold red]Boundary: not observed" in unknown
