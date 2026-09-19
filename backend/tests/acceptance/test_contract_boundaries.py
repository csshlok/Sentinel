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
from backend.app.main import create_app


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


def test_no_removed_subsystem_endpoints_are_exposed() -> None:
    """The four approved cuts (`OVERALL_CONTEXT.md`) must never surface a
    route: no event/effect journal, process supervisor, filesystem
    tracker/snapshot, tool registry, or replay endpoint, at any path depth.
    Guards `[SD]`'s own composition in `main.py`/`router.py` against
    accidentally reintroducing one of these as a future route is added."""

    app = create_app()
    paths = app.openapi()["paths"].keys()

    forbidden_fragments = (
        "/events",
        "/effects",
        "/replay",
        "/tools",
        "/processes",
        "/snapshots",
    )
    offending = [
        path
        for path in paths
        for fragment in forbidden_fragments
        if fragment in path
    ]
    assert offending == []


def test_expected_route_families_are_present() -> None:
    """Complements the forbidden-route check above: a route family
    disappearing silently (e.g. a refactor that drops `include_router`
    for one group) is just as much a contract break as a forbidden one
    appearing, so both directions are asserted."""

    app = create_app()
    paths = set(app.openapi()["paths"].keys())

    expected_prefixes = (
        "/api/v1/health",
        "/api/v1/capabilities",
        "/api/v1/changes",
        "/api/v1/actors",
        "/api/v1/delegations",
        "/api/v1/providers/github",
    )
    for prefix in expected_prefixes:
        assert any(path.startswith(prefix) for path in paths), prefix
    assert any(
        path.startswith("/api/v1/changes/") and path.endswith("/outcomes")
        for path in paths
    )
    assert any(
        path.startswith("/api/v1/changes/") and path.endswith("/recovery")
        for path in paths
    )
    assert any(
        path.startswith("/api/v1/changes/") and path.endswith("/passport")
        for path in paths
    )
