"""Plan 02-02 (SC2): every AppContainer setup stage fails loud, with its own stable code.

One row per stage of the claude launch. Each failure must leave: a stable
code the operator can see, no process resumed, the restricted-token launcher
never called, no boundary or authority claimed, the workspace lease released
and every staged credential revoked. Adding a stage means adding a row.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentRunStatus
from backend.app.core.errors import AppError
from backend.app.credentials.errors import agent_credential_staging_failed
from backend.app.execution import launcher as module
from backend.app.execution import platform_probe
from backend.app.execution.agent_staging import staged_home_failed, tool_snapshot_tampered
from backend.app.execution.appcontainer import job_required, launch_failed, verification_failed
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.tests.execution.test_launcher_appcontainer import box, claude  # noqa: F401 - fixture

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="the AppContainer path is Windows-only")

CHANGE = uuid4()


def _raise(error):
    def fail(*args, **kwargs):
        raise error
    return fail


# stage -> (code, how to inject, raised before a run exists?)
STAGES = {
    "platform": ("APPCONTAINER_PLATFORM_UNSUPPORTED", "platform", True),
    "workspace": ("WORKSPACE_SOURCE_DIRTY", "workspace", True),
    "tool_snapshot": ("AGENT_TOOL_SNAPSHOT_TAMPERED",
                      ("ensure_tool_snapshot", tool_snapshot_tampered()), False),
    "staged_home": ("AGENT_STAGED_HOME_FAILED",
                    ("rebuild_staged_home", staged_home_failed("injected")), False),
    "credential": ("AGENT_CREDENTIAL_STAGING_FAILED", "credential", False),
    "drive": ("AGENT_WORKSPACE_DRIVE_UNAVAILABLE", "drive", False),
    "job": ("APPCONTAINER_JOB_REQUIRED",
            ("spawn_appcontainer_supervised", job_required("create")), False),
    "create_process": ("APPCONTAINER_LAUNCH_FAILED",
                       ("spawn_appcontainer_supervised",
                        launch_failed("CreateProcessW failed (Windows error 5)")), False),
    "token_verification": ("APPCONTAINER_VERIFICATION_FAILED",
                           ("spawn_appcontainer_supervised", verification_failed("integrity")),
                           False),
}


def test_every_stage_has_a_distinct_code() -> None:
    codes = [code for code, _how, _raised in STAGES.values()]
    assert len(codes) == len(set(codes))


@pytest.mark.parametrize("stage", sorted(STAGES))
def test_a_failed_stage_is_loud_and_leaves_no_weaker_run(box, monkeypatch, stage):  # noqa: F811
    code, how, raised_before_run = STAGES[stage]
    if how == "platform":
        monkeypatch.setattr(platform_probe, "_cached",
                            platform_probe.PlatformSupport(False, "injected", 3))
    elif how == "workspace":
        box["provider"].error = AppError("WORKSPACE_SOURCE_DIRTY", "dirty", status_code=409)
    elif how == "credential":
        monkeypatch.setattr(box["stager"], "stage_agent_credential",
                            _raise(agent_credential_staging_failed("injected")))
    elif how == "drive":
        box["drives"]["map_error"] = OSError("No free drive letter is available")
    else:
        name, error = how
        monkeypatch.setattr(module, name, _raise(error))

    if raised_before_run:
        with pytest.raises(AppError) as caught:
            box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
        assert caught.value.code == code
        assert box["provider"].finished == []
    else:
        run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
        assert run.status is AgentRunStatus.ERROR
        assert any(f"({code})" in text for text in run.limitations), run.limitations
        assert run.restricted_token_applied is False
        assert run.authority_reduction is None and run.execution_boundary is None
        (finished,) = box["provider"].finished
        assert finished["status"] == "ERROR" and finished["facts"] is None
    assert box["restricted_calls"] == []
    assert len(box["stager"].revoked) == len(box["stager"].staged)
    assert len(box["drives"]["unmapped"]) == len(box["drives"]["mapped"])
