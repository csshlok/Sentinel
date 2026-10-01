"""The HTTP measurement route obeys and persists the Change Contract rule."""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from backend.app.assurance.store import EvidenceStore
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.tests.support_kb import make_repo, write


def test_http_measurement_uses_contract_rule_and_persists_result(tmp_path) -> None:
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "__pycache__/\n.pytest_cache/\n.coverage\n",
        "module.py": "def old():\n    return 1\n\ndef unused():\n    return 1\n",
        "tests/test_old.py": "from module import old\n\ndef test_old():\n    assert old() == 1\n",
    })
    database = tmp_path / "state" / "api.sqlite3"
    app = create_app(settings=Settings(database_path=database),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        created = client.post("/api/v1/changes", json={
            "title": "diff", "intent": "measure", "repository_path": str(root),
            "contract": {"schema_version": 2, "diff_coverage_rule": {
                "required": True, "minimum_percent": 100, "policy_version": "required-v1"}},
        })
        assert created.status_code == 201, created.text
        change_id = created.json()["id"]
        base = f"/api/v1/changes/{change_id}"
        baseline = client.post(f"{base}/evidence/baseline")
        assert baseline.status_code == 201, baseline.text
        write(root, "module.py", "def old():\n    return 1\n\ndef unused():\n    return 2\n")
        tested = client.post(f"{base}/evidence/current")
        assert tested.status_code == 201, tested.text
        measured = client.post(f"{base}/assurance/diff-coverage", json={
            "baseline_checkpoint_id": baseline.json()["checkpoint"]["id"],
            "tested_checkpoint_id": tested.json()["checkpoint"]["id"],
            "interpreter_path": sys.executable,
            "test_args": ["--collect-only"],
            "rule": {"required": True, "minimum_percent": 1},
        })
        assert measured.status_code == 200, measured.text
        body = measured.json()
        assert body["threshold"] == 100
        assert "--collect-only" not in body["command"]
        # IN-05: no host path (box python, scratch, tree) is persisted in the command.
        assert body["command"][0] == "<box-python>"
        assert not any("AppData" in part or str(root) in part for part in body["command"])
        assert "--rootdir=<tree>" in body["command"]
        assert body["diff_exercised"] == "FAIL"
        assert body["gate_satisfied"] is False
        stored = EvidenceStore(Database(database)).latest_diff_coverage(change_id)
        assert stored is not None and stored.artifact_digest == body["artifact_digest"]
        events = client.get(f"{base}/events")
        assert events.status_code == 200, events.text
        coverage_events = [item for item in events.json()["items"]
                           if item["subject_type"] == "diff_coverage"]
        assert len(coverage_events) == 1
        assert coverage_events[0]["payload"]["artifact_digest"] == body["artifact_digest"]
        # WR-02: the host test harness's token facts do not verify, so neither the
        # result nor the signed journal may claim the box boundary.
        assert body["boundary"] is None
        assert coverage_events[0]["payload"]["check_run_id"] == body["check_run_id"]
        assert coverage_events[0]["payload"]["check_boundary"] is None
