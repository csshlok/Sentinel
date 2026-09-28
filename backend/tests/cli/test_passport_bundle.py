"""Passport export and verify commands keep API issuance and offline trust separate."""

from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import backend.app.cli.passport_commands as commands
import backend.app.cli.main as main_module
import backend.app.core.router as router
from backend.app.cli.main import app as cli_app
from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.app.passport.bundle import BundleExporter
from backend.app.passport.cng import CngKey
from backend.app.passport.identity import active_key_name, activate_key_name
from backend.app.passport.jcs import parse_canonical
from backend.app.passport.trust import TrustRegistry
from backend.app.providers.http_transport import HttpResponse
from backend.tests.passport.test_builder import _database, _seed_change
from backend.tests.support_kb import make_repo


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_api_exports_from_change_id_and_rejects_body(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    root = make_repo(tmp_path / "repo", {"README.md": "hello\n"})
    database_path = tmp_path / "state.sqlite3"
    key_name = f"Sentinel disposable test {uuid4()}"
    original = BundleExporter
    monkeypatch.setattr(router, "BundleExporter",
                        lambda db: original(db, key_name=key_name))
    try:
        api = create_app(settings=Settings(database_path=database_path),
                         credential_store=InMemoryCredentialStore())
        with TestClient(api) as client:
            client.headers["Authorization"] = f"Bearer {api.state.api_token}"
            created = client.post("/api/v1/changes", json={
                "title": "portable", "intent": "export", "repository_path": str(root),
            })
            assert created.status_code == 201, created.text
            change_id = created.json()["id"]
            endpoint = f"/api/v1/changes/{change_id}/passport/v2/bundle"
            forged = client.post(endpoint, json={"passport": {"checks_passed": True}})
            assert forged.status_code == 400
            assert forged.json()["error"]["code"] == "PASSPORT_PAYLOAD_FORBIDDEN"
            exported = client.post(endpoint)
            assert exported.status_code == 200, exported.text
            assert exported.content.startswith(b"PK\x03\x04")
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                passport = parse_canonical(archive.read("passport.json"))
            assert passport["claims"]["change_id"] == change_id
            assert exported.headers["x-sentinel-payload-sha256"]
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_cli_export_and_offline_verify_exit_codes(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    database = _database(tmp_path)
    change = _seed_change(database)
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        artifact = BundleExporter(database, key_name=key_name).export(change.id)
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            signature = parse_canonical(archive.read("signature.json"))
        spki = base64.b64decode(signature["public_spki_b64"])

        class FakeTransport:
            def request(self, method, url, *, headers, body, timeout_seconds):
                assert method == "POST" and url.endswith(f"/{change.id}/passport/v2/bundle")
                assert body is None
                return HttpResponse(200, {"X-Sentinel-Payload-SHA256": artifact.payload_sha256},
                                    artifact.content)

        class FakeClient:
            def __init__(self, base_url):
                self.base_url = base_url
                self.token = "test"
                self.timeout_seconds = 10.0
                self.transport = FakeTransport()

        monkeypatch.setattr(commands, "ApiClient", FakeClient)
        runner = CliRunner()
        output = tmp_path / "portable.sentinel"
        exported = runner.invoke(cli_app, ["passport", "export", str(change.id),
                                           "--output", str(output), "--json"])
        assert exported.exit_code == 0, exported.output
        assert json.loads(exported.stdout)["payload_sha256"] == artifact.payload_sha256
        assert output.read_bytes() == artifact.content
        for db_file in tmp_path.glob("*.sqlite3*"):
            db_file.unlink()
        assert runner.invoke(cli_app, ["verify", str(output), "--json"]).exit_code == 2
        trusted = TrustRegistry().add(spki=spki, label="Lab")
        verified = runner.invoke(cli_app, ["verify", str(output), "--json"])
        assert verified.exit_code == 0, verified.output
        assert json.loads(verified.stdout)["claims"]["execution_boundary"] == "UNKNOWN"
        TrustRegistry().revoke(trusted)
        assert runner.invoke(cli_app, ["verify", str(output), "--json"]).exit_code == 2
        assert runner.invoke(cli_app, ["verify", str(tmp_path / "absent")]).exit_code == 3
        assert runner.invoke(cli_app, ["verify", "--unknown-option"]).exit_code == 3
        assert runner.invoke(cli_app, ["verify", "--key"]).exit_code == 3
        malformed = tmp_path / "malformed.sentinel"
        malformed.write_bytes(b"not a zip")
        assert runner.invoke(cli_app, ["verify", str(malformed)]).exit_code == 1
        invalid_json = runner.invoke(cli_app, ["verify", str(malformed), "--json"])
        assert invalid_json.exit_code == 1
        assert json.loads(invalid_json.stdout)["verdict"] == "INVALID"
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


def test_cli_legacy_v1_export_is_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    change_id = uuid4()

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def export_signed_passport(self, requested):
            assert requested == change_id
            return {"schema_version": 1, "signature": "legacy"}

    monkeypatch.setattr(main_module, "ApiClient", FakeClient)
    response = CliRunner().invoke(cli_app, ["passport", "export", str(change_id),
                                            "--v1", "--json"])
    assert response.exit_code == 0, response.output
    assert json.loads(response.stdout)["schema_version"] == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_identity_rotation_switches_api_signer_and_emits_statement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    database = _database(tmp_path)
    change = _seed_change(database)
    old_name = f"Sentinel disposable test {uuid4()}"
    successor_name = None
    with CngKey.open(name=old_name) as old:
        old_spki = old.public_spki()
    try:
        activate_key_name(old_name)
        destination = tmp_path / "rotation.json"
        rotated = CliRunner().invoke(cli_app, ["identity", "rotate", "--output",
                                               str(destination), "--json"])
        assert rotated.exit_code == 0, rotated.output
        successor_name = active_key_name()
        assert successor_name != old_name
        statement = json.loads(destination.read_text(encoding="utf-8"))
        trust = TrustRegistry(tmp_path / "recipient.json")
        trust.add(spki=old_spki, label="Old")
        assert trust.apply_rotation(statement) == json.loads(rotated.stdout)["new_fingerprint"]
        api = create_app(settings=Settings(database_path=tmp_path / "passport.sqlite3"),
                         credential_store=InMemoryCredentialStore())
        with TestClient(api) as client:
            client.headers["Authorization"] = f"Bearer {api.state.api_token}"
            issued = client.post(f"/api/v1/changes/{change.id}/passport/v2/issue")
            assert issued.status_code == 200, issued.text
            assert issued.json()["signer_fingerprint"] == statement["new_fingerprint"]
    finally:
        for name in (successor_name, old_name):
            if name is not None:
                with CngKey.open(name=name) as key:
                    key.delete_for_test()
