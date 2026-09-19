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


CHANGE = "00000000-0000-0000-0000-000000000000"
ACTOR = "22222222-2222-2222-2222-222222222222"
PLAN = "11111111-1111-1111-1111-111111111111"


def _invoke(monkeypatch, payload, argv):
    transport = FakeHttpTransport([json_response(200, payload)])
    _patch_client(monkeypatch, transport)
    args = list(argv)
    cut = args.index("--") if "--" in args else len(args)     # options must precede `--`
    result = runner.invoke(cli_main.app, [*args[:cut], "--json", *args[cut:]])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout), transport.calls[0]


@pytest.mark.parametrize(("argv", "method", "path"), [
    (["evidence", "show", CHANGE], "GET", f"/changes/{CHANGE}/evidence"),
    (["evidence", "baseline", CHANGE], "POST", f"/changes/{CHANGE}/evidence/baseline"),
    (["evidence", "current", CHANGE], "POST", f"/changes/{CHANGE}/evidence/current"),
    (["agent", "adapters"], "GET", "/agents/adapters"),
    (["agent", "list", CHANGE], "GET", f"/changes/{CHANGE}/agents"),
    (["assurance", "plan", CHANGE], "POST", f"/changes/{CHANGE}/assurance/plan"),
    (["assurance", "show", CHANGE], "GET", f"/changes/{CHANGE}/assurance/plan"),
    (["assurance", "evaluate", CHANGE, PLAN], "GET", f"/changes/{CHANGE}/assurance/{PLAN}/evaluation"),
    (["assurance", "facts", CHANGE], "GET", f"/changes/{CHANGE}/assurance/facts"),
])
def test_evidence_agent_assurance_commands_call_the_right_routes(monkeypatch, argv, method, path):
    result, call = _invoke(monkeypatch, {"ok": True}, argv)
    assert result == {"ok": True}
    assert call["method"] == method and call["url"].endswith("/api/v1" + path)


@pytest.mark.parametrize(("argv", "method", "path"), [
    (["events", "show", CHANGE], "GET", f"/changes/{CHANGE}/events?since_seq=1"),
    (["replay", "show", CHANGE], "GET", f"/changes/{CHANGE}/replay"),
    (["replay", "verify", CHANGE], "GET", f"/changes/{CHANGE}/replay/verify"),
    (["replay", "export", CHANGE], "GET", f"/changes/{CHANGE}/replay/export"),
])
def test_events_and_replay_commands_call_the_right_routes(monkeypatch, argv, method, path):
    result, call = _invoke(monkeypatch, {"ok": True}, argv)
    assert result == {"ok": True}
    assert call["method"] == method and call["url"].endswith("/api/v1" + path)


def test_events_show_type_filter_is_forwarded(monkeypatch):
    result, call = _invoke(
        monkeypatch, {"ok": True}, ["events", "show", CHANGE, "--type", "change.created"]
    )
    assert result == {"ok": True}
    assert call["url"].endswith(f"/api/v1/changes/{CHANGE}/events?since_seq=1&event_type=change.created")


def test_replay_export_writes_to_file(monkeypatch, tmp_path):
    out_path = tmp_path / "bundle.json"
    payload = {"change_id": CHANGE, "events": [], "effects": [], "chain_verified": True}
    result, call = _invoke(
        monkeypatch, payload, ["replay", "export", CHANGE, "--out", str(out_path)]
    )
    assert result == {"written_to": str(out_path)}
    assert call["method"] == "GET" and call["url"].endswith(f"/api/v1/changes/{CHANGE}/replay/export")
    assert json.loads(out_path.read_text(encoding="utf-8")) == payload


def test_agent_launch_sends_arguments_and_waits_longer_than_the_agent(monkeypatch):
    result, call = _invoke(monkeypatch, {"status": "PASSED"}, [
        "agent", "launch", CHANGE, ACTOR, "python", "--timeout", "120", "--env", "KEEP_ME",
        "--adapter", "generic", "--", "-c", "print(1)"])
    body = json.loads(call["body"])
    assert body["actor_id"] == ACTOR and body["launch"]["executable"] == "python"
    assert body["launch"]["args"] == ["-c", "print(1)"]
    assert body["launch"]["environment_keys"] == ["KEEP_ME"]
    assert body["launch"]["timeout_seconds"] == 120 and body["output_limit_bytes"] == 200_000


def test_agent_launch_waits_longer_than_the_agent_timeout():
    seen = []

    class Spy(FakeHttpTransport):
        def request(self, method, url, *, headers, body, timeout_seconds):
            seen.append(timeout_seconds)
            return super().request(method, url, headers=headers, body=body,
                                   timeout_seconds=timeout_seconds)

    client = ApiClient("http://x", transport=Spy([json_response(200, {}), json_response(200, {})]))
    client.launch_agent(CHANGE, actor_id=ACTOR, executable="python", args=[], timeout_seconds=120)
    client.get_evidence(CHANGE)
    assert seen == [180, 10.0]


