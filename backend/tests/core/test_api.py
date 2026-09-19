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
    return TestClient(app)


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

        verified = client.post(
            f"/api/v1/changes/{change_id}/verify",
            json={"executable": "pytest", "args": ["-q"], "timeout_seconds": 30},
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
