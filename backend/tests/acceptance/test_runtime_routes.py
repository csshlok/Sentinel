"""[SD] black-box acceptance coverage for the Gate 3 AC-domain routes.

Exercises identity, credential brokering, GitHub provider operations,
outcomes, recovery, and Change Passport end to end through the real HTTP
API, using only contract-conforming fakes for the Git adapter and the
GitHub HTTP transport (never a real network call or a real credential).
This is the composition `[SD]` owns per `AGENT_COORDINATION.md`; it is not
a substitute for `[AC]`'s owner-local unit/contract tests in
`backend/tests/{identity,policy,credentials,providers,outcomes,recovery,
passport}/`, which already cover each adapter's own decision tables.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from backend.app.contracts.models import GitCheckpoint, GitSummary, RepositoryInfo
from backend.app.core.config import Settings
from backend.app.core.database import Database
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.main import create_app
from backend.tests.core.fakes import FakeGitInspection
from backend.tests.providers.fakes import FakeHttpTransport, json_response


def _run(repo, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, shell=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_repo(tmp_path) -> tuple[str, str, str]:
    """One baseline commit, then one edit commit, with a GitHub `origin` remote."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    _run(repo, "add", "file.txt")
    _run(repo, "commit", "-m", "baseline")
    baseline_sha = _run(repo, "rev-parse", "HEAD")

    (repo / "file.txt").write_text("edited\n", encoding="utf-8")
    _run(repo, "commit", "-am", "edit")
    current_sha = _run(repo, "rev-parse", "HEAD")
    return str(repo), baseline_sha, current_sha


def _seed_checkpoint(
    database: Database, change_id: str, repo_path: str, head_sha: str
) -> None:
    now = datetime.now(UTC)
    checkpoint = GitCheckpoint(
        id=uuid4(),
        change_id=UUID(change_id),
        name="baseline",
        repository_root=repo_path,
        branch="main",
        head_sha=head_sha,
        status_digest=hashlib.sha256(b"baseline").hexdigest(),
        summary=GitSummary(
            repository_root=repo_path,
            branch="main",
            head_sha=head_sha,
            is_clean=True,
            total_additions=0,
            total_deletions=0,
            patch="",
            refreshed_at=now,
        ),
        evidence_revision=1,
        captured_at=now,
    )
    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO git_checkpoints (
                id, change_id, name, head_sha, evidence_revision, payload_json, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(checkpoint.id),
                change_id,
                checkpoint.name,
                checkpoint.head_sha,
                checkpoint.evidence_revision,
                checkpoint.model_dump_json(),
                checkpoint.captured_at.isoformat(),
            ),
        )


def _build_client(tmp_path, repo_path: str, current_sha: str, transport):
    now = datetime.now(UTC)
    git = FakeGitInspection(
        RepositoryInfo(root=repo_path, branch="main", head_sha=current_sha),
        GitSummary(
            repository_root=repo_path,
            branch="main",
            head_sha=current_sha,
            is_clean=True,
            total_additions=0,
            total_deletions=0,
            patch="",
            refreshed_at=now,
        ),
    )
    app = create_app(
        settings=Settings(database_path=tmp_path / "runtime.sqlite3"),
        git_inspection=git,
        credential_store=InMemoryCredentialStore(),
        http_transport=transport,
    )
    return app, TestClient(app)