def test_attach_stop_and_assurance_run_bodies(monkeypatch):
    _, call = _invoke(monkeypatch, {}, ["agent", "attach", CHANGE, ACTOR, "claude", "ext-9"])
    assert json.loads(call["body"])["attach"] == {"adapter": "claude", "external_run_id": "ext-9"}
    _, call = _invoke(monkeypatch, {}, ["agent", "stop", CHANGE, PLAN, ACTOR])
    assert call["url"].endswith(f"/agents/{PLAN}/stop") and json.loads(call["body"]) == {"actor_id": ACTOR}
    _, call = _invoke(monkeypatch, {}, ["assurance", "run", CHANGE, PLAN, ACTOR, "--output-limit", "500"])
    assert json.loads(call["body"]) == {"actor_id": ACTOR, "output_limit_bytes": 500}


def test_policy_denial_surfaces_as_exit_code_1(monkeypatch):
    transport = FakeHttpTransport([json_response(403, {"error": {
        "code": "POLICY_DENIED", "message": "no authority", "details": {}}})])
    _patch_client(monkeypatch, transport)
    result = runner.invoke(cli_main.app, ["agent", "launch", CHANGE, ACTOR, "python", "--json"])
    assert result.exit_code == 1 and json.loads(result.stdout)["error"]["code"] == "POLICY_DENIED"


@pytest.mark.parametrize(("argv", "method", "suffix"), [
    (["evidence", "checkpoints", CHANGE], "GET", f"/changes/{CHANGE}/git/checkpoints"),
    (["evidence", "compare", CHANGE, PLAN, ACTOR], "GET",
     f"/changes/{CHANGE}/git/compare?baseline_id={PLAN}&current_id={ACTOR}"),
    (["evidence", "environment", CHANGE], "GET", f"/changes/{CHANGE}/environment"),
    (["evidence", "dependencies", CHANGE], "GET", f"/changes/{CHANGE}/dependencies"),
])
def test_evidence_read_commands(monkeypatch, argv, method, suffix):
    result, call = _invoke(monkeypatch, {"ok": True}, argv)
    assert result == {"ok": True}
    assert call["method"] == method and call["url"].endswith("/api/v1" + suffix)


@pytest.mark.parametrize("argv", [
    ["evidence", "baseline", CHANGE], ["evidence", "current", CHANGE],
    ["assurance", "plan", CHANGE], ["assurance", "run", CHANGE, PLAN, ACTOR],
])
def test_mutating_evidence_commands_forward_the_idempotency_key(monkeypatch, argv):
    _, call = _invoke(monkeypatch, {}, [*argv, "--idempotency-key", "key-12345678"])
    assert call["headers"]["Idempotency-Key"] == "key-12345678"


TOOL = "33333333-3333-3333-3333-333333333333"


@pytest.mark.parametrize(("argv", "method", "path"), [
    (["tool", "list"], "GET", "/tools"),
    (["tool", "show", TOOL], "GET", f"/tools/{TOOL}"),
    (["tool", "for-change", CHANGE], "GET", f"/changes/{CHANGE}/tools"),
])
def test_tool_read_commands_call_the_right_routes(monkeypatch, argv, method, path):
    result, call = _invoke(monkeypatch, {"ok": True}, argv)
    assert result == {"ok": True}
    assert call["method"] == method and call["url"].endswith("/api/v1" + path)


def test_tool_trust_sends_decision_body(monkeypatch):
    result, call = _invoke(
        monkeypatch, {"decision": "APPROVE"},
        ["tool", "trust", TOOL, "APPROVE", "--actor-id", ACTOR,
         "--scope", "exact_version", "--reason", "Reviewed", "--change-id", CHANGE],
    )
    assert result == {"decision": "APPROVE"}
    assert call["method"] == "POST" and call["url"].endswith(f"/api/v1/tools/{TOOL}/trust")
    body = json.loads(call["body"])
    assert body == {
        "actor_id": ACTOR, "decision": "APPROVE", "scope": "exact_version",
        "reason": "Reviewed", "change_id": CHANGE,
    }


def test_tool_trust_omits_optional_fields_when_not_given(monkeypatch):
    _, call = _invoke(
        monkeypatch, {}, ["tool", "trust", TOOL, "DENY", "--actor-id", ACTOR],
    )
    body = json.loads(call["body"])
    assert body == {"actor_id": ACTOR, "decision": "DENY", "scope": "exact_version"}
