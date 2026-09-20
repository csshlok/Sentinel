from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.contracts.models import (
    ChangedPath,
    ChangedPathStatus,
    GitSummary,
    PathCategory,
    RepositoryInfo,
    VerificationResult,
    VerificationStatus,
)
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.tests.core.fakes import FakeGitInspection, FakeVerification


def build_client(tmp_path) -> TestClient:
    now = datetime.now(UTC)
    git = FakeGitInspection(
        RepositoryInfo(root="C:\\canonical repo", branch="main", head_sha="a" * 40),
        GitSummary(
            repository_root="C:\\canonical repo",
            branch="main",
            head_sha="a" * 40,
            is_clean=False,
            files=[
                ChangedPath(
                    path="src/app.py",
                    status=ChangedPathStatus.MODIFIED,
                    staged=False,
                    unstaged=True,
                    additions=1,
                    deletions=0,
                    category=PathCategory.SOURCE,
                )
            ],
            total_additions=1,
            total_deletions=0,
            patch="diff --git a/src/app.py b/src/app.py",
            refreshed_at=now,
        ),
    )
    verification = FakeVerification(
        VerificationResult(
            executable="pytest",
            args=["-q"],
            status=VerificationStatus.PASSED,
            exit_code=0,
            duration_ms=12,
            stdout="1 passed",
            stderr="",
            started_at=now,
            completed_at=now,
        )
    )
    app = create_app(
        settings=Settings(database_path=tmp_path / "changes.sqlite3"),
        git_inspection=git,
        verification=verification,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    return client


def test_change_refresh_and_verify_flow(tmp_path) -> None:
    with build_client(tmp_path) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "api_version": "1"}

        created = client.post(
            "/api/v1/changes",
            json={
                "title": "Review auth",
                "intent": "Check the token update",
                "repository_path": "C:\\requested repo",
            },
        )
        assert created.status_code == 201
        change_id = created.json()["id"]
        assert created.json()["repository_path"] == "C:\\canonical repo"
        assert created.json()["review_state"] == "NO_CHANGES"

        refreshed = client.post(f"/api/v1/changes/{change_id}/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["review_state"] == "MISSING_EVIDENCE"

        actor_id = client.post(
            "/api/v1/actors", json={"kind": "HUMAN", "display_name": "Owner"}
        ).json()["id"]
        grantor_id = client.post(
            "/api/v1/actors", json={"kind": "HUMAN", "display_name": "Grantor"}
        ).json()["id"]
        client.post("/api/v1/delegations", json={
            "grantor_id": grantor_id, "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["change.legacy_verify"], "ttl_seconds": 3600,
        })

        verified = client.post(
            f"/api/v1/changes/{change_id}/verify",
            json={
                "actor_id": actor_id,
                "verification": {"executable": "pytest", "args": ["-q"], "timeout_seconds": 30},
            },
        )
        assert verified.status_code == 200
        assert verified.json()["review_state"] == "READY_FOR_HUMAN_REVIEW"

        refreshed_again = client.post(f"/api/v1/changes/{change_id}/refresh")
        assert refreshed_again.status_code == 200
        assert refreshed_again.json()["verification"] is None
        assert refreshed_again.json()["review_state"] == "MISSING_EVIDENCE"

        listed = client.get("/api/v1/changes")
        assert listed.status_code == 200
        assert listed.json()["count"] == 1


def test_missing_change_uses_stable_error_envelope(tmp_path) -> None:
    with build_client(tmp_path) as client:
        response = client.get(
            "/api/v1/changes/00000000-0000-0000-0000-000000000000"
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHANGE_NOT_FOUND"


def test_validation_error_does_not_echo_input(tmp_path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/v1/changes",
            json={"title": "", "intent": "valid", "repository_path": "C:\\secret"},
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "C:\\secret" not in response.text


def test_backend_identity_is_stable_per_process_and_unauthenticated(tmp_path) -> None:
    """HANDOFF.md item SD.3: the desktop app needs a stronger identity signal
    than health + an authenticated call, to detect a stale reused backend
    process after a force-kill-and-relaunch."""

    with build_client(tmp_path) as client:
        first = client.get("/api/v1/system/backend-identity")
        second = client.get("/api/v1/system/backend-identity")
    assert first.status_code == 200
    body = first.json()
    assert body["service_name"] == "change-assurance-runtime-backend"
    assert body["api_version"] == "1"
    # Stable within one process lifetime...
    assert second.json()["instance_id"] == body["instance_id"]
    # ...but distinct from a different process (a fresh app == a fresh instance_id).
    with build_client(tmp_path.parent / (tmp_path.name + "-2")) as other_client:
        other = other_client.get("/api/v1/system/backend-identity")
    assert other.json()["instance_id"] != body["instance_id"]


def test_list_changes_reports_total_distinct_from_page_count(tmp_path) -> None:
    """HANDOFF.md item SD.6: `count` was only ever the page length, so the UI
    could not show "N of M" across pages."""

    with build_client(tmp_path) as client:
        for i in range(3):
            client.post("/api/v1/changes", json={
                "title": f"c{i}", "intent": "i", "repository_path": "C:\\requested repo"})
        page = client.get("/api/v1/changes?limit=2&offset=0")
        assert page.status_code == 200
        assert page.json()["count"] == 2
        assert page.json()["total"] == 3
        last_page = client.get("/api/v1/changes?limit=2&offset=2")
        assert last_page.json()["count"] == 1
        assert last_page.json()["total"] == 3


def test_change_view_exposes_allowed_next_states(tmp_path) -> None:
    """HANDOFF.md item SD.5: the UI should only offer legal state moves."""

    with build_client(tmp_path) as client:
        created = client.post("/api/v1/changes", json={
            "title": "t", "intent": "i", "repository_path": "C:\\requested repo"})
        assert set(created.json()["allowed_next_states"]) == {"ACTIVE", "CANCELLED"}
        cancelled = client.post(f"/api/v1/changes/{created.json()['id']}/cancel", json={
            "expected_revision": created.json()["revision"]})
        assert cancelled.json()["allowed_next_states"] == []


def test_list_actors(tmp_path) -> None:
    """HANDOFF.md item AC.1: an Authority screen creating delegations needs a
    real actor list, not only create-by-id and get-by-id."""

    with build_client(tmp_path) as client:
        empty = client.get("/api/v1/actors")
        assert empty.status_code == 200
        assert empty.json() == {"items": [], "count": 0, "total": 0}
        for name in ("Alice", "Bob", "Carol"):
            client.post("/api/v1/actors", json={"kind": "HUMAN", "display_name": name})
        listed = client.get("/api/v1/actors?limit=2&offset=0")
        assert listed.json()["count"] == 2
        assert listed.json()["total"] == 3
        names = {item["display_name"] for item in listed.json()["items"]}
        assert names <= {"Alice", "Bob", "Carol"}