def test_identity_provider_outcome_recovery_passport_flow(tmp_path) -> None:
    repo_path, baseline_sha, current_sha = _init_repo(tmp_path)
    transport = FakeHttpTransport(
        [
            json_response(
                201,
                {
                    "number": 7,
                    "html_url": "https://github.com/acme/widgets/pull/7",
                    "head": {"sha": current_sha},
                    "draft": True,
                },
            ),
            json_response(
                200,
                {
                    "check_runs": [
                        {
                            "name": "build",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": current_sha,
                        }
                    ]
                },
            ),
        ]
    )
    app, client = _build_client(tmp_path, repo_path, current_sha, transport)

    with client:
        created = client.post(
            "/api/v1/changes",
            json={
                "title": "Runtime routes",
                "intent": "Exercise identity/provider/outcome/recovery/passport",
                "repository_path": repo_path,
            },
        )
        assert created.status_code == 201
        change_id = created.json()["id"]

        actor = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "CI Agent"}
        )
        assert actor.status_code == 201
        actor_id = actor.json()["id"]
        assert client.get(f"/api/v1/actors/{actor_id}").status_code == 200

        delegation = client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": str(uuid4()),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["github.pr.create", "recovery.execute"],
                "ttl_seconds": 3600,
            },
        )
        assert delegation.status_code == 201
        assert delegation.json()["repository_path"] == repo_path

        listed_delegations = client.get(f"/api/v1/changes/{change_id}/delegations")
        assert listed_delegations.json()["count"] == 1

        status_before = client.get("/api/v1/providers/github/status")
        assert status_before.json() == {"provider": "github", "configured": False}

        connected = client.post(
            "/api/v1/providers/github/connect", json={"token": "gh-secret-token"}
        )
        assert connected.status_code == 200
        assert connected.json()["configured"] is True
        assert "gh-secret-token" not in connected.text

        pr_grant = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        )
        assert pr_grant.status_code == 201
        assert "gh-secret-token" not in pr_grant.text
        pr_grant_id = pr_grant.json()["id"]

        pr_body = {
            "actor_id": actor_id,
            "grant_id": pr_grant_id,
            "base_branch": "main",
            "head_branch": "feature",
            "title": "Test PR",
            "idempotency_key": "pr-create-1",
        }
        pr_response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls", json=pr_body
        )
        assert pr_response.status_code == 200
        assert pr_response.json()["status"] == "SUCCEEDED"
        assert pr_response.json()["safe_metadata"]["number"] == 7

        # Same idempotency key replays the stored result instead of a
        # second GitHub call or a second stored operation.
        pr_replay = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls", json=pr_body
        )
        assert pr_replay.status_code == 200
        assert pr_replay.json()["id"] == pr_response.json()["id"]

        read_grant = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.repo.read"],
                "ttl_seconds": 900,
            },
        )
        assert read_grant.status_code == 201
        read_grant_id = read_grant.json()["id"]

        refreshed = client.post(f"/api/v1/changes/{change_id}/refresh")
        assert refreshed.status_code == 200

        outcomes = client.post(
            f"/api/v1/changes/{change_id}/outcomes/refresh",
            json={"grant_id": read_grant_id, "required_check_names": ["build"]},
        )
        assert outcomes.status_code == 200
        assert outcomes.json()["count"] == 1
        assert outcomes.json()["items"][0]["status"] == "PASSED"
        assert client.get(f"/api/v1/changes/{change_id}/outcomes").json()["count"] == 1

        # Recovery needs at least one Git checkpoint. Seeded directly
        # against the shared schema the way `[KB]`'s GitStateTracker will
        # once that stream lands; this route does not depend on it.
        _seed_checkpoint(app.state.database, change_id, repo_path, baseline_sha)

        preview = client.post(f"/api/v1/changes/{change_id}/recovery/preview")
        assert preview.status_code == 201
        plan = preview.json()
        assert plan["status"] == "PLANNED"
        assert len(plan["actions"]) == 1
        assert plan["actions"][0]["supported"] is True

        latest_plan = client.get(f"/api/v1/changes/{change_id}/recovery")
        assert latest_plan.status_code == 200
        assert latest_plan.json()["id"] == plan["id"]

        executed = client.post(
            f"/api/v1/changes/{change_id}/recovery/{plan['id']}/execute",
            json={"actor_id": actor_id, "approval_token": "approved-by-test"},
        )
        assert executed.status_code == 200
        assert executed.json()["status"] == "RECOVERED"

        passport = client.post(f"/api/v1/changes/{change_id}/passport")
        assert passport.status_code == 201
        passport_body = passport.json()
        assert passport_body["change_id"] == change_id
        assert any(
            entry["kind"] == "git_checkpoint" for entry in passport_body["evidence"]
        )
        assert passport_body["recovery_status"] == "RECOVERED"
        # Environment/dependency/assurance evidence is genuinely absent
        # (`[KB]`'s stream is not wired yet); the Passport must say so
        # honestly rather than fabricate a reference.
        assert any(
            "environment passport" in limitation
            for limitation in passport_body["limitations"]
        )

        latest_passport = client.get(f"/api/v1/changes/{change_id}/passport")
        assert latest_passport.status_code == 200
        assert (
            latest_passport.json()["canonical_digest"]
            == passport_body["canonical_digest"]
        )


def test_policy_denies_operation_without_matching_delegation(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))
    del app

    with client:
        created = client.post(
            "/api/v1/changes",
            json={
                "title": "No authority",
                "intent": "Exercise default-deny policy",
                "repository_path": repo_path,
            },
        )
        change_id = created.json()["id"]

        actor = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Unauthorized"}
        )
        actor_id = actor.json()["id"]

        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        )
        grant_id = grant.json()["id"]

        # No delegation was ever created for this actor/Change, so policy
        # must default-deny even though a credential grant exists.
        response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature",
                "title": "Blocked PR",
                "idempotency_key": "blocked-1",
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "POLICY_DENIED"


def test_grant_bound_to_different_change_is_rejected(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))
    del app

    with client:
        change_a = client.post(
            "/api/v1/changes",
            json={
                "title": "Change A",
                "intent": "Owns the grant",
                "repository_path": repo_path,
            },
        ).json()["id"]
        change_b = client.post(
            "/api/v1/changes",
            json={
                "title": "Change B",
                "intent": "Must not use Change A's grant",
                "repository_path": repo_path,
            },
        ).json()["id"]

        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Cross-change"}
        ).json()["id"]

        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": str(uuid4()),
                "grantee_id": actor_id,
                "change_id": change_b,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 3600,
            },
        )
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_a}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        ).json()["id"]

        response = client.post(
            f"/api/v1/changes/{change_b}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature",
                "title": "Cross-change PR",
                "idempotency_key": "cross-1",
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CREDENTIAL_GRANT_BINDING_INVALID"
