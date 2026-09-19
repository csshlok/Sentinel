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


def _grantor_id(client) -> str:
    """Threat model finding #5: grantor_id must now resolve to a real

    Actor, so a synthetic uuid4() no longer works as a delegation grantor
    in tests; this creates a real one.
    """
    return client.post(
        "/api/v1/actors", json={"kind": "HUMAN", "display_name": "Grantor"}
    ).json()["id"]

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


def _build_client(tmp_path, repo_path: str, current_sha: str, transport, *, settings=None):
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
        settings=settings or Settings(database_path=tmp_path / "runtime.sqlite3"),
        git_inspection=git,
        credential_store=InMemoryCredentialStore(),
        http_transport=transport,
    )
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {app.state.api_token}"
    return app, client


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
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["github.pr.create", "recovery.execute", "github.repo.read"],
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
            json={"actor_id": actor_id, "grant_id": read_grant_id,
                  "required_check_names": ["build"]},
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

        # Reproduces the audit finding: retrying execute() on an already
        # -terminal plan must return the stored RECOVERED result, not
        # re-attempt Git operations that turn a real success into a
        # reported CONFLICTED purely from the retry.
        retried = client.post(
            f"/api/v1/changes/{change_id}/recovery/{plan['id']}/execute",
            json={"actor_id": actor_id, "approval_token": "approved-by-test"},
        )
        assert retried.status_code == 200
        assert retried.json() == executed.json()

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


def test_delegation_creation_rejects_self_delegation_and_unknown_grantor(tmp_path) -> None:
    """Threat model finding #5: grantor_id was never validated -- an actor

    could name itself as its own grantor (self-issuing unlimited authority)
    or name a nonexistent UUID (making the delegation's attribution
    meaningless for audit purposes). Both must now be refused.
    """

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))
    del app

    with client:
        change_id = client.post("/api/v1/changes", json={
            "title": "Grantor validation", "intent": "Exercise finding #5",
            "repository_path": repo_path,
        }).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Actor"}
        ).json()["id"]

        self_delegation = client.post("/api/v1/delegations", json={
            "grantor_id": actor_id, "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["agent.launch"], "ttl_seconds": 3600,
        })
        assert self_delegation.status_code == 422
        assert self_delegation.json()["error"]["code"] == "SELF_DELEGATION_NOT_PERMITTED"

        unknown_grantor = client.post("/api/v1/delegations", json={
            "grantor_id": str(uuid4()), "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["agent.launch"], "ttl_seconds": 3600,
        })
        assert unknown_grantor.status_code == 404
        assert unknown_grantor.json()["error"]["code"] == "ACTOR_NOT_FOUND"


def test_policy_denies_operation_without_matching_delegation(tmp_path) -> None:
    """Threat model finding #1: issuing a CredentialGrant now itself requires

    a matching Delegation for every requested scope, so the actor without
    any delegation cannot even mint a usable grant -- the vulnerability
    ("policy must default-deny even though a credential grant exists") no
    longer needs a separate downstream check, because the grant can never
    come into existence in the first place. Also confirms that a grant
    covering only an unrelated scope cannot be leveraged to mint a further
    grant for github.pr.create.
    """

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

        # No delegation was ever created for this actor/Change, so grant
        # issuance itself must default-deny.
        denied_grant = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create"], "ttl_seconds": 900},
        )
        assert denied_grant.status_code == 403
        assert denied_grant.json()["error"]["code"] == "POLICY_DENIED"

        # A delegation for a *different* scope does not let the actor mint
        # a grant for github.pr.create either.
        client.post("/api/v1/delegations", json={
            "grantor_id": _grantor_id(client), "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["github.repo.read"], "ttl_seconds": 3600,
        })
        still_denied = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create"], "ttl_seconds": 900},
        )
        assert still_denied.status_code == 403
        assert still_denied.json()["error"]["code"] == "POLICY_DENIED"


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
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_b,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 3600,
            },
        )
        # A delegation on Change A too, purely so the grant *can* be minted
        # for Change A (threat model finding #1's new check) -- the actual
        # cross-change binding check below is unaffected by this.
        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_a,
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


