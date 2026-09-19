from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.app.contracts.models import (
    ChangeView,
    EvidenceStatus,
    GitCheckpoint,
    GitSummary,
    RecoveryStatus,
    ReviewState,
)
from backend.app.contracts.ports import PassportPort
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.identity.models import Delegation
from backend.app.identity.repository import DelegationRepository
from backend.app.passport.builder import PassportBuilder

REPO_PATH = "C:\\work\\repo"


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "passport.sqlite3")
    database.initialize()
    return database


def _seed_change(database: Database, *, head_sha: str | None = None) -> ChangeView:
    now = datetime.now(UTC)
    change_id = uuid4()
    ChangeRepository(database).create(
        StoredChange(
            id=change_id,
            title="Passport test change",
            intent="Exercise passport building",
            repository_path=REPO_PATH,
            created_at=now,
            updated_at=now,
            last_refreshed_at=None,
            git_summary=None,
            verification=None,
        )
    )
    git_summary = (
        GitSummary(
            repository_root=REPO_PATH,
            branch="main",
            head_sha=head_sha,
            is_clean=False,
            total_additions=1,
            total_deletions=0,
            patch="",
            refreshed_at=now,
        )
        if head_sha
        else None
    )
    return ChangeView(
        id=change_id,
        title="Passport test change",
        intent="Exercise passport building",
        repository_path=REPO_PATH,
        created_at=now,
        updated_at=now,
        review_state=ReviewState.NO_CHANGES,
        git_summary=git_summary,
    )


def _seed_checkpoint(database: Database, change_id, head_sha: str, captured_at: datetime) -> None:
    checkpoint = GitCheckpoint(
        id=uuid4(),
        change_id=change_id,
        name="checkpoint",
        repository_root=REPO_PATH,
        branch="main",
        head_sha=head_sha,
        status_digest=hashlib.sha256(head_sha.encode()).hexdigest(),
        summary=GitSummary(
            repository_root=REPO_PATH,
            branch="main",
            head_sha=head_sha,
            is_clean=True,
            total_additions=0,
            total_deletions=0,
            patch="",
            refreshed_at=captured_at,
        ),
        evidence_revision=1,
        captured_at=captured_at,
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
                str(change_id),
                checkpoint.name,
                checkpoint.head_sha,
                checkpoint.evidence_revision,
                checkpoint.model_dump_json(),
                checkpoint.captured_at.isoformat(),
            ),
        )


def _seed_delegation(database: Database, change_id, *, grantee_id, scopes: list[str]) -> None:
    now = datetime.now(UTC)
    delegation = Delegation(
        id=uuid4(),
        grantor_id=uuid4(),
        grantee_id=grantee_id,
        change_id=change_id,
        repository_path=REPO_PATH,
        scopes=scopes,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    DelegationRepository(database).create(delegation)


def test_builder_satisfies_the_frozen_port(tmp_path) -> None:
    database = _database(tmp_path)
    builder = PassportBuilder(database, DelegationRepository(database))
    assert isinstance(builder, PassportPort)


def test_passport_with_no_evidence_lists_all_limitations(tmp_path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    builder = PassportBuilder(database, DelegationRepository(database))

    passport = builder.build(change)

    assert passport.evidence == []
    assert passport.outcomes == []
    assert passport.recovery_status is None
    assert any("Git checkpoint" in item for item in passport.limitations)
    assert any("recovery plan" in item for item in passport.limitations)


def test_current_checkpoint_is_marked_current(tmp_path) -> None:
    database = _database(tmp_path)
    head_sha = "a" * 40
    change = _seed_change(database, head_sha=head_sha)
    _seed_checkpoint(database, change.id, head_sha, datetime.now(UTC))
    builder = PassportBuilder(database, DelegationRepository(database))

    passport = builder.build(change)

    checkpoint_refs = [item for item in passport.evidence if item.kind == "git_checkpoint"]
    assert len(checkpoint_refs) == 1
    assert checkpoint_refs[0].status is EvidenceStatus.CURRENT


def test_stale_checkpoint_is_marked_stale(tmp_path) -> None:
    database = _database(tmp_path)
    current_sha = "b" * 40
    stale_sha = "a" * 40
    change = _seed_change(database, head_sha=current_sha)
    _seed_checkpoint(database, change.id, stale_sha, datetime.now(UTC))
    builder = PassportBuilder(database, DelegationRepository(database))

    passport = builder.build(change)

    checkpoint_refs = [item for item in passport.evidence if item.kind == "git_checkpoint"]
    assert checkpoint_refs[0].status is EvidenceStatus.STALE


def test_delegations_feed_actor_ids_and_authority_summary(tmp_path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    grantee_id = uuid4()
    _seed_delegation(database, change.id, grantee_id=grantee_id, scopes=["github.pr.create"])
    builder = PassportBuilder(database, DelegationRepository(database))

    passport = builder.build(change)

    assert passport.actor_ids == [grantee_id]
    assert any("github.pr.create" in item for item in passport.authority_summary)


def test_same_state_produces_the_same_canonical_digest(tmp_path) -> None:
    database = _database(tmp_path)
    head_sha = "c" * 40
    change = _seed_change(database, head_sha=head_sha)
    _seed_checkpoint(database, change.id, head_sha, datetime.now(UTC))
    builder = PassportBuilder(database, DelegationRepository(database))

    first = builder.build(change)
    second = builder.build(change)

    assert first.id != second.id
    assert first.canonical_digest == second.canonical_digest


def test_digest_changes_when_evidence_changes(tmp_path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    builder = PassportBuilder(database, DelegationRepository(database))
    before = builder.build(change)

    _seed_checkpoint(database, change.id, "d" * 40, datetime.now(UTC))
    after = builder.build(change)

    assert before.canonical_digest != after.canonical_digest
