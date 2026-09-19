"""Black-box acceptance coverage for the Person 2 evidence/agent/assurance routes.

Everything runs through the real HTTP API against a real disposable Git
repository, real subprocesses (a real agent process and a real pytest run) and a
real on-disk SQLite database that is reopened by a second app instance to prove
restart safety. Only the credential store is in-memory.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.tests.support_kb import make_repo, write

FILES = {
    "pyproject.toml": '[project]\nname = "d"\ndependencies = ["flask==2.0.0"]\n'
                      "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
    "requirements.txt": "flask==2.0.0\n",
    "app.py": "def add(a, b):\n    return a + b\n",
    "tests/test_app.py": "from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}
EDIT = ("import pathlib\n"
        "pathlib.Path('app.py').write_text('def add(a, b):\\n    return b + a\\n')\n"
        "pathlib.Path('requirements.txt').write_text('flask==3.0.0\\n')\nprint('agent done')\n")
KB_CAPABILITIES = {"git_checkpoints", "agent_launcher", "environment_passports",
                   "dependency_tracking", "assurance"}


def build(tmp_path):
    app = create_app(settings=Settings(database_path=tmp_path / "state" / "api.sqlite3"),
                     credential_store=InMemoryCredentialStore())
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    client.__enter__()          # run the lifespan: creates and migrates the database
    return client


def setup_change(client, repo, scopes, *, contract=None):
    created = client.post("/api/v1/changes", json={
        "title": "add feature", "intent": "exercise the KB stream", "repository_path": str(repo),
        "contract": contract or {"required_checks": ["pytest"]}})
    assert created.status_code == 201, created.text
    change = created.json()
    human = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}).json()
    agent = client.post("/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}).json()
    if scopes:
        delegation = client.post("/api/v1/delegations", json={
            "grantor_id": human["id"], "grantee_id": agent["id"], "change_id": change["id"],
            "scopes": scopes, "ttl_seconds": 3600})
        assert delegation.status_code == 201, delegation.text
    return change, agent["id"], human["id"]


def test_capabilities_report_the_kb_stream_as_available(tmp_path):
    client = build(tmp_path)
    items = {item["id"]: item for item in client.get("/api/v1/capabilities").json()["items"]}
    for name in KB_CAPABILITIES:
        assert items[name]["state"] == "AVAILABLE", name
    assert items["replay"]["state"] == "AVAILABLE"
    assert items["event_journal"]["state"] == "AVAILABLE"
    assert items["tool_registry"]["state"] == "AVAILABLE"


def test_full_flow_through_the_api_and_lifecycle_guards(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch", "agent.stop", "assurance.run"])
    base = f"/api/v1/changes/{change['id']}"

    # Nothing is proven yet, so the lifecycle guard refuses LOCALLY_VERIFIED.
    assert client.get(f"{base}/evidence").json()["baseline_captured"] is False
    assert client.get(f"{base}/assurance/facts").json()["required_assurance_passed"] is False
    active = client.post(f"{base}/transition", json={
        "target_state": "ACTIVE", "expected_revision": change["revision"]})
    assert active.status_code == 200, active.text
    early = client.post(f"{base}/transition", json={
        "target_state": "LOCALLY_VERIFIED", "expected_revision": active.json()["revision"]})
    assert early.status_code == 409
    assert "required_assurance_passed" in early.text

    # Baseline, then a real agent run that edits the repository.
    baseline = client.post(f"{base}/evidence/baseline")
    assert baseline.status_code == 201 and baseline.json()["checkpoint"]["name"] == "baseline"
    duplicate = client.post(f"{base}/evidence/baseline")
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "BASELINE_EXISTS"
    launched = client.post(f"{base}/agents/launch", json={
        "actor_id": agent, "launch": {"adapter": "generic", "executable": "python",
                                       "args": ["-c", EDIT], "timeout_seconds": 30}})
    assert launched.status_code == 201, launched.text
    run = launched.json()
    assert run["status"] == "PASSED" and run["stdout"].strip() == "agent done"
    assert run["descendant_control_available"] is False

    # Current evidence: comparison, drift, dependencies.
    current = client.post(f"{base}/evidence/current")
    assert current.status_code == 201, current.text
    snapshot = current.json()
    assert snapshot["comparison"]["added_paths"] == ["app.py", "requirements.txt"]
    flask = next(c for c in snapshot["dependencies"]["changes"] if c["package"] == "flask")
    assert (flask["old_version"], flask["new_version"]) == ("2.0.0", "3.0.0")
    overview = client.get(f"{base}/evidence").json()
    assert overview["baseline_captured"] and len(overview["checkpoints"]) == 2

    # Plan, run (real pytest), evaluate.
    plan = client.post(f"{base}/assurance/plan")
    assert plan.status_code == 201, plan.text
    plan_id = plan.json()["id"]
    assert any(c["id"] == "pytest" and c["required"] for c in plan.json()["checks"])
    assert client.get(f"{base}/assurance/plan").json()["id"] == plan_id
    ran = client.post(f"{base}/assurance/{plan_id}/run", json={"actor_id": agent})
    assert ran.status_code == 200, ran.text
    assert [r["status"] for r in ran.json()["items"] if r["check_id"] == "pytest"] == ["PASSED"]
    evaluation = client.get(f"{base}/assurance/{plan_id}/evaluation").json()
    assert evaluation["fresh"] and evaluation["required_assurance_passed"]
    facts = client.get(f"{base}/assurance/facts").json()
    assert facts["assurance_fresh"] and facts["required_assurance_passed"]

    # Verified evidence now unlocks the guarded transitions.
    verified = client.post(f"{base}/transition", json={
        "target_state": "LOCALLY_VERIFIED", "expected_revision": active.json()["revision"]})
    assert verified.status_code == 200, verified.text
    ready = client.post(f"{base}/transition", json={
        "target_state": "REVIEW_READY", "expected_revision": verified.json()["revision"]})
    assert ready.status_code == 200, ready.text

    # The passport now carries the KB evidence with no missing-evidence limitations.
    passport = client.post(f"{base}/passport").json()
    kinds = {item["kind"] for item in passport["evidence"]}
    assert {"git_checkpoint", "environment_passport", "dependency_report", "assurance_run"} <= kinds

    # Restart: a second app instance over the same database still knows everything.
    second = build(tmp_path)
    assert second.get(f"{base}/assurance/{plan_id}/evaluation").json()["required_assurance_passed"]
    assert [r["id"] for r in second.get(f"{base}/agents").json()["items"]] == [run["id"]]
    assert second.get(f"{base}/evidence").json()["baseline_captured"] is True

    # Any later edit makes the earlier proof stale.
    write(repo, "app.py", "def add(a, b):\n    return a + b + 0\n")
    stale = second.get(f"{base}/assurance/{plan_id}/evaluation").json()
    assert stale["status"] == "STALE" and not stale["required_assurance_passed"]
    assert second.get(f"{base}/assurance/facts").json()["assurance_fresh"] is False


def test_agent_and_assurance_execution_is_default_denied(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, human = setup_change(client, repo, ["agent.stop"])
    base = f"/api/v1/changes/{change['id']}"
    request = {"actor_id": agent, "launch": {"adapter": "generic", "executable": "python",
                                              "args": ["-c", "print(1)"], "timeout_seconds": 5}}
    denied = client.post(f"{base}/agents/launch", json=request)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "POLICY_DENIED"
    attach = {"actor_id": agent, "attach": {"adapter": "claude", "external_run_id": "ext"}}
    assert client.post(f"{base}/agents/attach", json=attach).status_code == 403
    client.post(f"{base}/evidence/baseline")
    plan = client.post(f"{base}/assurance/plan").json()
    assert client.post(f"{base}/assurance/{plan['id']}/run",
                       json={"actor_id": agent}).status_code == 403
    unknown_actor = client.post(f"{base}/agents/launch", json={**request, "actor_id": human})
    assert unknown_actor.status_code == 403
    assert client.get(f"{base}/agents").json()["count"] == 0     # nothing ran


def test_authority_ceiling_blocks_even_a_delegated_scope(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(
        client, repo, ["agent.launch"], contract={"authority_ceiling": ["assurance.run"]})
    response = client.post(f"/api/v1/changes/{change['id']}/agents/launch", json={
        "actor_id": agent, "launch": {"adapter": "generic", "executable": "python",
                                       "args": ["-c", "print(1)"], "timeout_seconds": 5}})
    assert response.status_code == 403
    assert response.json()["error"]["details"]["reason_code"] == "OPERATION_NOT_PERMITTED"


def test_attach_and_stop_and_adapter_listing(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.attach", "agent.stop"])
    base = f"/api/v1/changes/{change['id']}"
    attached = client.post(f"{base}/agents/attach", json={
        "actor_id": agent, "attach": {"adapter": "claude", "external_run_id": "ext-1"}})
    assert attached.status_code == 201 and attached.json()["status"] == "ATTACHED"
    stopped = client.post(f"{base}/agents/{attached.json()['id']}/stop", json={"actor_id": agent})
    assert stopped.status_code == 200 and stopped.json()["status"] == "ATTACHED"
    assert any("cannot be stopped" in text for text in stopped.json()["limitations"])
    other, other_agent, _ = setup_change(client, repo, ["agent.stop"])
    cross = client.post(f"/api/v1/changes/{other['id']}/agents/{attached.json()['id']}/stop",
                        json={"actor_id": other_agent})
    assert cross.status_code == 404 and cross.json()["error"]["code"] == "AGENT_RUN_NOT_FOUND"
    adapters = client.get("/api/v1/agents/adapters").json()
    assert {item["adapter"] for item in adapters["items"]} == {"generic", "codex", "claude"}
    assert all(item["descendant_control_available"] is False for item in adapters["items"])


def test_errors_for_missing_changes_evidence_and_plans(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["assurance.run"])
    base = f"/api/v1/changes/{change['id']}"
    ghost = "/api/v1/changes/00000000-0000-4000-8000-000000000000"
    for method, path in (("get", "/evidence"), ("post", "/evidence/baseline"),
                         ("post", "/evidence/current"), ("post", "/assurance/plan"),
                         ("get", "/assurance/plan"), ("get", "/agents")):
        response = getattr(client, method)(ghost + path)
        assert response.status_code == 404 and response.json()["error"]["code"] == "CHANGE_NOT_FOUND"
    assert client.post(f"{base}/evidence/current").json()["error"]["code"] == "BASELINE_MISSING"
    assert client.post(f"{base}/assurance/plan").json()["error"]["code"] == "EVIDENCE_MISSING"
    assert client.get(f"{base}/assurance/plan").status_code == 404
    missing = "00000000-0000-4000-8000-000000000001"
    assert client.get(f"{base}/assurance/{missing}/evaluation").status_code == 404
    assert client.post(f"{base}/assurance/{missing}/run", json={"actor_id": agent}).status_code == 404
    assert client.get(f"{base}/assurance/facts").json()["reasons"] == [
        "No assurance plan exists for this Change."]
    bad = client.post(f"{base}/agents/launch", json={"actor_id": agent, "launch": {"adapter": ""}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_declare_tool_manifest_registers_and_lists_for_the_change(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, _agent, _human = setup_change(client, repo, [])
    manifest_path = tmp_path / "server.mcp.json"
    manifest_path.write_text('{"name": "Weather MCP", "version": "1.0.0"}', encoding="utf-8")

    declared = client.post(
        f"/api/v1/changes/{change['id']}/tools/declare",
        json={"manifest_path": str(manifest_path)},
    )
    assert declared.status_code == 201, declared.text
    body = declared.json()
    assert body["name"] == "weather mcp"
    assert body["version"] == "1.0.0"
    assert body["source"].startswith("declared_manifest:")

    for_change = client.get(f"/api/v1/changes/{change['id']}/tools").json()
    assert for_change["count"] == 1
    assert for_change["items"][0]["id"] == body["id"]


def test_stale_evidence_blocks_local_verification_transition(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["assurance.run"])
    base = f"/api/v1/changes/{change['id']}"
    active = client.post(f"{base}/transition", json={
        "target_state": "ACTIVE", "expected_revision": change["revision"]}).json()
    client.post(f"{base}/evidence/baseline")
    write(repo, "app.py", "def add(a, b):\n    return b + a\n")
    client.post(f"{base}/evidence/current")
    plan = client.post(f"{base}/assurance/plan").json()
    client.post(f"{base}/assurance/{plan['id']}/run", json={"actor_id": agent})
    write(repo, "app.py", "def add(a, b):\n    return a + b + 1\n")      # moves after verification
    blocked = client.post(f"{base}/transition", json={
        "target_state": "LOCALLY_VERIFIED", "expected_revision": active["revision"]})
    assert blocked.status_code == 409
    assert "assurance_fresh" in blocked.text or "required_assurance_passed" in blocked.text
