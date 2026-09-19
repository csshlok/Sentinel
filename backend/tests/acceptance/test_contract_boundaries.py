from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.contracts.models import (
    ChangeContract,
    Delegation,
    EnvironmentFact,
)
from backend.app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]


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
    """The two subsystems that remain cut (`AGENT_COORDINATION.md`: process
    supervisor, filesystem tracker) must never surface a route, at any path
    depth. The event/effect journal, replay, and tool registry are no longer
    forbidden here -- see `EVENT_JOURNAL_AND_TOOL_REGISTRY_PLAN.md` -- and
    are asserted present instead, by
    `test_journal_and_tool_registry_routes_are_present` below. Guards
    `[SD]`'s own composition in `main.py`/`router.py` against reintroducing
    a still-cut subsystem as a future route is added."""

    app = create_app()
    paths = app.openapi()["paths"].keys()

    forbidden_fragments = (
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


def test_journal_and_tool_registry_routes_are_present() -> None:
    """Complements the forbidden-route check above: the bounded journal/
    replay/tool-registry capabilities this reversal adds must actually be
    wired, not silently dropped by a future refactor."""

    app = create_app()
    paths = set(app.openapi()["paths"].keys())

    assert any(
        path.startswith("/api/v1/changes/") and path.endswith("/events")
        for path in paths
    )
    assert any(
        path.startswith("/api/v1/changes/") and path.endswith("/replay")
        for path in paths
    )
    assert "/api/v1/changes/{change_id}/replay/verify" in paths
    assert "/api/v1/changes/{change_id}/replay/export" in paths


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


def test_frozen_openapi_snapshot_matches_the_live_app() -> None:
    """`openapi.json` at the repo root is the frozen contract plan section 5/8
    requires for a later browser UI phase. This does not check the file into
    a drifted state silently: if a route or model changes, regenerate it with

        python -c "import json; from backend.app.main import create_app; \
            json.dump(create_app().openapi(), open('openapi.json', 'w'), indent=2, sort_keys=True)"

    and commit the result alongside the change that caused it."""

    snapshot_path = REPO_ROOT / "openapi.json"
    assert snapshot_path.is_file(), "openapi.json is missing from the repo root."
    on_disk = json.loads(snapshot_path.read_text(encoding="utf-8"))
    live = create_app().openapi()
    assert on_disk == live, (
        "openapi.json is stale. Regenerate it (see this test's docstring) and "
        "commit it in the same change."
    )
