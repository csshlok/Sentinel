"""Plan section 8 read routes and replay safety for every Person 2 mutation."""

from __future__ import annotations

from backend.tests.acceptance.test_evidence_routes import EDIT, FILES, build, setup_change
from backend.tests.support_kb import make_repo, write

GHOST = "00000000-0000-4000-8000-000000000000"


def launch_edit(client, base, agent):
    return client.post(f"{base}/agents/launch", json={
        "actor_id": agent, "launch": {"adapter": "generic", "executable": "python",
                                       "args": ["-c", EDIT], "timeout_seconds": 30}})


def test_git_environment_and_dependency_reads(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch"])
    base = f"/api/v1/changes/{change['id']}"

    # Nothing captured yet: empty reads, honest 404s, no freshness claim.
    assert client.get(f"{base}/git/checkpoints").json() == {"items": [], "count": 0}
    assert client.get(f"{base}/environment").json() == {
        "passport": None, "baseline_id": None, "drift": None}
    missing = client.get(f"{base}/dependencies")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "DEPENDENCY_REPORT_NOT_FOUND"
    assert client.get(f"{base}/evidence").json()["latest_checkpoint_fresh"] is None

    first = client.post(f"{base}/evidence/baseline").json()
    assert client.get(f"{base}/evidence").json()["latest_checkpoint_fresh"] is True
    assert client.get(f"{base}/environment").json()["drift"] is None      # only one passport yet
    launch_edit(client, base, agent)
    assert client.get(f"{base}/evidence").json()["latest_checkpoint_fresh"] is False   # repo moved
    second = client.post(f"{base}/evidence/current").json()
    assert client.get(f"{base}/evidence").json()["latest_checkpoint_fresh"] is True

    listed = client.get(f"{base}/git/checkpoints").json()
    assert listed["count"] == 2
    assert [c["name"] for c in listed["items"]] == ["baseline", "current"]
    compared = client.get(f"{base}/git/compare", params={
        "baseline_id": first["checkpoint"]["id"], "current_id": second["checkpoint"]["id"]})
    assert compared.status_code == 200
    assert compared.json()["added_paths"] == ["app.py", "requirements.txt"]

    environment = client.get(f"{base}/environment").json()
    assert environment["baseline_id"] == first["environment"]["id"]
    assert environment["passport"]["id"] == second["environment"]["id"]
    assert environment["drift"]["causal_attribution_available"] is False
    dependencies = client.get(f"{base}/dependencies").json()
    assert any(c["package"] == "flask" for c in dependencies["changes"])

    write(repo, "extra.txt", "moved after the last checkpoint")
    assert client.get(f"{base}/evidence").json()["latest_checkpoint_fresh"] is False


def test_compare_is_scoped_to_the_change_and_validates_input(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    one, _, _ = setup_change(client, repo, [])
    two, _, _ = setup_change(client, repo, [])
    snap = client.post(f"/api/v1/changes/{one['id']}/evidence/baseline").json()["checkpoint"]["id"]
    foreign = client.get(f"/api/v1/changes/{two['id']}/git/compare",
                         params={"baseline_id": snap, "current_id": snap})
    assert foreign.status_code == 404 and foreign.json()["error"]["code"] == "CHECKPOINT_NOT_FOUND"
    unknown = client.get(f"/api/v1/changes/{one['id']}/git/compare",
                         params={"baseline_id": snap, "current_id": GHOST})
    assert unknown.status_code == 404
    assert client.get(f"/api/v1/changes/{one['id']}/git/compare",
                      params={"baseline_id": "nope", "current_id": snap}).status_code == 422
    for path in ("/git/checkpoints", "/environment", "/dependencies"):
        response = client.get(f"/api/v1/changes/{GHOST}{path}")
        assert response.status_code == 404 and response.json()["error"]["code"] == "CHANGE_NOT_FOUND"


def test_every_mutation_replays_safely_with_an_idempotency_key(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch", "assurance.run"])
    base = f"/api/v1/changes/{change['id']}"

    baseline = client.post(f"{base}/evidence/baseline", headers={"Idempotency-Key": "baseline-key-1"})
    replay = client.post(f"{base}/evidence/baseline", headers={"Idempotency-Key": "baseline-key-1"})
    assert baseline.status_code == replay.status_code == 201 and baseline.json() == replay.json()
    # Without the key a second baseline is still refused, never silently redone.
    assert client.post(f"{base}/evidence/baseline").status_code == 409

    launch_edit(client, base, agent)
    current = client.post(f"{base}/evidence/current", headers={"Idempotency-Key": "current-key-01"})
    again = client.post(f"{base}/evidence/current", headers={"Idempotency-Key": "current-key-01"})
    assert current.json() == again.json()
    assert client.get(f"{base}/git/checkpoints").json()["count"] == 2      # the replay captured nothing

    plan = client.post(f"{base}/assurance/plan", headers={"Idempotency-Key": "plan-key-0001"})
    plan_again = client.post(f"{base}/assurance/plan", headers={"Idempotency-Key": "plan-key-0001"})
    assert plan.json() == plan_again.json()

    body = {"actor_id": agent}
    ran = client.post(f"{base}/assurance/{plan.json()['id']}/run", json=body,
                      headers={"Idempotency-Key": "run-key-00001"})
    ran_again = client.post(f"{base}/assurance/{plan.json()['id']}/run", json=body,
                            headers={"Idempotency-Key": "run-key-00001"})
    assert ran.status_code == 200 and ran.json() == ran_again.json()
    conflict = client.post(f"{base}/assurance/{plan.json()['id']}/run",
                           json={**body, "output_limit_bytes": 10},
                           headers={"Idempotency-Key": "run-key-00001"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    # Replays did not execute the checks again: only one set of runs exists.
    evaluation = client.get(f"{base}/assurance/{plan.json()['id']}/evaluation").json()
    assert evaluation["results"][0]["status"] == "PASSED"
