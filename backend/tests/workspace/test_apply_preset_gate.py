"""Plan 02-05: a selected policy preset gates REVIEW_READY and workspace apply-back.

User decision: REVIEW_READY gets the full preset decision; apply-back enforces
only the rules decidable before apply (sealed-diff paths, agent-run boundary),
because checks and coverage are refused while agent work is unapplied.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.core.preset_gate import review_ready_gate
from backend.app.policy.presets import pre_apply_denials
from backend.tests.support_kb import write
from backend.tests.workspace.conftest import repo_fingerprint
from backend.tests.workspace.test_routes import FACTS, _head, _repo, api, windows_only  # noqa: F401

DOCS = {"schema_version": 3, "policy_preset_name": "docs-only", "policy_change_type": "docs"}


@pytest.mark.parametrize(("preset", "kind", "paths", "modes", "boundary", "denied"), [
    ("docs-only", "docs", ("README.md",), (), "UNKNOWN", False),
    ("docs-only", "docs", ("README.md", "calc.py"), (), "UNKNOWN", True),
    ("docs-only", "docs", (), (), "UNKNOWN", True),
    ("docs-only", "docs", ("README.md",), ("README.md",), "UNKNOWN", True),
    ("strict", "code", ("calc.py",), (), "MIXED", True),
    ("strict", "code", ("calc.py",), (), "APPCONTAINER", False),
    # Coverage and checks are not decidable before apply: enforced at REVIEW_READY.
    ("standard", "code", ("calc.py",), (), "UNKNOWN", False),
    ("docs-only", "code", ("README.md",), (), "APPCONTAINER", True),
])
def test_pre_apply_rules(preset, kind, paths, modes, boundary, denied) -> None:
    reasons = pre_apply_denials(preset_name=preset, change_type=kind, changed_paths=paths,
                                mode_changed_paths=modes, execution_boundary=boundary)
    assert bool(reasons) is denied, reasons


def test_review_gate_ignores_a_change_without_a_preset(monkeypatch) -> None:
    from backend.app.contracts.models import ChangeContract

    class Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no snapshot is needed without a preset")

    monkeypatch.setattr("backend.app.passport.v2.PassportV2Issuer", Boom)
    change = type("C", (), {"contract": ChangeContract(), "id": uuid4()})()
    review_ready_gate(None, change)  # type: ignore[arg-type]


def test_review_gate_refuses_unknown_evidence(monkeypatch) -> None:
    from backend.app.contracts.models import ChangeContract

    class Failing:
        def __init__(self, *args, **kwargs):
            pass

        def snapshot(self, change_id):
            raise AppError("PASSPORT_LAUNCH_IN_PROGRESS", "in progress", status_code=409)

    monkeypatch.setattr("backend.app.passport.v2.PassportV2Issuer", Failing)
    change = type("C", (), {"contract": ChangeContract(**DOCS), "id": uuid4()})()
    with pytest.raises(AppError) as raised:
        review_ready_gate(None, change)  # type: ignore[arg-type]
    assert raised.value.code == "PRESET_GATE_DENIED"
    assert raised.value.details["gate"] == "REVIEW_READY"
    assert "UNKNOWN" in raised.value.details["reasons"][0]


def test_review_gate_refuses_a_deny_and_passes_an_allow(tmp_path) -> None:
    from backend.app.contracts.models import ChangeContract
    from backend.app.passport.v2 import PassportV2Issuer

    class Fixed:
        def __init__(self, decision):
            self.decision = decision

        def __call__(self, *args, **kwargs):
            return self

        def snapshot(self, change_id):
            return type("S", (), {"policy_decision": self.decision,
                                  "policy_denials": ["docs-only paths are missing"]})()

    change = type("C", (), {"contract": ChangeContract(**DOCS), "id": uuid4()})()
    import backend.app.passport.v2 as v2

    original = v2.PassportV2Issuer
    try:
        v2.PassportV2Issuer = Fixed("DENY")
        with pytest.raises(AppError) as raised:
            review_ready_gate(None, change)  # type: ignore[arg-type]
        assert raised.value.details["reasons"] == ["docs-only paths are missing"]
        v2.PassportV2Issuer = Fixed("ALLOW")
        review_ready_gate(None, change)  # type: ignore[arg-type]
    finally:
        v2.PassportV2Issuer = original
    assert PassportV2Issuer is original


def _preset_change(client, repo: Path):
    created = client.post("/api/v1/changes", json={
        "title": "docs change", "intent": "update the docs", "repository_path": str(repo),
        "contract": DOCS})
    assert created.status_code == 201, created.text
    change = created.json()
    human = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}).json()
    agent = client.post("/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}).json()
    response = client.post("/api/v1/delegations", json={
        "grantor_id": human["id"], "grantee_id": agent["id"], "change_id": change["id"],
        "scopes": ["workspace.apply"], "ttl_seconds": 3600})
    assert response.status_code == 201, response.text
    return change, agent["id"]


def _edit_and_preview(app, client, change_id: str, repo: Path, files: dict[str, str]) -> str:
    manager = app.state.workspace_manager
    run_id = uuid4()
    record = manager.ensure(UUID(change_id), str(repo), run_id=run_id)
    for name, text in files.items():
        write(record.workspace_path, name, text)
    manager.finish_run(record.id, run_id, facts={**FACTS, "profile_name": record.profile_name},
                       status="COMPLETED")
    preview = client.post(f"/api/v1/changes/{change_id}/workspace/preview")
    assert preview.status_code == 200, preview.text
    return preview.json()["approval_token"]


@windows_only
def test_apply_back_of_code_under_a_docs_preset_is_refused(api, tmp_path) -> None:  # noqa: F811
    app, client = api
    repo = _repo(tmp_path)
    before, fingerprint = _head(repo), repo_fingerprint(repo)
    change, agent = _preset_change(client, repo)
    token = _edit_and_preview(app, client, change["id"], repo,
                              {"README.md": "docs\n", "calc.py": "def add(a, b):\n    return 0\n"})
    refused = client.post(f"/api/v1/changes/{change['id']}/workspace/apply",
                          json={"actor_id": agent, "approval_token": token})
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "PRESET_GATE_DENIED" and error["details"]["gate"] == "APPLY"
    assert _head(repo) == before and repo_fingerprint(repo) == fingerprint


@windows_only
def test_apply_back_of_docs_under_a_docs_preset_proceeds(api, tmp_path) -> None:  # noqa: F811
    app, client = api
    repo = _repo(tmp_path)
    change, agent = _preset_change(client, repo)
    token = _edit_and_preview(app, client, change["id"], repo, {"README.md": "better docs\n"})
    applied = client.post(f"/api/v1/changes/{change['id']}/workspace/apply",
                          json={"actor_id": agent, "approval_token": token})
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    assert (repo / "README.md").read_text(encoding="utf-8").replace("\r\n", "\n") == "better docs\n"


@pytest.mark.parametrize(("contract", "gated"), [(DOCS, True), (None, False)])
def test_review_ready_runs_the_preset_gate_through_the_api(api, tmp_path, contract,  # noqa: F811
                                                           gated) -> None:
    from backend.app.contracts.models import LifecycleFacts

    app, client = api
    repo = _repo(tmp_path)
    body = {"title": "gate", "intent": "reach review", "repository_path": str(repo)}
    if contract is not None:
        body["contract"] = contract
    change = client.post("/api/v1/changes", json=body).json()
    with app.state.database.connection() as connection:
        connection.execute("UPDATE changes SET lifecycle_state = 'LOCALLY_VERIFIED' WHERE id = ?",
                           (change["id"],))
    revision = client.get(f"/api/v1/changes/{change['id']}").json()["revision"]

    class AllFacts:
        def get_facts(self, change, target_state):
            return LifecycleFacts(**{name: True for name in LifecycleFacts.model_fields})

    app.state.change_service.lifecycle_facts = AllFacts()
    moved = client.post(f"/api/v1/changes/{change['id']}/transition", json={
        "target_state": "REVIEW_READY", "expected_revision": revision})
    if gated:
        assert moved.status_code == 409, moved.text
        assert moved.json()["error"]["code"] == "PRESET_GATE_DENIED"
        state = client.get(f"/api/v1/changes/{change['id']}").json()["lifecycle_state"]
        assert state == "LOCALLY_VERIFIED"
    else:
        assert moved.status_code == 200, moved.text
        assert moved.json()["lifecycle_state"] == "REVIEW_READY"
