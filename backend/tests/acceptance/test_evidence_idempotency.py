"""Replay safety for the side-effecting Person 2 routes (agent launch/attach)."""

from __future__ import annotations

import pytest

from backend.app.assurance.store import IdempotencyStore
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.tests.acceptance.test_evidence_routes import FILES, build, setup_change
from backend.tests.support_kb import make_repo

KEY = "launch-key-0001"


def launch_body(agent, code="print('once')"):
    return {"actor_id": agent, "launch": {"adapter": "generic", "executable": "python",
                                           "args": ["-c", code], "timeout_seconds": 30}}


def test_replayed_launch_returns_the_first_run_and_starts_nothing_new(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch"])
    url = f"/api/v1/changes/{change['id']}/agents/launch"
    first = client.post(url, json=launch_body(agent), headers={"Idempotency-Key": KEY})
    again = client.post(url, json=launch_body(agent), headers={"Idempotency-Key": KEY})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    assert client.get(f"/api/v1/changes/{change['id']}/agents").json()["count"] == 1

    # A different request under the same key is refused, and the key survives a restart.
    other = client.post(url, json=launch_body(agent, "print('different')"),
                        headers={"Idempotency-Key": KEY})
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    restarted = build(tmp_path)
    replay = restarted.post(url, json=launch_body(agent), headers={"Idempotency-Key": KEY})
    assert replay.json() == first.json()
    assert restarted.get(f"/api/v1/changes/{change['id']}/agents").json()["count"] == 1


def test_requests_without_a_key_are_independent(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch"])
    url = f"/api/v1/changes/{change['id']}/agents/launch"
    a = client.post(url, json=launch_body(agent)).json()
    b = client.post(url, json=launch_body(agent)).json()
    assert a["id"] != b["id"]
    assert client.get(f"/api/v1/changes/{change['id']}/agents").json()["count"] == 2


def test_attach_is_replay_safe_and_keys_are_scoped_per_change(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    one, agent_one, _ = setup_change(client, repo, ["agent.attach", "agent.launch"])
    two, agent_two, _ = setup_change(client, repo, ["agent.attach", "agent.launch"])
    body = {"attach": {"adapter": "claude", "external_run_id": "ext"}}
    first = client.post(f"/api/v1/changes/{one['id']}/agents/attach",
                        json={"actor_id": agent_one, **body}, headers={"Idempotency-Key": KEY})
    again = client.post(f"/api/v1/changes/{one['id']}/agents/attach",
                        json={"actor_id": agent_one, **body}, headers={"Idempotency-Key": KEY})
    assert first.json() == again.json()
    elsewhere = client.post(f"/api/v1/changes/{two['id']}/agents/attach",
                            json={"actor_id": agent_two, **body}, headers={"Idempotency-Key": KEY})
    assert elsewhere.status_code == 201 and elsewhere.json()["id"] != first.json()["id"]


def test_a_foreign_actor_cannot_reuse_someone_elses_idempotency_key(tmp_path):
    """A different actor's body under the same key is refused before any replay,

    never served the first actor's stored result. The mismatched-body check in
    ``IdempotencyStore.claim`` catches this before authorization would even run
    -- the same ``IDEMPOTENCY_KEY_REUSED`` path already covered for a same
    -actor differing request, since the body includes the requesting actor.
    """

    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, human = setup_change(client, repo, ["agent.launch"])
    url = f"/api/v1/changes/{change['id']}/agents/launch"
    client.post(url, json=launch_body(agent), headers={"Idempotency-Key": KEY})
    stranger = client.post(url, json=launch_body(human), headers={"Idempotency-Key": KEY})
    assert stranger.status_code == 409
    assert stranger.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert client.get(f"/api/v1/changes/{change['id']}/agents").json()["count"] == 1


def test_authority_is_re_checked_for_every_non_replayed_request(tmp_path):
    """An actor with no delegation is denied on a fresh key, not silently allowed

    because some other request happened to be cached. This is the actual
    security property replay safety must not weaken: authorization always
    runs for a request that is not an exact replay of a completed one.
    """

    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, human = setup_change(client, repo, ["agent.launch"])
    url = f"/api/v1/changes/{change['id']}/agents/launch"
    client.post(url, json=launch_body(agent), headers={"Idempotency-Key": KEY})

    stranger = client.post(url, json=launch_body(human),
                           headers={"Idempotency-Key": "launch-key-0002"})
    assert stranger.status_code == 403
    assert client.get(f"/api/v1/changes/{change['id']}/agents").json()["count"] == 1


def test_a_replayed_request_does_not_spend_a_second_delegation_use(tmp_path):
    """The bug this test guards: authorizing before the idempotency claim meant

    every retry of an already-completed request re-evaluated policy and, once
    delegation ``uses`` are consumed on allow, spent another use even though
    no new action ran. A ``use_limit=1`` delegation must survive any number of
    replays of the same request and still be usable exactly once.
    """

    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    created = client.post("/api/v1/changes", json={
        "title": "add feature", "intent": "exercise replay safety",
        "repository_path": str(repo), "contract": {"required_checks": ["pytest"]}})
    change = created.json()
    human = client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}).json()
    agent = client.post("/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}).json()
    delegation = client.post("/api/v1/delegations", json={
        "grantor_id": human["id"], "grantee_id": agent["id"], "change_id": change["id"],
        "scopes": ["agent.launch"], "ttl_seconds": 3600, "use_limit": 1}).json()
    assert delegation["use_limit"] == 1

    url = f"/api/v1/changes/{change['id']}/agents/launch"
    first = client.post(url, json=launch_body(agent["id"]), headers={"Idempotency-Key": KEY})
    assert first.status_code == 201, first.text
    for _ in range(3):
        again = client.post(url, json=launch_body(agent["id"]), headers={"Idempotency-Key": KEY})
        assert again.status_code == 201
        assert again.json() == first.json()

    # The delegation still has its one use recorded, not four.
    delegations = client.get(f"/api/v1/changes/{change['id']}/delegations").json()
    assert delegations["items"][0]["uses"] == 1

    # And that one use is still enough to authorize a genuinely new request.
    second = client.post(url, json=launch_body(agent["id"], "print('second')"),
                         headers={"Idempotency-Key": "launch-key-0003"})
    assert second.status_code == 403


def test_idempotency_store_claim_complete_release(tmp_path):
    db = Database(tmp_path / "idem.sqlite3")
    db.initialize()
    store = IdempotencyStore(db)
    assert store.claim("scope", "k1", "hash") is None
    with pytest.raises(AppError) as info:                     # still running
        store.claim("scope", "k1", "hash")
    assert info.value.code == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    store.complete("scope", "k1", '{"done": true}')
    assert store.claim("scope", "k1", "hash") == '{"done": true}'
    with pytest.raises(AppError) as info:
        store.claim("scope", "k1", "other-hash")
    assert info.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert store.claim("scope", "k2", "hash") is None
    store.release("scope", "k2")                              # a failed attempt frees its key
    assert store.claim("scope", "k2", "hash") is None
    store.release("scope", "k1")                              # completed results are never released
    assert store.claim("scope", "k1", "hash") == '{"done": true}'


def test_a_failed_launch_releases_its_key_so_it_can_be_retried(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch"])
    url = f"/api/v1/changes/{change['id']}/agents/launch"
    bad = launch_body(agent)
    bad["launch"]["executable"] = "bash"                      # rejected by the adapter allowlist
    failed = client.post(url, json=bad, headers={"Idempotency-Key": KEY})
    assert failed.status_code == 400 and failed.json()["error"]["code"] == "AGENT_EXECUTABLE_NOT_ALLOWED"
    retry = client.post(url, json=bad, headers={"Idempotency-Key": KEY})
    assert retry.json()["error"]["code"] == "AGENT_EXECUTABLE_NOT_ALLOWED"   # not "in progress"
    ok = client.post(url, json=launch_body(agent), headers={"Idempotency-Key": "launch-key-0002"})
    assert ok.status_code == 201
