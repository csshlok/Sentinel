from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def committed_repository(tmp_path: Path) -> Path:
    repo = tmp_path / "integration repository"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "Integration Test")
    git(repo, "config", "user.email", "integration@example.com")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    git(repo, "add", "app.py")
    git(repo, "commit", "-m", "baseline")
    return repo


def test_real_create_refresh_verify_flow(tmp_path: Path) -> None:
    repo = committed_repository(tmp_path)
    app = create_app(
        settings=Settings(database_path=tmp_path / "change-assurance.sqlite3")
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/changes",
            json={
                "title": "Update application value",
                "intent": "Change VALUE and verify the new result",
                "repository_path": str(repo),
            },
        )
        assert created.status_code == 201
        change_id = created.json()["id"]
        assert created.json()["repository_path"] == str(repo.resolve())
        assert created.json()["review_state"] == "NO_CHANGES"

        (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        refreshed = client.post(f"/api/v1/changes/{change_id}/refresh")
        assert refreshed.status_code == 200
        payload = refreshed.json()
        assert payload["review_state"] == "MISSING_EVIDENCE"
        assert payload["git_summary"]["total_additions"] == 1
        assert payload["git_summary"]["total_deletions"] == 1
        assert payload["git_summary"]["files"][0]["category"] == "SOURCE"

        verified = client.post(
            f"/api/v1/changes/{change_id}/verify",
            json={
                "executable": "python",
                "args": [
                    "-c",
                    "import app; assert app.VALUE == 2",
                ],
                "timeout_seconds": 30,
            },
        )
        assert verified.status_code == 200
        verified_payload = verified.json()
        assert verified_payload["verification"]["status"] == "PASSED"
        assert verified_payload["review_state"] == "READY_FOR_HUMAN_REVIEW"

        refreshed_again = client.post(f"/api/v1/changes/{change_id}/refresh")
        assert refreshed_again.status_code == 200
        assert refreshed_again.json()["verification"] is None
        assert refreshed_again.json()["review_state"] == "MISSING_EVIDENCE"


def test_repository_validation_error_uses_stable_envelope(tmp_path: Path) -> None:
    non_repo = tmp_path / "plain directory"
    non_repo.mkdir()
    app = create_app(settings=Settings(database_path=tmp_path / "errors.sqlite3"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/repositories/validate",
            json={"path": str(non_repo)},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_A_GIT_REPOSITORY"
    assert str(non_repo) not in response.text


def test_verification_failure_timeout_and_policy_errors_through_api(
    tmp_path: Path,
) -> None:
    repo = committed_repository(tmp_path)
    (repo / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    app = create_app(
        settings=Settings(
            database_path=tmp_path / "verification.sqlite3",
            verification_output_limit_bytes=100,
        )
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/changes",
            json={
                "title": "Verification outcomes",
                "intent": "Exercise real verification failure boundaries",
                "repository_path": str(repo),
            },
        ).json()
        change_id = created["id"]
        client.post(f"/api/v1/changes/{change_id}/refresh")

        failed = client.post(
            f"/api/v1/changes/{change_id}/verify",
            json={
                "executable": "python",
                "args": ["-c", "import sys; print('x' * 500); sys.exit(3)"],
                "timeout_seconds": 30,
            },
        )
        assert failed.status_code == 200
        failed_payload = failed.json()
        assert failed_payload["verification"]["status"] == "FAILED"
        assert failed_payload["verification"]["exit_code"] == 3
        assert failed_payload["verification"]["output_truncated"] is True
        assert len(failed_payload["verification"]["stdout"].encode("utf-8")) <= 100
        assert failed_payload["review_state"] == "FAILED_VERIFICATION"

        timed_out = client.post(
            f"/api/v1/changes/{change_id}/verify",
            json={
                "executable": "python",
                "args": ["-c", "import time; time.sleep(5)"],
                "timeout_seconds": 1,
            },
        )
        assert timed_out.status_code == 200
        assert timed_out.json()["verification"]["status"] == "TIMED_OUT"
        assert timed_out.json()["review_state"] == "FAILED_VERIFICATION"

        denied = client.post(
            f"/api/v1/changes/{change_id}/verify",
            json={"executable": "powershell", "args": [], "timeout_seconds": 30},
        )
        assert denied.status_code == 400
        assert denied.json()["error"]["code"] == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"
