"""Plan 02-03: AgentRun.execution_boundary comes only from observed launch facts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import (AgentAttachRequest, AgentLaunchRequest,
                                          AgentRunStatus, ExecutionBoundary)
from backend.app.execution import launcher as module
from backend.app.execution.appcontainer import AppContainerFacts, CAPABILITY_SIDS
from backend.app.execution.launcher import AgentLauncher, appcontainer_boundary
from backend.app.execution.process_supervisor import IS_WINDOWS

CHANGE = uuid4()


def _facts(**overrides) -> AppContainerFacts:
    values = dict(profile_name="sentinel.w.abc", package_sid="S-1-15-2-1-2-3-4-5-6-7",
                  is_appcontainer=True, integrity_rid=0x1000,
                  capability_sids=(CAPABILITY_SIDS["internetClient"],), job_verified=True,
                  verified_at=datetime(2026, 10, 8, tzinfo=UTC))
    values.update(overrides)
    return AppContainerFacts(**values)


def test_verified_facts_become_an_appcontainer_boundary() -> None:
    boundary = appcontainer_boundary(_facts(), working_directory=r"C:\ac\ws",
                                     workspace_drive="Z:")
    assert boundary == ExecutionBoundary(
        kind="APPCONTAINER", profile="sentinel.w.abc", capabilities=["internetClient"],
        package_sid="S-1-15-2-1-2-3-4-5-6-7", integrity_rid="0x1000", job_verified=True,
        verified_at=datetime(2026, 10, 8, tzinfo=UTC), working_directory=r"C:\ac\ws",
        workspace_drive="Z:")


@pytest.mark.parametrize("override", [{"is_appcontainer": False}, {"job_verified": False}])
def test_unverified_facts_record_no_boundary(override) -> None:
    assert appcontainer_boundary(_facts(**override), working_directory=None,
                                 workspace_drive=None) is None
    assert appcontainer_boundary(None, working_directory=None, workspace_drive=None) is None


def test_attached_run_records_no_boundary_kind() -> None:
    run = AgentLauncher().attach(CHANGE, AgentAttachRequest(adapter="generic",
                                                            external_run_id="ext-1"))
    assert run.execution_boundary == ExecutionBoundary(kind="NONE", profile="generic")


@pytest.mark.skipif(not IS_WINDOWS, reason="the restricted token is Windows-only")
def test_a_real_restricted_run_records_restricted_token(tmp_path: Path) -> None:
    run = AgentLauncher().launch(CHANGE, str(tmp_path), AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", "print('hi')"],
        timeout_seconds=30), 10_000)
    assert run.status is AgentRunStatus.PASSED, run.limitations
    boundary = run.execution_boundary
    assert boundary is not None and boundary.kind == "RESTRICTED_TOKEN"
    assert boundary.job_verified is True and boundary.profile == "generic"
    assert Path(boundary.working_directory) == tmp_path.resolve()
    assert boundary.package_sid is None and boundary.capabilities == []


def test_a_launch_that_never_spawns_records_no_boundary(tmp_path: Path, monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr(module, "spawn_restricted_supervised", refuse)
    run = AgentLauncher().launch(CHANGE, str(tmp_path), AgentLaunchRequest(
        adapter="generic", executable="python", args=["-c", "print('hi')"],
        timeout_seconds=30), 10_000)
    assert run.status is AgentRunStatus.ERROR
    assert run.execution_boundary is None