def test_change_lifecycle_transitions_use_real_evidence(tmp_path) -> None:
    """`RuntimeLifecycleFacts` end to end: authority gates `ACTIVE`, and a
    real recovery plan/execution gates the `RECOVERY_PENDING -> RECOVERING
    -> RECOVERED_VERIFIED` branch — through the real API, not a fake port."""

    repo_path, baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        created = client.post(
            "/api/v1/changes",
            json={
                "title": "Lifecycle evidence",
                "intent": "Exercise RuntimeLifecycleFacts through the real API",
                "repository_path": repo_path,
            },
        )
        change_id = created.json()["id"]
        assert created.json()["lifecycle_state"] == "DRAFT"

        # No delegation yet: ACTIVE is blocked on real, not fabricated, authority.
        blocked = client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "ACTIVE", "expected_revision": 1},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "TRANSITION_GUARD_FAILED"
        assert blocked.json()["error"]["details"]["missing_requirements"] == [
            "authority_valid"
        ]

        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Lifecycle Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["recovery.execute"],
                "ttl_seconds": 3600,
            },
        )

        activated = client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "ACTIVE", "expected_revision": 1},
        )
        assert activated.status_code == 200
        assert activated.json()["lifecycle_state"] == "ACTIVE"
        revision = activated.json()["revision"]

        pending = client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "RECOVERY_PENDING", "expected_revision": revision},
        )
        assert pending.status_code == 200
        revision = pending.json()["revision"]

        # Recovering needs a real approved-and-recovered plan; seeded the
        # same way `[KB]`'s GitStateTracker will once it exists.
        _seed_checkpoint(app.state.database, change_id, repo_path, baseline_sha)
        plan_id = client.post(f"/api/v1/changes/{change_id}/recovery/preview").json()["id"]
        executed = client.post(
            f"/api/v1/changes/{change_id}/recovery/{plan_id}/execute",
            json={"actor_id": actor_id, "approval_token": "approved-by-test"},
        )
        assert executed.json()["status"] == "RECOVERED"

        recovering = client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "RECOVERING", "expected_revision": revision},
        )
        assert recovering.status_code == 200
        assert recovering.json()["lifecycle_state"] == "RECOVERING"
        revision = recovering.json()["revision"]

        verified = client.post(
            f"/api/v1/changes/{change_id}/transition",
            json={"target_state": "RECOVERED_VERIFIED", "expected_revision": revision},
        )
        assert verified.status_code == 200
        assert verified.json()["lifecycle_state"] == "RECOVERED_VERIFIED"


def test_state_persists_across_a_real_app_restart(tmp_path) -> None:
    """Change/actor/delegation/recovery-plan state survives tearing down and
    rebuilding `create_app()` against the same database file — not just a
    second connection within one process, but a genuinely new app instance,
    the way a real process restart would look."""

    db_path = tmp_path / "restart.sqlite3"
    settings = Settings(database_path=db_path)
    repo_path, baseline_sha, current_sha = _init_repo(tmp_path)

    app1, client1 = _build_client(
        tmp_path, repo_path, current_sha, FakeHttpTransport([]), settings=settings
    )
    with client1:
        created = client1.post(
            "/api/v1/changes",
            json={
                "title": "Restart survivor",
                "intent": "Prove state outlives one app instance",
                "repository_path": repo_path,
            },
        )
        change_id = created.json()["id"]

        actor_id = client1.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Persisted Agent"}
        ).json()["id"]

        client1.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client1),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["recovery.execute"],
                "ttl_seconds": 3600,
            },
        )

        _seed_checkpoint(app1.state.database, change_id, repo_path, baseline_sha)
        plan_id = client1.post(f"/api/v1/changes/{change_id}/recovery/preview").json()["id"]

    # Tear down the first app entirely and build a brand-new one against
    # the same on-disk database, exactly like a real process restart.
    del app1, client1
    app2, client2 = _build_client(
        tmp_path, repo_path, current_sha, FakeHttpTransport([]), settings=settings
    )
    with client2:
        refetched_change = client2.get(f"/api/v1/changes/{change_id}")
        assert refetched_change.status_code == 200
        assert refetched_change.json()["title"] == "Restart survivor"

        refetched_actor = client2.get(f"/api/v1/actors/{actor_id}")
        assert refetched_actor.status_code == 200

        refetched_delegations = client2.get(f"/api/v1/changes/{change_id}/delegations")
        assert refetched_delegations.json()["count"] == 1

        refetched_plan = client2.get(f"/api/v1/changes/{change_id}/recovery")
        assert refetched_plan.status_code == 200
        assert refetched_plan.json()["id"] == plan_id


