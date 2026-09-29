"""GitHub CLI commands use only local API paths and typed JSON results."""

from __future__ import annotations

import json
from uuid import uuid4

from typer.testing import CliRunner

from backend.app.cli.main import app


def test_github_check_cli_posts_change_id_without_claim_payload(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            assert base_url == "http://127.0.0.1:8000"

        def _request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"state": "GITHUB_APP_NOT_INSTALLED",
                    "installation_url": "https://github.com/apps/sentinel-lab/installations/new"}

    monkeypatch.setattr("backend.app.cli.github_commands.ApiClient", FakeClient)
    change_id = uuid4()
    result = CliRunner().invoke(app, ["github", "check", str(change_id), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "GITHUB_APP_NOT_INSTALLED"
    assert calls == [("POST", f"/api/v1/changes/{change_id}/providers/github/checks", {})]


def test_github_app_cli_create_and_status_are_owner_scoped(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, base_url):
            pass

        def _request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return {"owner": "Lab", "configured": False}

    monkeypatch.setattr("backend.app.cli.github_commands.ApiClient", FakeClient)
    runner = CliRunner()
    created = runner.invoke(app, ["github", "app", "create", "Lab",
                                  "--account-kind", "organization", "--json"])
    status = runner.invoke(app, ["github", "app", "status", "Lab", "--json"])
    assert created.exit_code == status.exit_code == 0
    assert calls == [
        ("POST", "/api/v1/providers/github/app/flows",
         {"json_body": {"owner": "Lab", "account_kind": "organization"}}),
        ("GET", "/api/v1/providers/github/app/status/Lab", {}),
    ]
    invalid = runner.invoke(app, ["github", "app", "status", "../other"])
    assert invalid.exit_code != 0
    assert len(calls) == 2
