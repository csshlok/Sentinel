"""`sentinel workspace show|preview|apply|discard|sweep` against a fake HTTP transport."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from backend.app.cli import main as cli_main
from backend.app.cli.client import ApiClient
from backend.app.providers.http_transport import TransportTimeout
from backend.tests.providers.fakes import FakeHttpTransport, json_response

runner = CliRunner()
CHANGE = "00000000-0000-0000-0000-000000000001"
ACTOR = "11111111-1111-1111-1111-111111111111"
BASE = "http://127.0.0.1:8000"


def _patch(monkeypatch: pytest.MonkeyPatch, *responses) -> FakeHttpTransport:
    transport = FakeHttpTransport(list(responses))
    monkeypatch.setattr(cli_main, "ApiClient",
                        lambda api_url: ApiClient(api_url, transport=transport))
    return transport


def _only_call(transport: FakeHttpTransport) -> dict:
    assert len(transport.calls) == 1
    return transport.calls[0]


def test_show_gets_the_workspace_and_prints_one_json_object(monkeypatch) -> None:
    transport = _patch(monkeypatch, json_response(200, {"id": "w1", "state": "READY"}))
    result = runner.invoke(cli_main.app, ["workspace", "show", CHANGE, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"id": "w1", "state": "READY"}
    assert len(result.stdout.strip().splitlines()) == 1
    call = _only_call(transport)
    assert call["method"] == "GET"
    assert call["url"] == f"{BASE}/api/v1/changes/{CHANGE}/workspace"
    assert call["body"] is None


def test_preview_posts_to_the_preview_route(monkeypatch) -> None:
    transport = _patch(monkeypatch, json_response(200, {"approval_token": "t"}))
    result = runner.invoke(cli_main.app, ["workspace", "preview", CHANGE, "--json"])
    assert result.exit_code == 0, result.output
    call = _only_call(transport)
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/v1/changes/{CHANGE}/workspace/preview"


def test_apply_posts_actor_and_token(monkeypatch) -> None:
    transport = _patch(monkeypatch, json_response(200, {"applied": True}))
    result = runner.invoke(cli_main.app,
                           ["workspace", "apply", CHANGE, ACTOR, "approval-token", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"applied": True}
    call = _only_call(transport)
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/v1/changes/{CHANGE}/workspace/apply"
    assert json.loads(call["body"]) == {"actor_id": ACTOR, "approval_token": "approval-token"}


def test_discard_posts_the_actor(monkeypatch) -> None:
    transport = _patch(monkeypatch, json_response(200, {"state": "CLEANED"}))
    result = runner.invoke(cli_main.app, ["workspace", "discard", CHANGE, ACTOR, "--json"])
    assert result.exit_code == 0, result.output
    call = _only_call(transport)
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/v1/changes/{CHANGE}/workspace/discard"
    assert json.loads(call["body"]) == {"actor_id": ACTOR}


def test_sweep_posts_to_the_sweep_route(monkeypatch) -> None:
    transport = _patch(monkeypatch,
                       json_response(200, {"cleaned": [], "preserved": [], "failed": []}))
    result = runner.invoke(cli_main.app, ["workspace", "sweep", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["cleaned"] == []
    call = _only_call(transport)
    assert call["method"] == "POST"
    assert call["url"] == f"{BASE}/api/v1/workspaces/sweep"


def test_api_error_exits_1_with_the_code(monkeypatch) -> None:
    _patch(monkeypatch, json_response(404, {"error": {
        "code": "WORKSPACE_NOT_FOUND", "message": "none", "details": {}}}))
    result = runner.invoke(cli_main.app, ["workspace", "show", CHANGE, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["code"] == "WORKSPACE_NOT_FOUND"


def test_api_error_plain_output_names_the_code(monkeypatch) -> None:
    _patch(monkeypatch, json_response(404, {"error": {
        "code": "WORKSPACE_NOT_FOUND", "message": "none", "details": {}}}))
    result = runner.invoke(cli_main.app, ["workspace", "show", CHANGE, "--no-color"])
    assert result.exit_code == 1
    assert "WORKSPACE_NOT_FOUND" in result.stdout


def test_transport_timeout_exits_2(monkeypatch) -> None:
    _patch(monkeypatch, TransportTimeout("unreachable"))
    result = runner.invoke(cli_main.app, ["workspace", "sweep", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "CONNECTION_ERROR"
