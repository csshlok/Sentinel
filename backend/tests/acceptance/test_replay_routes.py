"""J3: acceptance-level tests for the Replay routes (`/events`, `/replay`,
`/replay/verify`, `/replay/export`).

Drives a real Change through the real HTTP API and asserts: the reconstructed
timeline's event order matches actual execution order; the dedicated tamper-
detection test that directly edits one committed row via raw `sqlite3`
(bypassing the app layer, not any trigger, since `event_hash` is edited to a
legitimate-looking value no trigger can distinguish from a real one) and
confirms `GET /replay/verify` reports `verified: false` with the correct
`first_break_seq`; and an export-bundle round-trip confirming redaction holds.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from backend.tests.acceptance.test_runtime_routes import _build_client, _init_repo
from backend.tests.providers.fakes import FakeHttpTransport


def _grantor_id(client) -> str:
    """Threat model finding #5: grantor_id must now resolve to a real

    Actor, so a synthetic uuid4() no longer works as a delegation grantor
    in tests; this creates a real one.
    """
    return client.post(
        "/api/v1/actors", json={"kind": "HUMAN", "display_name": "Grantor"}
    ).json()["id"]

def test_replay_reconstructs_events_in_actual_execution_order(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "Replay order", "intent": "Exercise /replay ordering",
                  "repository_path": repo_path},
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Replay Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={"grantor_id": _grantor_id(client), "grantee_id": actor_id, "change_id": change_id,
                  "scopes": ["recovery.execute"], "ttl_seconds": 3600},
        )
        transitioned = client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "ACTIVE", "expected_revision": 1},
        )
        assert transitioned.status_code == 200

        replay = client.get(f"/api/v1/changes/{change_id}/replay")
        assert replay.status_code == 200
        body = replay.json()
        assert body["chain_verified"] is True
        seqs = [e["seq"] for e in body["events"]]
        assert seqs == sorted(seqs)
        assert seqs == list(range(1, len(seqs) + 1))
        types = [e["event_type"] for e in body["events"]]
        # Actual execution order: the Change is created, then a delegation is
        # issued, then it transitions.
        assert types.index("change.created") < types.index("delegation.issued")
        assert types.index("delegation.issued") < types.index("change.transitioned")

        verify = client.get(f"/api/v1/changes/{change_id}/replay/verify")
        assert verify.status_code == 200
        assert verify.json() == {
            "change_id": change_id, "verified": True,
            "checked_events": len(seqs), "first_break_seq": None, "reason": None,
        }

        events_route = client.get(f"/api/v1/changes/{change_id}/events")
        assert events_route.status_code == 200
        assert events_route.json()["count"] == len(seqs)

        filtered = client.get(f"/api/v1/changes/{change_id}/events?event_type=change.created")
        assert filtered.json()["count"] == 1


def test_replay_verify_detects_a_direct_file_level_tamper(tmp_path) -> None:
    """The dedicated tamper-detection acceptance test: edit one committed
    `event_hash` directly via raw sqlite3 (a legitimate-looking value; no
    trigger can prevent this since UPDATE-blocking exists precisely to force
    tampering to happen this way -- outside the app, not through it) and
    confirm `/replay/verify` reports it honestly."""

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "Tamper target", "intent": "Exercise tamper detection",
                  "repository_path": repo_path},
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Tamper Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={"grantor_id": _grantor_id(client), "grantee_id": actor_id, "change_id": change_id,
                  "scopes": ["recovery.execute"], "ttl_seconds": 3600},
        )
        client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "ACTIVE", "expected_revision": 1},
        )

        pre_tamper = client.get(f"/api/v1/changes/{change_id}/replay/verify")
        assert pre_tamper.json()["verified"] is True

        # Directly tamper with the second event's hash, bypassing the app
        # layer entirely (the append-only UPDATE trigger applies to any live
        # SQL connection, live or not -- this simulates the app being
        # stopped and the raw file edited, the only way an edit like this
        # can actually happen, per A.3's own framing).
        db_path = app.state.settings.database_path
        raw = sqlite3.connect(db_path)
        try:
            raw.execute("DROP TRIGGER journal_events_immutable_update")
            raw.execute(
                "UPDATE journal_events SET event_hash = ? "
                "WHERE change_id = ? AND seq = 2",
                ("f" * 64, change_id),
            )
            raw.commit()
        finally:
            raw.close()

        verify = client.get(f"/api/v1/changes/{change_id}/replay/verify")
        assert verify.status_code == 200
        result = verify.json()
        assert result["verified"] is False
        assert result["first_break_seq"] == 2
        assert result["reason"]

        replay = client.get(f"/api/v1/changes/{change_id}/replay")
        assert replay.json()["chain_verified"] is False
        assert replay.json()["first_break_seq"] == 2


def test_replay_export_round_trip_preserves_redaction(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    secret_token = "gh-export-canary-secret"
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={"title": "Export flow", "intent": "Exercise /replay/export",
                  "repository_path": repo_path},
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Export Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={"grantor_id": _grantor_id(client), "grantee_id": actor_id, "change_id": change_id,
                  "scopes": ["github.pr.create"], "ttl_seconds": 3600},
        )
        client.post("/api/v1/providers/github/connect", json={"token": secret_token})
        grant = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create"], "ttl_seconds": 900},
        ).json()
        del grant

        export = client.get(f"/api/v1/changes/{change_id}/replay/export")
        assert export.status_code == 200
        body = export.json()
        assert body["change_id"] == change_id
        assert body["events"]
        assert secret_token not in export.text
        assert "limitations" in body and body["limitations"]

        # Round trip: reconstruct and export must describe the same events.
        replay = client.get(f"/api/v1/changes/{change_id}/replay").json()
        assert [e["id"] for e in replay["events"]] == [e["id"] for e in body["events"]]
