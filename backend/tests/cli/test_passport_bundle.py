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
import backend.app.core.router as router
from backend.app.cli.main import app as cli_app
from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.app.passport.bundle import BundleExporter
from backend.app.passport.cng import CngKey
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
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()
