"""Plan 02-02 (D3): an unsupported Windows is refused loudly on both AppContainer paths."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest
from backend.app.core.capabilities import build_capabilities
from backend.app.core.errors import AppError
from backend.app.execution import platform_probe
from backend.app.execution.platform_probe import PlatformSupport, require_appcontainer_platform

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AppContainers are Windows-only")

SERVER = PlatformSupport(False, "a box could not open the NUL device (exit 1)", 3)


@pytest.mark.real_platform_probe
def test_the_real_probe_matches_this_host() -> None:
    support = platform_probe.platform_support(refresh=True)
    if os.environ.get("GITHUB_ACTIONS") == "true" or platform_probe.product_type() != 1:
        # Hosted runners are Windows Server: refused, with a reason.
        assert support.supported is False and support.reason
    else:
        assert support == PlatformSupport(True, None, 1)
    leftover = [name for name in os.listdir(Path(os.environ["LOCALAPPDATA"]) / "Packages")
                if name.startswith(platform_probe.PROBE_PREFIX)]
    assert leftover == []


@pytest.mark.real_platform_probe
def test_require_raises_a_stable_code(monkeypatch) -> None:
    monkeypatch.setattr(platform_probe, "_cached", SERVER)
    with pytest.raises(AppError) as raised:
        require_appcontainer_platform()
    assert raised.value.code == "APPCONTAINER_PLATFORM_UNSUPPORTED"
    assert raised.value.status_code == 503
    assert raised.value.details == {"reason": SERVER.reason, "product_type": 3}


@pytest.mark.real_platform_probe
def test_claude_launch_is_refused_before_any_workspace(monkeypatch, tmp_path: Path) -> None:
    from backend.app.execution import launcher as module
    from backend.app.execution.launcher import AgentLauncher

    monkeypatch.setattr(platform_probe, "_cached", SERVER)

    class NoWorkspace:
        def ensure(self, *args, **kwargs):
            raise AssertionError("no workspace may be created on an unsupported platform")

    def no_spawn(*args, **kwargs):
        raise AssertionError("nothing may be spawned on an unsupported platform")

    monkeypatch.setattr(module, "spawn_restricted_supervised", no_spawn)
    monkeypatch.setattr(module, "spawn_appcontainer_supervised", no_spawn)
    with pytest.raises(AppError) as raised:
        AgentLauncher(workspaces=NoWorkspace()).launch(
            uuid4(), str(tmp_path), AgentLaunchRequest(adapter="claude", executable="claude"),
            10_000)
    assert raised.value.code == "APPCONTAINER_PLATFORM_UNSUPPORTED"


@pytest.mark.real_platform_probe
def test_check_box_open_is_refused(monkeypatch, tmp_path: Path) -> None:
    from backend.app.core.database import Database
    from backend.app.execution.check_box import BoxRuntime, CheckBoxes

    monkeypatch.setattr(platform_probe, "_cached", SERVER)
    database = Database(tmp_path / "state.sqlite3")
    database.initialize()
    boxes = CheckBoxes(database, runtime_root=tmp_path / "runtimes")
    runtime = BoxRuntime.__new__(BoxRuntime)
    with pytest.raises(AppError) as raised:
        boxes.open(uuid4(), tmp_path, runtime)
    assert raised.value.code == "APPCONTAINER_PLATFORM_UNSUPPORTED"


def test_the_capability_report_names_the_platform_result() -> None:
    supported = build_capabilities(set(), platform=PlatformSupport(True, None, 1))
    refused = build_capabilities(set(), platform=SERVER)
    item = next(item for item in supported.items if item.id == "appcontainer_boundary")
    assert item.state.value == "AVAILABLE" and item.reason is None
    item = next(item for item in refused.items if item.id == "appcontainer_boundary")
    assert item.state.value == "UNSUPPORTED" and item.reason == SERVER.reason
