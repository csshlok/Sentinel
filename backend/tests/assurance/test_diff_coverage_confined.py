"""The diff-coverage collector runs in a real confined check box (05-03 task 3).

Real Windows: a real ``sentinel.test.*`` AppContainer profile per measurement
and the snapshot of this interpreter (built once into a throwaway cache).
Positive controls run the same hostile ``conftest.py`` code on the host to show
each attempt would otherwise succeed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.assurance.diff_coverage import collect_diff_coverage
from backend.app.contracts.models import (
    ChangeContract, ChangeView, DiffCoverageRequest, DiffCoverageRule, ReviewState, utc_now,
)
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.git.state import GitStateTracker
from backend.tests.support_kb import make_repo, write

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

if IS_WINDOWS:
    from backend.tests.workspace.conftest import (
        HOSTED_RUNNER_APPCONTAINER_GAP,
        delete_test_profiles,
    )

    pytestmark = [pytestmark, HOSTED_RUNNER_APPCONTAINER_GAP]

GI = "__pycache__/\n.pytest_cache/\n.coverage\n"
CANARY_NAME = "conftest-escaped.txt"


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    root = tmp_path_factory.mktemp("diff-confined") / "check-runtimes"
    try:
        yield root
    finally:
        delete_test_profiles()
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def boxes(tmp_path, cache):
    from backend.app.core.journal import JournalWriter
    from backend.app.execution.check_box import CheckBoxes

    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    manager = CheckBoxes(database, journal=JournalWriter(database),
                         profile_prefix="sentinel.test.", runtime_root=cache)
    yield manager
    manager.sweep(live_run_ids=())


def _change(boxes, root: Path) -> ChangeView:
    now = datetime.now(UTC)
    view = ChangeView(id=uuid4(), title="confined coverage", intent="measure",
                      repository_path=str(root), created_at=utc_now(), updated_at=utc_now(),
                      review_state=ReviewState.MISSING_EVIDENCE)
    ChangeRepository(boxes.repository.database).create(StoredChange(
        id=view.id, title=view.title, intent=view.intent, repository_path=str(root),
        created_at=now, updated_at=now, last_refreshed_at=None, git_summary=None,
        verification=None, contract=ChangeContract()))
    return view


def _measure(boxes, root: Path, files_after: dict[str, str], *, before: dict[str, str]):
    make_repo(root, {".gitignore": GI, **before})
    change = _change(boxes, root)
    tracker = GitStateTracker()
    baseline = tracker.capture(change.id, "baseline", str(root), 1, 1_048_576)
    for name, text in files_after.items():
        write(root, name, text)
    tested = tracker.capture(change.id, "tested", str(root), 1, 1_048_576)
    request = DiffCoverageRequest(
        baseline_checkpoint_id=baseline.id, tested_checkpoint_id=tested.id,
        rule=DiffCoverageRule(required=True, minimum_percent=80,
                              interpreter_path=sys.executable),
    )
    seen: list[tuple[UUID, str]] = []
    result = collect_diff_coverage(change=change, baseline=baseline, tested=tested,
                                   request=request, checks=boxes,
                                   on_check_run=lambda run_id, b: seen.append((run_id, b)))
    return change, result, seen


def _confined_events(boxes, change_id: UUID) -> list[dict]:
    with boxes.repository.database.connection() as connection:
        rows = connection.execute(
            "SELECT payload_json FROM journal_events WHERE change_id = ? AND event_type = ? "
            "ORDER BY seq", (str(change_id), "check.confined_run")).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


BEFORE = {
    "module.py": "def old():\n    return 1\n\n\ndef new():\n    return 1\n",
    "tests/test_module.py": "from module import new, old\n\n\ndef test_old():\n    assert old() == 1\n",
}
AFTER = {
    "module.py": "def old():\n    return 1\n\n\ndef new():\n    return 2\n",
    "tests/test_module.py": ("from module import new, old\n\n\ndef test_old():\n    assert old() == 1\n"
                             "\n\ndef test_new():\n    assert new() == 2\n"),
}


def test_legit_change_passes_inside_a_real_box(tmp_path, boxes) -> None:
    change, result, seen = _measure(boxes, tmp_path / "repo", AFTER, before=BEFORE)
    assert result.collector_status == "COLLECTED", result.reasons
    assert result.checks_passed is True
    assert result.diff_exercised == "PASS", result.reasons
    assert result.freshness == "CURRENT"
    assert result.gate_satisfied is True
    # The command ran the snapshot python with evidence in the box scratch folder.
    assert "check-runtimes" in result.command[0]
    assert any("\\AC\\scratch\\" in part for part in result.command)
    assert len(seen) == 1 and seen[0][1] == "APPCONTAINER"
    events = _confined_events(boxes, change.id)
    assert len(events) == 2  # coverage run + coverage json, in the same box
    assert {event["check_run_id"] for event in events} == {str(seen[0][0])}
    assert all(event["is_appcontainer"] is True and event["job_verified"] is True
               and event["boundary"] == "APPCONTAINER" for event in events)
    assert boxes.repository.get(seen[0][0]).state.value == "CLEANED"


HOSTILE_CONFTEST = '''
import os, pathlib
TARGET = pathlib.Path({target!r})
try:
    (TARGET / {name!r}).write_text("escaped", encoding="utf-8")
    RESULT = "allowed"
except Exception as exc:
    RESULT = "denied:" + type(exc).__name__
pathlib.Path("conftest-result.txt").write_text(RESULT, encoding="utf-8")
'''


def test_hostile_conftest_cannot_write_the_user_repository(tmp_path, boxes) -> None:
    root = tmp_path / "repo"
    conftest = HOSTILE_CONFTEST.format(target=str(root), name=CANARY_NAME)

    # Positive control: the same conftest code at user authority reaches the repository.
    control_dir = tmp_path / "control"
    control_dir.mkdir()
    (control_dir / "probe.py").write_text(conftest, encoding="utf-8")
    root.mkdir()
    subprocess.run([sys.executable, "probe.py"], cwd=control_dir, check=True, timeout=60)
    assert (control_dir / "conftest-result.txt").read_text(encoding="utf-8") == "allowed"
    assert (root / CANARY_NAME).exists()
    (root / CANARY_NAME).unlink()

    after = {**AFTER, "conftest.py": conftest}
    change, result, seen = _measure(boxes, root, after, before=BEFORE)
    assert not (root / CANARY_NAME).exists()
    assert not (root / "conftest-result.txt").exists()  # it was written in the box tree only
    assert seen and seen[0][1] == "APPCONTAINER"
    # The escape attempt never produces a PASS: the changed conftest.py is unmeasured
    # configuration, so the verdict is at most UNKNOWN.
    assert result.diff_exercised != "PASS"
    assert result.gate_satisfied is False
    assert result.freshness == "CURRENT"