def test_credential_grants_are_usable_and_revocable_across_a_real_app_restart(tmp_path) -> None:
    """Reproduces the audit finding: CredentialBroker cached grants only in

    process memory, so a grant issued before a restart became invisible to
    the broker afterward even though it was still durably persisted --
    resolve_secret raised CREDENTIAL_GRANT_NOT_FOUND and revoke_grant did
    too, despite GET-style lookups still finding the grant.
    """

    db_path = tmp_path / "restart_credentials.sqlite3"
    settings = Settings(database_path=db_path)
    repo_path, baseline_sha, current_sha = _init_repo(tmp_path)

    app1, client1 = _build_client(
        tmp_path, repo_path, current_sha, FakeHttpTransport([]), settings=settings
    )
    with client1:
        change_id = client1.post(
            "/api/v1/changes",
            json={
                "title": "Grant survives a restart",
                "intent": "Prove credential grants outlive one app instance",
                "repository_path": repo_path,
            },
        ).json()["id"]
        actor_id = client1.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}
        ).json()["id"]
        client1.post("/api/v1/delegations", json={
            "grantor_id": _grantor_id(client1), "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["github.pr.create"], "ttl_seconds": 3600,
        })
        client1.post("/api/v1/providers/github/connect", json={"token": "gh-secret-token"})
        grant_id = client1.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create"], "ttl_seconds": 3600},
        ).json()["id"]

    del app1, client1
    app2, client2 = _build_client(
        tmp_path, repo_path, current_sha, FakeHttpTransport([]), settings=settings
    )
    with client2:
        revoked = client2.post(
            f"/api/v1/changes/{change_id}/providers/github/grants/{grant_id}/revoke"
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["revoked_at"] is not None


def test_close_pull_request_compensates_the_changes_own_created_pr(tmp_path) -> None:
    """Real end-to-end provider compensation: create a PR through the API,

    then close it through the new compensation route, and confirm the
    close call targets the exact PR the Change itself created (not a
    caller-supplied number) and is idempotency-key-replay-safe like every
    other provider mutation.
    """

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    transport = FakeHttpTransport([
        json_response(201, {
            "number": 7, "html_url": "https://github.com/acme/widgets/pull/7",
            "draft": True, "head": {"sha": current_sha},
        }),
        json_response(200, {
            "number": 7, "html_url": "https://github.com/acme/widgets/pull/7",
            "draft": False, "head": {"sha": current_sha, "ref": "feature"},
        }),
    ])
    app, client = _build_client(tmp_path, repo_path, current_sha, transport)

    with client:
        change_id = client.post("/api/v1/changes", json={
            "title": "Compensation flow", "intent": "Exercise provider compensation",
            "repository_path": repo_path,
        }).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}
        ).json()["id"]
        client.post("/api/v1/delegations", json={
            "grantor_id": _grantor_id(client), "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["github.pr.create", "github.pr.close"], "ttl_seconds": 3600,
        })
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.create", "github.pr.close"],
                  "ttl_seconds": 900},
        ).json()["id"]

        created = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={"actor_id": actor_id, "grant_id": grant_id, "base_branch": "main",
                  "head_branch": "feature", "title": "Test PR",
                  "idempotency_key": "pr-create-1"},
        )
        assert created.status_code == 200 and created.json()["status"] == "SUCCEEDED"

        closed = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls/close",
            json={"actor_id": actor_id, "grant_id": grant_id,
                  "idempotency_key": "pr-close-1"},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "SUCCEEDED"
        assert closed.json()["safe_metadata"]["number"] == 7
        assert closed.json()["safe_metadata"]["state"] == "CLOSED"

        replay = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls/close",
            json={"actor_id": actor_id, "grant_id": grant_id,
                  "idempotency_key": "pr-close-1"},
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == closed.json()["id"]


