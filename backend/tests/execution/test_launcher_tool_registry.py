"""T1: real launcher tests for AgentLauncherPort tool-trust enforcement (B.6).

Uses a real `ToolRegistryService` over a real SQLite database and a real
`AgentLauncher` -- no fakes for the enforcement path itself, matching this
codebase's real-boundary testing bar.
"""

from __future__ import annotations

import os
import sys
from uuid import UUID, uuid4

import pytest

from backend.app.contracts.models import (
    AgentLaunchRequest, AgentRunStatus, JournalEventType, ToolTrustState,
)
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter, row_to_event
from backend.app.core.tool_registry_service import ToolRegistryService
from backend.app.execution.launcher import AgentLauncher

CHANGE = uuid4()


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "reg.sqlite3")
    database.initialize()
    return database


def _make_change(database: Database, change_id: UUID) -> None:
    with database.connection(immediate=True) as connection:
        connection.execute(
            "INSERT INTO changes (id, title, intent, repository_path, created_at, updated_at) "
            "VALUES (?, 'T', 'I', 'C:\\repo', '2024-01-01T00:00:00+00:00', "
            "'2024-01-01T00:00:00+00:00')",
            (str(change_id),),
        )


def _events(database: Database, change_id: UUID) -> list:
    with database.connection() as connection:
        rows = connection.execute(
            "SELECT * FROM journal_events WHERE change_id = ? ORDER BY seq", (str(change_id),)
        ).fetchall()
    return [row_to_event(row) for row in rows]


def _python_request(code: str) -> AgentLaunchRequest:
    return AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", code], timeout_seconds=10
    )


def test_unknown_tool_auto_registers_as_observed_and_is_journaled(tmp_path) -> None:
    database = _database(tmp_path)
    _make_change(database, CHANGE)
    journal = JournalWriter(database)
    registry = ToolRegistryService(database, journal=journal)
    launcher = AgentLauncher(tool_registry=registry)

    run = launcher.launch(CHANGE, str(tmp_path), _python_request("print(1)"), 10_000)
    assert run.status is AgentRunStatus.PASSED

    manifests = registry.list()
    assert len(manifests) == 1
    assert manifests[0].trust_state is ToolTrustState.OBSERVED
    assert manifests[0].artifact_digest  # a real sha256 of sys.executable's bytes

    events = _events(database, CHANGE)
    registered = [e for e in events if e.event_type is JournalEventType.TOOL_MANIFEST_REGISTERED]
    assert len(registered) == 1
    assert registered[0].subject_id == manifests[0].id


def test_denied_tool_blocks_launch_with_no_process_started(tmp_path) -> None:
    database = _database(tmp_path)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(sys.executable, source="launcher_executable")
    registry.decide_trust(manifest.id, uuid4(), "DENY", "exact_version", "not allowed", None)

    launcher = AgentLauncher(tool_registry=registry)
    marker = tmp_path / "marker.txt"
    code = f"open(r'{marker}', 'w').write('ran')"

    with pytest.raises(AppError) as excinfo:
        launcher.launch(CHANGE, str(tmp_path), _python_request(code), 10_000)
    assert excinfo.value.code == "POLICY_DENIED"
    assert not marker.exists()

    # A second attempt is refused the same way: the DENY decision is durable.
    with pytest.raises(AppError) as excinfo_2:
        launcher.launch(CHANGE, str(tmp_path), _python_request(code), 10_000)
    assert excinfo_2.value.code == "POLICY_DENIED"
    assert not marker.exists()
    assert registry.get(manifest.id).trust_state is ToolTrustState.DENIED


def test_approved_then_denied_tool_second_launch_is_refused(tmp_path) -> None:
    """First launch of a previously-unseen tool auto-registers and is not
    blocked; an explicit DENY decision then refuses every subsequent launch
    attempt of that exact tool."""

    database = _database(tmp_path)
    _make_change(database, CHANGE)
    journal = JournalWriter(database)
    registry = ToolRegistryService(database, journal=journal)
    launcher = AgentLauncher(tool_registry=registry)

    first = launcher.launch(CHANGE, str(tmp_path), _python_request("print(1)"), 10_000)
    assert first.status is AgentRunStatus.PASSED
    manifest = registry.list()[0]
    assert manifest.trust_state is ToolTrustState.OBSERVED

    registry.decide_trust(manifest.id, uuid4(), "DENY", "exact_version", "reconsidered", CHANGE)

    with pytest.raises(AppError) as excinfo:
        launcher.launch(CHANGE, str(tmp_path), _python_request("print(2)"), 10_000)
    assert excinfo.value.code == "POLICY_DENIED"


def test_supply_chain_digest_swap_invalidates_approved_trust(tmp_path, monkeypatch) -> None:
    """Adversarial supply-chain simulation: the same declared tool name
    resolves to different bytes on a second launch. This must be detected
    as drift and the prior APPROVED trust invalidated -- through the real
    launcher, not just the unit-level ToolRegistryService (already covered
    in test_tool_registry_service.py)."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tool_path = bin_dir / "mytool.exe"
    tool_path.write_bytes(b"original-tool-bytes")
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    database = _database(tmp_path)
    _make_change(database, CHANGE)
    journal = JournalWriter(database)
    registry = ToolRegistryService(database, journal=journal)
    launcher = AgentLauncher(frozenset({"mytool"}), tool_registry=registry)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    request = AgentLaunchRequest(adapter="generic", executable="mytool", args=[], timeout_seconds=5)

    launcher.launch(CHANGE, str(repo_root), request, 1000)
    manifest = registry.list()[0]
    original_digest = manifest.artifact_digest
    registry.decide_trust(manifest.id, uuid4(), "APPROVE", "exact_version", "reviewed", CHANGE)
    assert registry.get(manifest.id).trust_state is ToolTrustState.APPROVED

    tool_path.write_bytes(b"swapped-malicious-bytes")
    launcher.launch(CHANGE, str(repo_root), request, 1000)

    updated = registry.get(manifest.id)
    assert updated.artifact_digest != original_digest
    assert updated.trust_state is ToolTrustState.PROVISIONAL

    events = _events(database, CHANGE)
    invalidated = [e for e in events if e.event_type is JournalEventType.TOOL_TRUST_INVALIDATED]
    assert len(invalidated) == 1


def test_no_tool_registry_configured_behaves_exactly_as_before(tmp_path) -> None:
    """Backward compatibility: `tool_registry=None` (the default) means
    launch behaves exactly as it did before this feature existed."""

    launcher = AgentLauncher()
    run = launcher.launch(CHANGE, str(tmp_path), _python_request("print('ok')"), 10_000)
    assert run.status is AgentRunStatus.PASSED
    assert run.stdout.strip() == "ok"


def test_attach_never_checks_tool_trust_no_executable_identity_exists(tmp_path) -> None:
    """attach() has no executable path to identify a tool from; it must not
    fabricate one. A DENIED decision against an unrelated tool must never
    affect attach, since attach never resolves any tool at all."""

    from backend.app.contracts.models import AgentAttachRequest

    database = _database(tmp_path)
    registry = ToolRegistryService(database)
    manifest = registry.resolve_or_register(sys.executable, source="launcher_executable")
    registry.decide_trust(manifest.id, uuid4(), "DENY", "exact_version", "unrelated", None)

    launcher = AgentLauncher(tool_registry=registry)
    run = launcher.attach(CHANGE, AgentAttachRequest(adapter="claude", external_run_id="ext-1"))
    assert run.status.value == "ATTACHED"
