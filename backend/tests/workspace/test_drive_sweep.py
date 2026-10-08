"""Quick 261008-9pq: the sweep removes a crashed run's workspace drive, and only that one."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.execution.dos_drive import map_drive, query_drive, unmap_drive
from backend.app.execution.process_supervisor import IS_WINDOWS

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")


def test_sweep_removes_an_interrupted_runs_drive_but_not_a_live_one(
    workspace_manager, user_repo: Path, tmp_path: Path,
) -> None:
    crashed_run, live_run = uuid4(), uuid4()
    crashed = workspace_manager.ensure(uuid4(), str(user_repo), run_id=crashed_run)
    # A second workspace from the same repository content, with a run that is still live.
    live = workspace_manager.ensure(uuid4(), str(user_repo), run_id=live_run)
    crashed_letter = map_drive(crashed.container_path)
    live_letter = map_drive(live.container_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    unrelated_letter = map_drive(unrelated)
    try:
        workspace_manager.sweep(live_run_ids={live_run})
        assert query_drive(crashed_letter) == []
        assert query_drive(live_letter), "a live run's drive must survive the sweep"
        assert query_drive(unrelated_letter), "a mapping Sentinel did not record is untouched"
    finally:
        unmap_drive(crashed_letter, crashed.container_path)
        unmap_drive(live_letter, live.container_path)
        unmap_drive(unrelated_letter, unrelated)
