"""T0: acceptance tests for the Tool Registry routes (`/tools`,
`/tools/{id}`, `/tools/{id}/trust`, `/changes/{id}/tools`).

No launcher integration exists yet (that is T1's `AgentLauncherPort`
enforcement point); these tests seed the registry directly through
`app.state.runtime_services.tools` -- the same real `ToolRegistryService`
instance the routes use -- then verify every result through the real HTTP
API, matching the existing `_seed_checkpoint` pattern in
`test_runtime_routes.py` for evidence not yet wired through its own routes.
"""

from __future__ import annotations

from uuid import uuid4

from backend.tests.acceptance.test_runtime_routes import _build_client, _init_repo
from backend.tests.providers.fakes import FakeHttpTransport


def test_unknown_tool_auto_registers_as_observed_not_blocked(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"unknown-tool-bytes")

    with client:
        manifest = app.state.runtime_services.tools.resolve_or_register(
            str(exe), source="launcher_executable"
        )
        assert manifest.trust_state.value == "OBSERVED"

        listed = client.get("/api/v1/tools")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert listed.json()["items"][0]["id"] == str(manifest.id)

        shown = client.get(f"/api/v1/tools/{manifest.id}")
        assert shown.status_code == 200
        assert shown.json()["trust_state"] == "OBSERVED"

        missing = client.get(f"/api/v1/tools/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TOOL_NOT_FOUND"


def test_approve_then_deny_trust_decisions_through_the_real_api(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    exe = tmp_path / "claude.exe"
    exe.write_bytes(b"claude-bytes")

    with client:
        manifest = app.state.runtime_services.tools.resolve_or_register(
            str(exe), source="launcher_executable"
        )
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "Tool trust", "intent": "Exercise POST /tools/{id}/trust",
                  "repository_path": repo_path},
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "HUMAN", "display_name": "Reviewer"}
        ).json()["id"]

        approved = client.post(
            f"/api/v1/tools/{manifest.id}/trust",
            json={"actor_id": actor_id, "decision": "APPROVE", "scope": "exact_version",
                  "reason": "Reviewed manually", "change_id": change_id},
        )
        assert approved.status_code == 200
        assert approved.json()["decision"] == "APPROVE"

        shown = client.get(f"/api/v1/tools/{manifest.id}")
        assert shown.json()["trust_state"] == "APPROVED"

        denied = client.post(
            f"/api/v1/tools/{manifest.id}/trust",
            json={"actor_id": actor_id, "decision": "DENY", "scope": "exact_version",
                  "reason": "Reconsidered", "change_id": change_id},
        )
        assert denied.status_code == 200
        assert client.get(f"/api/v1/tools/{manifest.id}").json()["trust_state"] == "DENIED"

        events = client.get(f"/api/v1/changes/{change_id}/events").json()["items"]
        types = [e["event_type"] for e in events]
        assert types.count("tool.trust.decided") == 2


def test_changes_tools_route_lists_only_observed_tools_for_that_change(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))
    registry = app.state.runtime_services.tools

    tool_a_path = tmp_path / "a.exe"
    tool_a_path.write_bytes(b"a")
    tool_b_path = tmp_path / "b.exe"
    tool_b_path.write_bytes(b"b")

    with client:
        tool_a = registry.resolve_or_register(str(tool_a_path), source="launcher_executable")
        tool_b = registry.resolve_or_register(str(tool_b_path), source="launcher_executable")
        change_a = client.post(
            "/api/v1/changes",
            json={"title": "A", "intent": "Owns tool A", "repository_path": repo_path},
        ).json()["id"]
        change_b = client.post(
            "/api/v1/changes",
            json={"title": "B", "intent": "Owns tool B", "repository_path": repo_path},
        ).json()["id"]

        from uuid import UUID
        registry.record_observation(tool_a.id, UUID(change_a), None, [], "launch")
        registry.record_observation(tool_b.id, UUID(change_b), None, [], "launch")

        for_a = client.get(f"/api/v1/changes/{change_a}/tools")
        assert for_a.status_code == 200
        assert [item["id"] for item in for_a.json()["items"]] == [str(tool_a.id)]

        for_b = client.get(f"/api/v1/changes/{change_b}/tools")
        assert [item["id"] for item in for_b.json()["items"]] == [str(tool_b.id)]
