from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.app.core.database import Database
from backend.app.identity.models import Delegation, DelegationDenialReason
from backend.app.identity.repository import DelegationRepository
from backend.app.identity.service import IdentityService, evaluate_delegation

REPO_PATH = "C:\\work\\repo"
OTHER_REPO_PATH = "C:\\work\\other-repo"
SCOPE = "github.pr.create"


def _delegation(now: datetime, **overrides: object) -> Delegation:
    change_id = overrides.pop("change_id", uuid4())
    defaults: dict[str, object] = dict(
        id=uuid4(),
        grantor_actor_id=uuid4(),
        grantee_actor_id=uuid4(),
        change_id=change_id,
        repository_path=REPO_PATH,
        scopes=[SCOPE],
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
    )
    defaults.update(overrides)
    return Delegation(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("build_kwargs", "expected_reason"),
    [
        ({"revoked_at": lambda now: now - timedelta(seconds=1)}, DelegationDenialReason.REVOKED),
        (
            {"issued_at": lambda now: now + timedelta(minutes=1)},
            DelegationDenialReason.EXPIRED,
        ),
        (
            {"expires_at": lambda now: now - timedelta(minutes=1)},
            DelegationDenialReason.EXPIRED,
        ),
        ({"scopes": ["other.scope"]}, DelegationDenialReason.SCOPE_NOT_GRANTED),
        (
            {"max_uses": 1, "use_count": 1},
            DelegationDenialReason.EXHAUSTED,
        ),
    ],
)
def test_evaluate_delegation_denies(build_kwargs: dict, expected_reason) -> None:
    now = datetime.now(UTC)
    resolved = {
        key: (value(now) if callable(value) else value)
        for key, value in build_kwargs.items()
    }
    delegation = _delegation(now, **resolved)

    decision = evaluate_delegation(
        delegation,
        change_id=delegation.change_id,
        repository_path=REPO_PATH,
        scope=SCOPE,
        now=now,
    )

    assert decision.allowed is False
    assert decision.denial_reason is expected_reason


def test_evaluate_delegation_denies_missing() -> None:
    now = datetime.now(UTC)
    decision = evaluate_delegation(
        None, change_id=uuid4(), repository_path=REPO_PATH, scope=SCOPE, now=now
    )
    assert decision.allowed is False
    assert decision.denial_reason is DelegationDenialReason.NOT_FOUND


def test_evaluate_delegation_denies_wrong_change() -> None:
    now = datetime.now(UTC)
    delegation = _delegation(now)
    decision = evaluate_delegation(
        delegation,
        change_id=uuid4(),
        repository_path=REPO_PATH,
        scope=SCOPE,
        now=now,
    )
    assert decision.denial_reason is DelegationDenialReason.WRONG_CHANGE


def test_evaluate_delegation_denies_wrong_repository() -> None:
    now = datetime.now(UTC)
    delegation = _delegation(now)
    decision = evaluate_delegation(
        delegation,
        change_id=delegation.change_id,
        repository_path=OTHER_REPO_PATH,
        scope=SCOPE,
        now=now,
    )
    assert decision.denial_reason is DelegationDenialReason.WRONG_REPOSITORY


def test_evaluate_delegation_allows_exact_boundary_timestamps() -> None:
    now = datetime.now(UTC)
    delegation = _delegation(now, issued_at=now, expires_at=now + timedelta(seconds=1))
    decision = evaluate_delegation(
        delegation,
        change_id=delegation.change_id,
        repository_path=REPO_PATH,
        scope=SCOPE,
        now=now,
    )
    assert decision.allowed is True
    assert decision.delegation_id == delegation.id


def test_evaluate_delegation_denies_at_expiry_instant() -> None:
    now = datetime.now(UTC)
    delegation = _delegation(now, issued_at=now - timedelta(hours=1), expires_at=now)
    decision = evaluate_delegation(
        delegation,
        change_id=delegation.change_id,
        repository_path=REPO_PATH,
        scope=SCOPE,
        now=now,
    )
    assert decision.denial_reason is DelegationDenialReason.EXPIRED


def test_identity_service_authorizes_through_repository(tmp_path) -> None:
    database = Database(tmp_path / "identity.sqlite3")
    database.initialize()
    repository = DelegationRepository(database)
    now = datetime.now(UTC)
    delegation = _delegation(now)
    repository.create(delegation)

    service = IdentityService(repository)

    allowed = service.authorize(
        delegation.id,
        change_id=delegation.change_id,
        repository_path=REPO_PATH,
        scope=SCOPE,
        now=now,
    )
    assert allowed.allowed is True

    denied = service.authorize(
        uuid4(),
        change_id=delegation.change_id,
        repository_path=REPO_PATH,
        scope=SCOPE,
        now=now,
    )
    assert denied.allowed is False
    assert denied.denial_reason is DelegationDenialReason.NOT_FOUND
