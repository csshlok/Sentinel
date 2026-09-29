"""The policy API reports persisted decisions without caller-supplied evidence."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.contracts.models import ChangeContract
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.tests.passport.test_builder import _seed_change


def test_policy_route_denies_when_no_preset_or_evidence_exists(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    database = Database(path)
    database.initialize()
    change = _seed_change(database)
    app = create_app(settings=Settings(database_path=path),
                     credential_store=InMemoryCredentialStore())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {app.state.api_token}"
        endpoint = f"/api/v1/changes/{change.id}/policy/preset"
        absent = client.get(endpoint)
        assert absent.status_code == 200
        assert absent.json()["decision"] == "DENY"
        assert absent.json()["preset_name"] is None
        assert "No versioned policy preset" in absent.json()["denials"][0]

        contract = ChangeContract(schema_version=3, policy_preset_name="strict",
                                  policy_change_type="code")
        with database.connection() as connection:
            connection.execute("UPDATE changes SET contract_json = ?, revision = revision + 1 "
                               "WHERE id = ?", (contract.model_dump_json(), str(change.id)))
        selected = client.get(endpoint)
        assert selected.status_code == 200
        body = selected.json()
        assert body["preset_name"] == "strict" and body["preset_version"] == "1.0.0"
        assert body["decision"] == "DENY"
        assert any("checks" in reason for reason in body["denials"])
        assert any("AppContainer" in reason for reason in body["denials"])