def test_outcome_refresh_is_bound_to_the_calling_actor(tmp_path) -> None:
    """Threat model finding #4: OutcomeService.refresh only checked

    grant.change_id, not who was calling -- any actor holding any grant
    bound to a Change (issued to a *different* actor) could read its
    GitHub PR/CI status. Now uses require_grant (actor+Change binding) and
    is policy-gated like every other provider read.
    """

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))
    del app

    with client:
        change_id = client.post("/api/v1/changes", json={
            "title": "Outcome binding", "intent": "Exercise actor-bound outcome refresh",
            "repository_path": repo_path,
        }).json()["id"]

        owner_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Owner"}
        ).json()["id"]
        stranger_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Stranger"}
        ).json()["id"]
        client.post("/api/v1/delegations", json={
            "grantor_id": _grantor_id(client), "grantee_id": owner_id, "change_id": change_id,
            "scopes": ["github.repo.read"], "ttl_seconds": 3600,
        })
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": owner_id, "scopes": ["github.repo.read"], "ttl_seconds": 900},
        ).json()["id"]

        # The owner can use their own grant.
        as_owner = client.post(
            f"/api/v1/changes/{change_id}/outcomes/refresh",
            json={"actor_id": owner_id, "grant_id": grant_id, "required_check_names": []},
        )
        assert as_owner.status_code == 200

        # A different actor cannot use the owner's grant, even though it is
        # bound to this same Change.
        as_stranger = client.post(
            f"/api/v1/changes/{change_id}/outcomes/refresh",
            json={"actor_id": stranger_id, "grant_id": grant_id, "required_check_names": []},
        )
        assert as_stranger.status_code == 403
        assert as_stranger.json()["error"]["code"] == "CREDENTIAL_GRANT_BINDING_INVALID"


def test_close_pull_request_without_a_created_pr_is_refused(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    app, client = _build_client(tmp_path, repo_path, current_sha, FakeHttpTransport([]))

    with client:
        change_id = client.post("/api/v1/changes", json={
            "title": "No PR yet", "intent": "Refuse compensation with nothing to compensate",
            "repository_path": repo_path,
        }).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Agent"}
        ).json()["id"]
        client.post("/api/v1/delegations", json={
            "grantor_id": _grantor_id(client), "grantee_id": actor_id, "change_id": change_id,
            "scopes": ["github.pr.close"], "ttl_seconds": 3600,
        })
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={"actor_id": actor_id, "scopes": ["github.pr.close"], "ttl_seconds": 900},
        ).json()["id"]

        refused = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls/close",
            json={"actor_id": actor_id, "grant_id": grant_id, "idempotency_key": "k"},
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "NO_PULL_REQUEST_TO_COMPENSATE"


def _init_repo_without_github_remote(tmp_path) -> str:
    repo = tmp_path / "repo-no-remote"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "config", "user.email", "test@example.com")
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    _run(repo, "add", "file.txt")
    _run(repo, "commit", "-m", "baseline")
    return str(repo)


def test_provider_operation_records_failure_after_exhausted_retries(tmp_path) -> None:
    """A GitHub 5xx that outlasts every retry must not become an unhandled
    500: `GitHubProviderAdapter` records it as a `FAILED` operation with the
    provider's own stable error code, and that failure is persisted like any
    other operation — not silently dropped."""

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    # GitHubProvider retries a 5xx up to max_retries=3 times (4 attempts
    # total) before giving up; queue one failing response per attempt.
    transport = FakeHttpTransport([json_response(503, {"message": "degraded"})] * 4)
    app, client = _build_client(tmp_path, repo_path, current_sha, transport)
    del app

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={
                "title": "Provider outage",
                "intent": "Exercise exhausted-retry failure handling",
                "repository_path": repo_path,
            },
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Outage Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 3600,
            },
        )
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        ).json()["id"]

        response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature",
                "title": "Outage PR",
                "idempotency_key": "outage-1",
            },
        )
        # Provider failure is a recorded outcome, not an API crash.
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "FAILED"
        assert body["safe_metadata"]["error_code"] == "PROVIDER_UNAVAILABLE"
        assert len(transport.calls) == 4

        # The failure is durable: re-listing the outcomes of this
        # idempotency key returns the same FAILED record, not a retry.
        outcomes_after = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature",
                "title": "Outage PR",
                "idempotency_key": "outage-1",
            },
        )
        assert outcomes_after.json()["id"] == body["id"]
        # No further HTTP calls: the idempotency-key replay short-circuits
        # before the provider is ever called again.
        assert len(transport.calls) == 4


