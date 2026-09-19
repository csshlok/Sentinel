"""Reproduces the audit finding: a journal-write failure left a mutation

durably committed even though the request that caused it reported failure.
`IdentityAdminService.create_delegation`/`revoke_delegation` and
`CredentialAdminService.issue_grant`/`revoke_grant` now share one SQLite
transaction between the repository write and the paired journal event
(`Database.connection_or`), so a raised journal error rolls back the
repository write too -- the client's "this failed" is no longer a lie about
what the database actually holds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.contracts.models import (
    Actor,
    ActorKind,
    ChangeContract,
    ChangeView,
    DelegationCreateRequest,
    PolicyDecision,
    ReviewState,
    RiskLevel,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.runtime_repositories import CredentialGrantRepository
from backend.app.core.runtime_service import CredentialAdminService, IdentityAdminService
from backend.app.credentials.broker import CredentialBroker
from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.identity.repository import ActorRepository, DelegationRepository

REPO_PATH = "C:\\work\\repo"


class _ExplodingJournal:
    """A journal double that always fails, to prove the mutation it would

    have described does not survive when the append raises."""

    def append(self, *args, **kwargs):
        raise RuntimeError("journal backend unavailable")


class _AllowAllPolicy:
    """These tests exercise journal-failure atomicity, not authorization --

    a permissive policy keeps issue_grant/revoke_grant's own authority
    check (threat model finding #1) out of the way here.
    """

    def evaluate(self, actor_id, change, operation, parameters):
        del actor_id, change, operation, parameters
        return PolicyDecision(
            allowed=True, reason_code="ALLOWED", explanation="allowed for the test",
            risk_level=RiskLevel.LOW,
        )


class _FakeChangeService:
    def __init__(self, change_id) -> None:
        now = datetime.now(UTC)
        self._view = ChangeView(
            id=change_id, title="T", intent="I", repository_path=REPO_PATH,
            created_at=now, updated_at=now, review_state=ReviewState.NO_CHANGES,
            contract=ChangeContract(),
        )

    def get(self, change_id):
        del change_id
        return self._view


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "atomicity.sqlite3")
    database.initialize()
    return database


def _seed_change(database: Database) -> str:
    change_id = uuid4()
    now = datetime.now(UTC)
    ChangeRepository(database).create(
        StoredChange(
            id=change_id, title="T", intent="I", repository_path=REPO_PATH,
            created_at=now, updated_at=now, last_refreshed_at=None,
            git_summary=None, verification=None,
        )
    )
    return str(change_id)


def test_a_journal_failure_rolls_back_delegation_creation(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = _seed_change(database)
    actors = ActorRepository(database)
    delegations = DelegationRepository(database)
    now = datetime.now(UTC)
    grantee = actors.create(
        Actor(id=uuid4(), kind=ActorKind.AGENT, display_name="Agent",
              created_at=now, updated_at=now)
    )
    grantor = actors.create(
        Actor(id=uuid4(), kind=ActorKind.HUMAN, display_name="Grantor",
              created_at=now, updated_at=now)
    )
    service = IdentityAdminService(actors, delegations, journal=_ExplodingJournal())

    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        service.create_delegation(
            DelegationCreateRequest(
                grantor_id=grantor.id, grantee_id=grantee.id, change_id=change_id,
                scopes=["agent.launch"], ttl_seconds=3600,
            ),
            repository_path=REPO_PATH,
        )

    assert delegations.list_for_change(change_id) == []


def test_a_journal_failure_rolls_back_delegation_revocation(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = _seed_change(database)
    actors = ActorRepository(database)
    delegations = DelegationRepository(database)
    now = datetime.now(UTC)
    grantee = actors.create(
        Actor(id=uuid4(), kind=ActorKind.AGENT, display_name="Agent",
              created_at=now, updated_at=now)
    )
    grantor = actors.create(
        Actor(id=uuid4(), kind=ActorKind.HUMAN, display_name="Grantor",
              created_at=now, updated_at=now)
    )
    # Issue the delegation through a working journal first.
    service = IdentityAdminService(actors, delegations)
    delegation = service.create_delegation(
        DelegationCreateRequest(
            grantor_id=grantor.id, grantee_id=grantee.id, change_id=change_id,
            scopes=["agent.launch"], ttl_seconds=3600,
        ),
        repository_path=REPO_PATH,
    )

    failing_service = IdentityAdminService(actors, delegations, journal=_ExplodingJournal())
    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        failing_service.revoke_delegation(delegation.id)

    # The revocation must not have taken effect: revoked_at stays None.
    assert delegations.get(delegation.id).revoked_at is None


def test_a_journal_failure_rolls_back_credential_grant_issuance(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = _seed_change(database)
    actors = ActorRepository(database)
    grants = CredentialGrantRepository(database)
    now = datetime.now(UTC)
    actor = actors.create(
        Actor(id=uuid4(), kind=ActorKind.AGENT, display_name="Agent",
              created_at=now, updated_at=now)
    )
    broker = CredentialBroker(InMemoryCredentialStore())
    service = CredentialAdminService(
        broker, actors, grants, policy=_AllowAllPolicy(),
        change_service=_FakeChangeService(change_id), journal=_ExplodingJournal(),
    )

    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        service.issue_grant(actor.id, change_id, ["github.pr.create"], 3600)

    # The broker issued it in memory, but the durable row must not exist --
    # a restart (or any GET-style lookup backed by the repository) must never
    # see a grant the request reported as failed.
    with database.connection() as connection:
        rows = connection.execute("SELECT 1 FROM credential_grants").fetchall()
    assert rows == []


def test_a_journal_failure_rolls_back_credential_grant_revocation(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = _seed_change(database)
    actors = ActorRepository(database)
    grants = CredentialGrantRepository(database)
    now = datetime.now(UTC)
    actor = actors.create(
        Actor(id=uuid4(), kind=ActorKind.AGENT, display_name="Agent",
              created_at=now, updated_at=now)
    )
    broker = CredentialBroker(InMemoryCredentialStore(), grant_lookup=grants.get)
    fake_change_service = _FakeChangeService(change_id)
    working_service = CredentialAdminService(
        broker, actors, grants, policy=_AllowAllPolicy(), change_service=fake_change_service,
    )
    grant = working_service.issue_grant(actor.id, change_id, ["github.pr.create"], 3600)

    failing_service = CredentialAdminService(
        broker, actors, grants, policy=_AllowAllPolicy(),
        change_service=fake_change_service, journal=_ExplodingJournal(),
    )
    with pytest.raises(RuntimeError, match="journal backend unavailable"):
        failing_service.revoke_grant(grant.id)

    assert grants.get(grant.id).revoked_at is None
