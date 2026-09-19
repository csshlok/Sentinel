from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.identity.models import Actor, ActorKind, Delegation


def _now() -> datetime:
    return datetime.now(UTC)


def test_actor_rejects_undeclared_fields() -> None:
    with pytest.raises(ValidationError):
        Actor(
            id=uuid4(),
            kind=ActorKind.HUMAN,
            display_name="Aditya",
            created_at=_now(),
            updated_at=_now(),
            extra="not allowed",  # type: ignore[call-arg]
        )


def test_delegation_requires_at_least_one_scope() -> None:
    with pytest.raises(ValidationError):
        Delegation(
            id=uuid4(),
            grantor_id=uuid4(),
            grantee_id=uuid4(),
            change_id=uuid4(),
            repository_path="C:\\work\\repo",
            scopes=[],
            issued_at=_now(),
            expires_at=_now() + timedelta(hours=1),
        )


def test_delegation_expiry_must_be_after_issued_at() -> None:
    now = _now()
    with pytest.raises(ValidationError):
        Delegation(
            id=uuid4(),
            grantor_id=uuid4(),
            grantee_id=uuid4(),
            change_id=uuid4(),
            repository_path="C:\\work\\repo",
            scopes=["github.repo.read"],
            issued_at=now,
            expires_at=now,
        )


def test_delegation_uses_cannot_exceed_use_limit() -> None:
    now = _now()
    with pytest.raises(ValidationError):
        Delegation(
            id=uuid4(),
            grantor_id=uuid4(),
            grantee_id=uuid4(),
            change_id=uuid4(),
            repository_path="C:\\work\\repo",
            scopes=["github.repo.read"],
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            use_limit=1,
            uses=2,
        )
