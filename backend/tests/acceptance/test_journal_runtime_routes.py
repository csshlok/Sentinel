"""J2: real-boundary tests for [AC]-owned (+ [SD] policy.decision.denied,
change_repository.py) Event/Effect Journal emission.

Drives the same real identity/credential/provider/outcome/recovery/passport
flow as `test_runtime_routes.py`, through the real HTTP API with a real
SQLite database and a real disposable Git repository, then reads
`journal_events` back and asserts the resulting chain is well-formed and
correctly ordered. Also contains this plan's C.5 "one test that must exist
before anything else ships": a canary-secret scan proving a real credential
value never reaches `journal_events.payload_json`.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.database import Database
from backend.app.core.journal import compute_event_hash, row_to_event
from backend.tests.acceptance.test_runtime_routes import (
    _build_client,
    _init_repo,
    _seed_checkpoint,
)
from backend.tests.providers.fakes import FakeHttpTransport, json_response


def _events(database: Database, change_id: str) -> list:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_events WHERE change_id = ? ORDER BY seq",
            (change_id,),
        ).fetchall()
    return [row_to_event(row) for row in rows]


def _all_payload_json(database: Database) -> str:
    with database.connection() as connection:
        rows = connection.execute("SELECT payload_json FROM journal_events").fetchall()
    return "\n".join(row["payload_json"] for row in rows)


def _assert_chain_valid(events: list) -> None:
    prev_hash = None
    for index, event in enumerate(events):
        assert event.seq == index + 1
        assert event.prev_event_hash == prev_hash
        expected = compute_event_hash(
            prev_event_hash=prev_hash, seq=event.seq, change_id=event.change_id,
            event_type=event.event_type.value, actor_id=event.actor_id,
            subject_type=event.subject_type, subject_id=event.subject_id,
            payload=event.payload, occurred_at=event.occurred_at,
            schema_version=event.schema_version,
        )
        assert expected == event.event_hash
        prev_hash = event.event_hash


def test_full_ac_flow_produces_a_correctly_chained_and_ordered_journal(tmp_path) -> None:
    repo_path, baseline_sha, current_sha = _init_repo(tmp_path)
    secret_token = "gh-super-secret-canary-token-xyz"
    transport = FakeHttpTransport(
        [
            json_response(201, {
                "number": 7, "html_url": "https://github.com/acme/widgets/pull/7",
                "head": {"sha": current_sha}, "draft": True,
            }),
            json_response(200, {
                "check_runs": [
                    {"name": "build", "status": "completed", "conclusion": "success",
                     "head_sha": current_sha}
                ]
            }),
        ]
    )
    app, client = _build_client(tmp_path, repo_path, current_sha, transport)

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "Journal flow", "intent": "Exercise [AC] journal emission",
                  "repository_path": repo_path},
        ).json()["id"]

        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Journal Agent"}
        ).json()["id"]

        delegation = client.post(
            "/api/v1/delegations",
            json={"grantor_id": str(uuid4()), "grantee_id": actor_id, "change_id": change_id,
                  "scopes": ["github.pr.create", "recovery.execute", "github.repo.read"],
                  "ttl_seconds": 3600},
        )
        assert delegation.status_code == 201

        client.post("/api/v1/providers/github/connect", json={"token": secret_token})

        pr_grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create"], "ttl_seconds": 900},
        ).json()["id"]

        pr_response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={"actor_id": actor_id, "grant_id": pr_grant_id, "base_branch": "main",
                  "head_branch": "feature", "title": "Test PR", "idempotency_key": "pr-1"},
        )
        assert pr_response.status_code == 200

        read_grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.repo.read"], "ttl_seconds": 900},
        ).json()["id"]

        # GitHubOutcomeTracker needs `change.git_summary` populated before it
        # will compare CI check runs against a real head_sha.
        refreshed = client.post(f"/api/v1/changes/{change_id}/refresh")
        assert refreshed.status_code == 200

        outcomes = client.post(
            f"/api/v1/changes/{change_id}/outcomes/refresh",
            json={"grant_id": read_grant_id, "required_check_names": ["build"]},
        )
        assert outcomes.status_code == 200

        _seed_checkpoint(app.state.database, change_id, repo_path, baseline_sha)
        plan_id = client.post(f"/api/v1/changes/{change_id}/recovery/preview").json()["id"]
        executed = client.post(
            f"/api/v1/changes/{change_id}/recovery/{plan_id}/execute",
            json={"actor_id": actor_id, "approval_token": "approved-by-test"},
        )
        assert executed.json()["status"] == "RECOVERED"

        passport = client.post(f"/api/v1/changes/{change_id}/passport")
        assert passport.status_code == 201

        revoke_response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants/{pr_grant_id}/revoke"
        )
        assert revoke_response.status_code == 200

        # -- canary secret: the token must never reach the journal -----------
        payload_blob = _all_payload_json(app.state.database)
        assert secret_token not in payload_blob

        events = _events(app.state.database, change_id)
        _assert_chain_valid(events)
        types = [e.event_type.value for e in events]

        # CHANGE_CREATED is emitted before this test's flow even starts
        # issuing delegations, so it is seq 1 by construction.
        assert types[0] == "change.created"
        assert "delegation.issued" in types
        assert types.count("credential.grant.issued") == 2
        assert "credential.secret.resolved" in types
        assert "provider.pull_request.created" in types
        assert "provider.ci_refreshed" in types
        assert "outcome.recorded" in types
        assert "recovery.plan.created" in types
        assert "recovery.action.completed" in types
        assert "recovery.plan.completed" in types
        assert "passport.built" in types
        assert "credential.grant.revoked" in types

        # Ordering sanity: delegation precedes the PR it authorizes, and the
        # PR-create event precedes the CI refresh that reads its outcome.
        assert types.index("delegation.issued") < types.index("provider.pull_request.created")
        assert types.index("provider.pull_request.created") < types.index("provider.ci_refreshed")
        assert types.index("recovery.plan.created") < types.index("recovery.plan.completed")

        # The recovery.action.completed effect claims restoration_class="exact".
        with app.state.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM journal_effects WHERE resource_type = 'recovery_action'"
            ).fetchone()
        assert row["restoration_class"] == "exact"
        assert row["before_digest"] != row["produced_digest"]


def test_policy_denial_is_journaled(tmp_path) -> None:
    """Threat model finding #1: grant issuance itself is now policy-gated,

    so an actor with no delegation is denied at that step -- and that
    denial is journaled exactly like every other policy.decision.denied
    event, closing the vulnerability one step earlier than before (a
    denied create_pull_request call downstream is no longer reachable
    without a delegation, since a grant can't exist without one either).
    """

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "No authority", "intent": "Exercise policy.decision.denied",
                  "repository_path": repo_path},
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Unauthorized"}
        ).json()["id"]
        client.post("/api/v1/providers/github/connect", json={"token": "token"})

        response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create"], "ttl_seconds": 900},
        )
        assert response.status_code == 403

    events = _events(app.state.database, change_id)
    denied = [e for e in events if e.event_type.value == "policy.decision.denied"]
    assert len(denied) == 1
    assert denied[0].payload["operation"] == "github.pr.create"
    assert denied[0].actor_id is not None and str(denied[0].actor_id) == actor_id


def test_change_deletion_journals_and_then_cascades_the_event_away(tmp_path) -> None:
    """change.deleted is emitted immediately before the row delete, but the
    ON DELETE CASCADE on journal_events.change_id removes it along with
    every other event for that Change -- proving the plan's own documented
    limitation (no cross-Change audit log survives Change deletion)."""

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "Deletable", "intent": "Exercise change.deleted",
                  "repository_path": repo_path},
        ).json()["id"]
        assert len(_events(app.state.database, change_id)) == 1

        deleted = client.delete(f"/api/v1/changes/{change_id}")
        assert deleted.status_code == 204

    assert _events(app.state.database, change_id) == []
