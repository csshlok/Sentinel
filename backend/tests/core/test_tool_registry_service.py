"""T0: unit tests for ToolRegistryService -- drift computation and the
exhaustive trust-state decision table."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.contracts.models import JournalEventType, ToolTrustState
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter, row_to_event
from backend.app.core.tool_registry_service import ToolRegistryService


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "tools.sqlite3")
    database.initialize()
    return database


def _make_change(database: Database, change_id) -> None:
    with database.connection(immediate=True) as connection:
        connection.execute(
            "INSERT INTO changes (id, title, intent, repository_path, created_at, updated_at) "
            "VALUES (?, 'T', 'I', 'C:\\repo', '2024-01-01T00:00:00+00:00', "
            "'2024-01-01T00:00:00+00:00')",
            (str(change_id),),
        )


def _executable(tmp_path, name="tool.exe", content=b"v1") -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def test_first_resolve_registers_at_observed(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")
    assert manifest.trust_state is ToolTrustState.OBSERVED
    assert manifest.signature_state.value == "unknown"


def test_resolve_missing_file_raises(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ToolRegistryService(database)
    with pytest.raises(AppError) as excinfo:
        registry.resolve_or_register(str(tmp_path / "does-not-exist.exe"), source="launcher_executable")
    assert excinfo.value.code == "TOOL_EXECUTABLE_UNREADABLE"


def test_repeated_resolve_of_same_bytes_updates_last_seen_only(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ToolRegistryService(database)
    exe = _executable(tmp_path)
    first = registry.resolve_or_register(exe, source="launcher_executable")
    second = registry.resolve_or_register(exe, source="launcher_executable")
    assert first.id == second.id
    assert first.artifact_digest == second.artifact_digest
    assert len(registry.list()) == 1


def test_record_observation_emits_registration_event_once(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    journal = JournalWriter(database)
    registry = ToolRegistryService(database, journal=journal)
    exe = _executable(tmp_path)
    manifest = registry.resolve_or_register(exe, source="launcher_executable")

    registry.record_observation(manifest.id, change_id, None, [], "launch")
    registry.record_observation(manifest.id, change_id, None, [], "launch")

    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_events WHERE change_id = ?", (str(change_id),)
        ).fetchall()
    events = [row_to_event(r) for r in rows]
    registered = [e for e in events if e.event_type is JournalEventType.TOOL_MANIFEST_REGISTERED]
    assert len(registered) == 1
    assert registered[0].subject_id == manifest.id


def test_record_observation_widens_manifest_capabilities(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")
    registry.record_observation(manifest.id, change_id, None, ["github.repo.read"], "launch")
    updated = registry.get(manifest.id)
    assert updated.capabilities == ["github.repo.read"]


# -- drift computation ---------------------------------------------------


def _approve(registry, tool_id, change_id) -> None:
    registry.decide_trust(tool_id, uuid4(), "APPROVE", "exact_version", None, change_id)


def test_no_drift_when_digest_and_capabilities_unchanged(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")
    _approve(registry, manifest.id, change_id)

    report = registry.check_drift(manifest.id)
    assert report.drifted is False
    assert report.changed_fields == []
    assert registry.get(manifest.id).trust_state is ToolTrustState.APPROVED


def test_drift_when_digest_changes(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    journal = JournalWriter(database)
    registry = ToolRegistryService(database, journal=journal)
    exe = _executable(tmp_path, content=b"original-bytes")
    manifest = registry.resolve_or_register(exe, source="launcher_executable")
    _approve(registry, manifest.id, change_id)

    # Simulate a supply-chain swap: same declared tool, different bytes.
    with open(exe, "wb") as handle:
        handle.write(b"swapped-malicious-bytes")
    registry.resolve_or_register(exe, source="launcher_executable")

    report = registry.check_drift(manifest.id, change_id=change_id)
    assert report.drifted is True
    assert report.changed_fields == ["artifact_digest"]
    assert report.prior_trust_state is ToolTrustState.APPROVED
    assert report.new_trust_state is ToolTrustState.PROVISIONAL
    assert registry.get(manifest.id).trust_state is ToolTrustState.PROVISIONAL

    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_events WHERE change_id = ?", (str(change_id),)
        ).fetchall()
    events = [row_to_event(r) for r in rows]
    invalidated = [e for e in events if e.event_type is JournalEventType.TOOL_TRUST_INVALIDATED]
    assert len(invalidated) == 1


def test_drift_when_capabilities_change(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")
    _approve(registry, manifest.id, change_id)

    registry.record_observation(manifest.id, change_id, None, ["github.pr.create"], "launch")

    report = registry.check_drift(manifest.id)
    assert report.drifted is True
    assert report.changed_fields == ["capabilities"]


def test_drift_when_both_digest_and_capabilities_change(tmp_path) -> None:
    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    registry = ToolRegistryService(database)
    exe = _executable(tmp_path, content=b"v1")
    manifest = registry.resolve_or_register(exe, source="launcher_executable")
    _approve(registry, manifest.id, change_id)

    registry.record_observation(manifest.id, change_id, None, ["github.pr.create"], "launch")
    with open(exe, "wb") as handle:
        handle.write(b"v2-different")
    registry.resolve_or_register(exe, source="launcher_executable")

    report = registry.check_drift(manifest.id)
    assert report.drifted is True
    assert set(report.changed_fields) == {"artifact_digest", "capabilities"}


def test_drift_check_without_any_approval_is_never_drifted(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")
    report = registry.check_drift(manifest.id)
    assert report.drifted is False


def test_drift_never_overrides_a_later_explicit_denial(tmp_path) -> None:
    """Reproduces the audit finding: approve -> deny -> digest change ->

    check_drift must not resurrect the stale, now-superseded APPROVE decision
    and flip a denied tool back to PROVISIONAL. Denial is not itself
    something drift loosens -- a human explicitly denying a tool is a
    stronger, later signal than the earlier approval drift would otherwise
    react to.
    """

    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    registry = ToolRegistryService(database)
    exe = _executable(tmp_path, content=b"original-bytes")
    manifest = registry.resolve_or_register(exe, source="launcher_executable")

    _approve(registry, manifest.id, change_id)
    registry.decide_trust(manifest.id, uuid4(), "DENY", "exact_version", "revoked", change_id)
    assert registry.get(manifest.id).trust_state is ToolTrustState.DENIED

    with open(exe, "wb") as handle:
        handle.write(b"swapped-bytes")
    registry.resolve_or_register(exe, source="launcher_executable")

    report = registry.check_drift(manifest.id, change_id=change_id)
    assert report.drifted is False
    assert report.prior_trust_state is ToolTrustState.DENIED
    assert report.new_trust_state is ToolTrustState.DENIED
    assert registry.get(manifest.id).trust_state is ToolTrustState.DENIED


# -- exhaustive trust-state decision table --------------------------------


@pytest.mark.parametrize("decision", ["APPROVE", "DENY"])
@pytest.mark.parametrize("starting_scope", ["exact_version", "publisher_policy"])
def test_decide_trust_transition_table_is_exhaustive(tmp_path, decision, starting_scope) -> None:
    """Every (decision, scope) pair reaches the expected resulting state,
    regardless of the tool's current trust_state -- matching this project's
    exhaustive decision-table coverage standard for security/policy code."""

    database = _database(tmp_path)
    change_id = uuid4()
    _make_change(database, change_id)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")
    assert manifest.trust_state is ToolTrustState.OBSERVED

    decided = registry.decide_trust(
        manifest.id, uuid4(), decision, starting_scope, "test reason", change_id
    )
    expected = ToolTrustState.APPROVED if decision == "APPROVE" else ToolTrustState.DENIED
    assert registry.get(manifest.id).trust_state is expected
    assert decided.decision.value == decision
    assert decided.scope.value == starting_scope


def test_decide_trust_without_change_id_is_recorded_but_not_journaled(tmp_path) -> None:
    """A publisher/version-level policy decision (change_id=None) has no
    Change to scope a journal entry to -- still durably recorded in
    tool_trust_decisions, but absent from every Change's journal."""

    database = _database(tmp_path)
    journal = JournalWriter(database)
    registry = ToolRegistryService(database, journal=journal)
    manifest = registry.resolve_or_register(_executable(tmp_path), source="launcher_executable")

    decided = registry.decide_trust(manifest.id, uuid4(), "APPROVE", "publisher_policy", None, None)
    assert decided.change_id is None
    assert registry.get(manifest.id).trust_state is ToolTrustState.APPROVED

    with database.connection() as connection:
        count = connection.execute("SELECT COUNT(*) AS n FROM journal_events").fetchone()["n"]
    assert count == 0


def test_list_for_change_returns_only_observed_tools(tmp_path) -> None:
    database = _database(tmp_path)
    change_a, change_b = uuid4(), uuid4()
    _make_change(database, change_a)
    _make_change(database, change_b)
    registry = ToolRegistryService(database)
    tool_a = registry.resolve_or_register(_executable(tmp_path, "a.exe", b"a"), source="launcher_executable")
    tool_b = registry.resolve_or_register(_executable(tmp_path, "b.exe", b"b"), source="launcher_executable")
    registry.record_observation(tool_a.id, change_a, None, [], "launch")
    registry.record_observation(tool_b.id, change_b, None, [], "launch")

    for_a = registry.list_for_change(change_a)
    assert [t.id for t in for_a] == [tool_a.id]
