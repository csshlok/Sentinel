from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.contracts.models import (
    ChangeContract,
    Delegation,
    EnvironmentFact,
)


def test_change_contract_rejects_duplicate_policy_values() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        ChangeContract(allowed_paths=["src/**", "src/**"])


def test_sensitive_environment_fact_cannot_contain_raw_value() -> None:
    with pytest.raises(ValidationError, match="sensitive"):
        EnvironmentFact(key="TOKEN", value="known-secret", sensitive=True)


def test_delegation_requires_a_valid_time_window_and_use_count() -> None:
    now = datetime.now(UTC)
    base = {
        "id": uuid4(),
        "grantor_id": uuid4(),
        "grantee_id": uuid4(),
        "change_id": uuid4(),
        "repository_path": "C:\\repo",
        "scopes": ["github:pull-request:create"],
        "issued_at": now,
        "expires_at": now + timedelta(minutes=5),
    }
    assert Delegation(**base).uses == 0
    with pytest.raises(ValidationError, match="expires_at"):
        Delegation(**{**base, "expires_at": now})
    with pytest.raises(ValidationError, match="use_limit"):
        Delegation(**{**base, "use_limit": 1, "uses": 2})
