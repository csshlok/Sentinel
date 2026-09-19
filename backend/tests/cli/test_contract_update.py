import json

import pytest

from backend.app.cli import main as cli_main
from backend.app.cli.client import ApiClient
from backend.tests.providers.fakes import FakeHttpTransport, json_response

runner = __import__("typer.testing", fromlist=["CliRunner"]).CliRunner()


def test_change_contract_update_sends_expected_body(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeHttpTransport([json_response(200, {"id": "c1", "revision": 2})])

    def factory(api_url: str) -> ApiClient:
        return ApiClient(api_url, transport=transport)

    monkeypatch.setattr(cli_main, "ApiClient", factory)

    result = runner.invoke(
        cli_main.app,
        [
            "change",
            "contract-update",
            "00000000-0000-0000-0000-000000000000",
            "1",
            "--forbidden-path",
            "secrets",
            "--required-check",
            "pytest",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    body = json.loads(transport.calls[0]["body"])
    assert body["expected_revision"] == 1
    assert body["contract"]["forbidden_paths"] == ["secrets"]
    assert body["contract"]["required_checks"] == ["pytest"]
    assert transport.calls[0]["method"] == "PUT"
