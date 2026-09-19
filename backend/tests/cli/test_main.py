import json

import pytest
from typer.testing import CliRunner

from backend.app.cli import main as cli_main
from backend.app.cli.client import ApiClient
from backend.tests.providers.fakes import FakeHttpTransport, json_response

runner = CliRunner()


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: FakeHttpTransport) -> None:
    def factory(api_url: str) -> ApiClient:
        return ApiClient(api_url, transport=transport)

    monkeypatch.setattr(cli_main, "ApiClient", factory)


def test_capabilities_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeHttpTransport([json_response(200, {"items": []})])
    _patch_client(monkeypatch, transport)

    result = runner.invoke(cli_main.app, ["capabilities", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"items": []}


def test_api_error_exits_1_and_prints_code(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeHttpTransport(
        [json_response(404, {"error": {"code": "CHANGE_NOT_FOUND", "message": "no", "details": {}}})]
    )
    _patch_client(monkeypatch, transport)

    result = runner.invoke(
        cli_main.app, ["change", "show", "00000000-0000-0000-0000-000000000000", "--json"]
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "CHANGE_NOT_FOUND"


def test_connection_error_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.providers.http_transport import TransportTimeout

    transport = FakeHttpTransport([TransportTimeout("unreachable")])
    _patch_client(monkeypatch, transport)

    result = runner.invoke(cli_main.app, ["capabilities", "--json"])

    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "CONNECTION_ERROR"


def test_change_create_and_list(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeHttpTransport(
        [
            json_response(201, {"id": "c1", "title": "My change"}),
            json_response(200, {"items": [{"id": "c1"}], "count": 1}),
        ]
    )
    _patch_client(monkeypatch, transport)

    created = runner.invoke(
        cli_main.app,
        ["change", "create", "My change", "Do a thing", "C:\\repo", "--json"],
    )
    assert created.exit_code == 0
    assert json.loads(created.stdout)["id"] == "c1"

    listed = runner.invoke(cli_main.app, ["change", "list", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["count"] == 1


def test_recovery_execute_passes_approval_token(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeHttpTransport([json_response(200, {"status": "RECOVERED"})])
    _patch_client(monkeypatch, transport)

    result = runner.invoke(
        cli_main.app,
        [
            "recovery",
            "execute",
            "00000000-0000-0000-0000-000000000000",
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
            "approval-token",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "RECOVERED"
    body = json.loads(transport.calls[0]["body"])
    assert body["approval_token"] == "approval-token"


def test_no_color_env_var_disables_color(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeHttpTransport([json_response(200, {"items": []})])
    _patch_client(monkeypatch, transport)
    monkeypatch.setenv("NO_COLOR", "1")

    result = runner.invoke(cli_main.app, ["capabilities"])

    assert result.exit_code == 0
    assert "\x1b[" not in result.stdout