def test_provider_operation_records_immediate_failure_for_not_found(tmp_path) -> None:
    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    transport = FakeHttpTransport([json_response(404, {"message": "no such repository"})])
    app, client = _build_client(tmp_path, repo_path, current_sha, transport)
    del app

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={
                "title": "Missing repository",
                "intent": "Exercise immediate non-retryable failure",
                "repository_path": repo_path,
            },
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "404 Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 3600,
            },
        )
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        ).json()["id"]

        response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature",
                "title": "404 PR",
                "idempotency_key": "not-found-1",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "FAILED"
        assert response.json()["safe_metadata"]["error_code"] == "PROVIDER_NOT_FOUND"
        # 404 is not in the retryable set: exactly one HTTP call was made.
        assert len(transport.calls) == 1


def test_pull_request_route_returns_stable_error_when_repository_has_no_github_remote(
    tmp_path,
) -> None:
    """Unlike a GitHub-side failure, an unresolvable local repository slug
    is a genuine request-level error `[SD]`'s composition layer raises
    directly — before any GitHub call — and it must reach the client as the
    documented `{"error": {"code", ...}}` envelope, not an internal 500."""

    repo_path = _init_repo_without_github_remote(tmp_path)
    now = datetime.now(UTC)
    head_sha = "d" * 40
    app, client = _build_client(tmp_path, repo_path, head_sha, FakeHttpTransport([]))
    del app, now

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={
                "title": "No remote",
                "intent": "Exercise unresolved-repository-slug error",
                "repository_path": repo_path,
            },
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "No Remote Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 3600,
            },
        )
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        ).json()["id"]

        response = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature",
                "title": "No remote PR",
                "idempotency_key": "no-remote-1",
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PROVIDER_REPOSITORY_UNRESOLVED"


def test_idempotency_key_reused_for_a_genuinely_different_pr_is_rejected(tmp_path) -> None:
    """An idempotency key must mean "the same request, safe to replay," not
    "any request with this key." Reusing one with a different base/head
    branch or title is a caller bug (key collision), and must be a stable
    error — never a silent no-op that looks like success while creating no
    PR for the actual request."""

    repo_path, _baseline_sha, current_sha = _init_repo(tmp_path)
    transport = FakeHttpTransport(
        [
            json_response(
                201,
                {
                    "number": 1,
                    "html_url": "https://github.com/acme/widgets/pull/1",
                    "head": {"sha": current_sha},
                    "draft": True,
                },
            )
        ]
    )
    app, client = _build_client(tmp_path, repo_path, current_sha, transport)
    del app

    with client:
        change_id = client.post(
            "/api/v1/changes",
            json={
                "title": "Idempotency collision",
                "intent": "Exercise a reused key with a different body",
                "repository_path": repo_path,
            },
        ).json()["id"]
        actor_id = client.post(
            "/api/v1/actors", json={"kind": "AGENT", "display_name": "Collision Agent"}
        ).json()["id"]
        client.post(
            "/api/v1/delegations",
            json={
                "grantor_id": _grantor_id(client),
                "grantee_id": actor_id,
                "change_id": change_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 3600,
            },
        )
        client.post("/api/v1/providers/github/connect", json={"token": "token"})
        grant_id = client.post(
            f"/api/v1/changes/{change_id}/providers/github/grants",
            json={
                "actor_id": actor_id,
                "scopes": ["github.pr.create"],
                "ttl_seconds": 900,
            },
        ).json()["id"]

        first = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature-A",
                "title": "PR A",
                "idempotency_key": "shared-key",
            },
        )
        assert first.status_code == 200
        assert first.json()["status"] == "SUCCEEDED"

        # Same key, genuinely different PR: must be rejected, not silently
        # return PR A's result as if it were the answer for PR B.
        second = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature-B",
                "title": "PR B",
                "idempotency_key": "shared-key",
            },
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

        # An exact replay of the original request still returns the
        # original stored result, with no second GitHub call.
        replay = client.post(
            f"/api/v1/changes/{change_id}/providers/github/pulls",
            json={
                "actor_id": actor_id,
                "grant_id": grant_id,
                "base_branch": "main",
                "head_branch": "feature-A",
                "title": "PR A",
                "idempotency_key": "shared-key",
            },
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]
        assert len(transport.calls) == 1
