"""One installed package version is reported by every release surface."""

from __future__ import annotations

from importlib.metadata import version

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from backend.app.cli.main import app as cli_app
from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.app.passport.v2 import PassportV2Issuer
from backend.app.policy.version import product_version
from backend.tests.passport.test_builder import _database, _seed_change


def test_version_matches_package_api_cli_and_signed_payload(tmp_path) -> None:
    expected = version("change-assurance")
    assert product_version() == expected

    cli = CliRunner().invoke(cli_app, ["--version"])
    assert cli.exit_code == 0
    assert cli.stdout.strip() == expected

    database = _database(tmp_path)
    change = _seed_change(database)
    assert PassportV2Issuer(database).snapshot(change.id).product_version == expected

    api = create_app(settings=Settings(database_path=tmp_path / "passport.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    with TestClient(api) as client:
        client.headers["Authorization"] = f"Bearer {api.state.api_token}"
        response = client.get("/api/v1/version")
    assert response.status_code == 200
    assert response.json() == {"product_version": expected}
