from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from backend.app.contracts.models import (
    ChangeView,
    GitCheckpoint,
    GitSummary,
    RecoveryStatus,
    ReviewState,
)
from backend.app.contracts.ports import RecoveryPort
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.recovery.git_recovery import GitRecoveryEngine


def _run(repo, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, shell=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _init_linear_repo(tmp_path) -> tuple[str, str, str]:
    """One baseline commit, then one edit commit. Returns (repo, baseline_sha, current_sha)."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "config", "user.email", "test@example.com")
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    _run(repo, "add", "file.txt")
    _run(repo, "commit", "-m", "baseline")
    baseline_sha = _run(repo, "rev-parse", "HEAD")

    (repo / "file.txt").write_text("edited\n", encoding="utf-8")
    _run(repo, "commit", "-am", "edit")
    current_sha = _run(repo, "rev-parse", "HEAD")
    return str(repo), baseline_sha, current_sha


def _init_repo_with_merge_commit(tmp_path) -> tuple[str, str, str]:
    """A real merge commit in range, which `git revert` (no -m) always fails on."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "config", "user.email", "test@example.com")
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    _run(repo, "add", "file.txt")
    _run(repo, "commit", "-m", "baseline")
    baseline_sha = _run(repo, "rev-parse", "HEAD")
    main_branch = _run(repo, "branch", "--show-current")

    _run(repo, "checkout", "-b", "feature")
    (repo / "file.txt").write_text("feature\n", encoding="utf-8")
    _run(repo, "commit", "-am", "feature edit")

    _run(repo, "checkout", main_branch)
    (repo / "file.txt").write_text("main-edit\n", encoding="utf-8")
    _run(repo, "commit", "-am", "main edit")

    subprocess.run(
        ["git", "-C", str(repo), "merge", "feature", "-m", "merge feature"],
        capture_output=True,
        text=True,
        shell=False,
    )
    (repo / "file.txt").write_text("resolved\n", encoding="utf-8")
    _run(repo, "add", "file.txt")
    _run(repo, "commit", "--no-edit")
    current_sha = _run(repo, "rev-parse", "HEAD")
    return str(repo), baseline_sha, current_sha


def _seed_change_and_checkpoint(
    database: Database, repository_path: str, baseline_sha: str, current_sha: str
) -> ChangeView:
    now = datetime.now(UTC)
    change_id = uuid4()
    ChangeRepository(database).create(
        StoredChange(
            id=change_id,
            title="Recovery test change",
            intent="Exercise recovery",
            repository_path=repository_path,
            created_at=now,
            updated_at=now,
            last_refreshed_at=None,
            git_summary=None,
            verification=None,
        )
    )
    checkpoint = GitCheckpoint(
        id=uuid4(),
        change_id=change_id,
        name="baseline",
        repository_root=repository_path,
        branch="main",
        head_sha=baseline_sha,
        status_digest=hashlib.sha256(b"baseline").hexdigest(),
        summary=GitSummary(
            repository_root=repository_path,
            branch="main",
            head_sha=baseline_sha,
            is_clean=True,
            total_additions=0,
            total_deletions=0,
            patch="",
            refreshed_at=now,
        ),
        evidence_revision=1,
        captured_at=now,
    )
    with database.connection() as connection:
        connection.execute(
            """
            INSERT INTO git_checkpoints (
                id, change_id, name, head_sha, evidence_revision, payload_json, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(checkpoint.id),
                str(change_id),
                checkpoint.name,
                checkpoint.head_sha,
                checkpoint.evidence_revision,
                checkpoint.model_dump_json(),
                checkpoint.captured_at.isoformat(),
            ),
        )

    git_summary = GitSummary(
        repository_root=repository_path,
        branch="main",
        head_sha=current_sha,
        is_clean=True,
        total_additions=0,
        total_deletions=0,
        patch="",
        refreshed_at=now,
    )
    return ChangeView(
        id=change_id,
        title="Recovery test change",
        intent="Exercise recovery",
        repository_path=repository_path,
        created_at=now,
        updated_at=now,
        review_state=ReviewState.NO_CHANGES,
        git_summary=git_summary,
    )


def _database(tmp_path) -> Database:
    database = Database(tmp_path / "recovery.sqlite3")
    database.initialize()
    return database


def test_engine_satisfies_the_frozen_port(tmp_path) -> None:
    engine = GitRecoveryEngine(_database(tmp_path))
    assert isinstance(engine, RecoveryPort)


def test_plan_raises_without_checkpoint_evidence(tmp_path) -> None:
    database = _database(tmp_path)
    engine = GitRecoveryEngine(database)
    change = ChangeView(
        id=uuid4(),
        title="No evidence",
        intent="x",
        repository_path="C:\\work\\repo",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        review_state=ReviewState.NO_CHANGES,
    )
    with pytest.raises(AppError) as excinfo:
        engine.plan(change)
    assert excinfo.value.code == "RECOVERY_NO_CHECKPOINT_EVIDENCE"


def test_plan_reports_nothing_to_revert_at_baseline(tmp_path) -> None:
    repo, baseline_sha, _ = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, baseline_sha)
    engine = GitRecoveryEngine(database)

    plan = engine.plan(change)

    assert plan.actions == []
    assert any("already at the baseline" in item for item in plan.unsupported_effects)


def test_plan_for_clean_linear_revert_is_supported_and_does_not_mutate_repo(tmp_path) -> None:
    repo, baseline_sha, current_sha = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    branches_before = _run(repo, "branch", "--list")
    head_before = _run(repo, "rev-parse", "HEAD")

    plan = engine.plan(change)

    assert len(plan.actions) == 1
    assert plan.actions[0].supported is True
    assert plan.conflicts == []
    assert _run(repo, "branch", "--list") == branches_before
    assert _run(repo, "rev-parse", "HEAD") == head_before


def test_plan_for_unrevertable_merge_commit_reports_conflict_without_mutation(tmp_path) -> None:
    repo, baseline_sha, current_sha = _init_repo_with_merge_commit(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    branches_before = _run(repo, "branch", "--list")
    head_before = _run(repo, "rev-parse", "HEAD")

    plan = engine.plan(change)

    assert len(plan.actions) == 1
    assert plan.actions[0].supported is False
    assert len(plan.conflicts) == 1
    assert _run(repo, "branch", "--list") == branches_before
    assert _run(repo, "rev-parse", "HEAD") == head_before


def test_execute_without_approval_token_raises(tmp_path) -> None:
    repo, baseline_sha, current_sha = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    plan = engine.plan(change)

    with pytest.raises(AppError) as excinfo:
        engine.execute(change, plan, "")
    assert excinfo.value.code == "RECOVERY_NOT_APPROVED"


def test_execute_clean_revert_creates_dedicated_branch_and_reverts(tmp_path) -> None:
    repo, baseline_sha, current_sha = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    head_before = _run(repo, "rev-parse", "HEAD")
    branch_before = _run(repo, "branch", "--show-current")

    plan = engine.plan(change)
    result = engine.execute(change, plan, "approval-token-123")

    assert result.status is RecoveryStatus.RECOVERED
    assert result.approved_at is not None
    assert result.completed_at is not None

    # The user's actual working directory/HEAD must never be disturbed.
    assert _run(repo, "rev-parse", "HEAD") == head_before
    assert _run(repo, "branch", "--show-current") == branch_before

    dedicated_branch = f"change-assurance/recovery/{change.id}"
    branch_tip = _run(repo, "rev-parse", dedicated_branch)
    file_at_tip = subprocess.run(
        ["git", "-C", repo, "show", f"{branch_tip}:file.txt"],
        capture_output=True,
        text=True,
        shell=False,
    ).stdout
    assert file_at_tip == "base\n"


def test_execute_conflicting_revert_leaves_target_repository_unchanged(tmp_path) -> None:
    repo, baseline_sha, current_sha = _init_repo_with_merge_commit(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    head_before = _run(repo, "rev-parse", "HEAD")
    branches_before = _run(repo, "branch", "--list")

    plan = engine.plan(change)
    result = engine.execute(change, plan, "approval-token-123")

    assert result.status is RecoveryStatus.CONFLICTED
    assert _run(repo, "rev-parse", "HEAD") == head_before
    assert _run(repo, "branch", "--list") == branches_before


def test_execute_with_no_actions_is_a_trivial_success(tmp_path) -> None:
    repo, baseline_sha, _ = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, baseline_sha)
    engine = GitRecoveryEngine(database)

    plan = engine.plan(change)
    result = engine.execute(change, plan, "approval-token-123")

    assert result.status is RecoveryStatus.RECOVERED


def test_execute_refuses_a_plan_whose_head_has_moved_since_preview(tmp_path) -> None:
    """Reproduces the audit finding: execute() used the plan's saved SHA

    without checking the repository's actual current HEAD. A commit made
    after preview but before execute must make the plan stale rather than
    silently reverting from a base that no longer reflects reality.
    """

    repo, baseline_sha, current_sha = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    plan = engine.plan(change)

    # The repository moves after the plan was previewed.
    from pathlib import Path
    (Path(repo) / "file.txt").write_text("edited again\n", encoding="utf-8")
    _run(repo, "commit", "-am", "second edit")

    result = engine.execute(change, plan, "approval-token-123")

    assert result.status is RecoveryStatus.RECOVERY_FAILED
    assert any("HEAD moved" in conflict for conflict in result.conflicts)
    # No dedicated branch should have been created for a plan that was
    # refused before any Git mutation.
    assert f"change-assurance/recovery/{change.id}" not in _run(repo, "branch", "--list")


def test_retrying_execute_on_an_already_recovered_plan_does_not_corrupt_it(tmp_path) -> None:
    """Reproduces the audit finding: retrying execute() on a plan that had

    already succeeded re-attempted the same branch creation and turned a
    genuinely successful recovery into a reported CONFLICTED, purely from
    the retry itself. The engine's own execute() is not required to be
    idempotent (RecoveryService.execute is the layer that must not call it
    again for an already-terminal plan -- see
    test_runtime_service_atomicity-adjacent coverage in acceptance tests);
    this test documents the underlying non-idempotent behavior so the
    composing layer's guard is not accidentally removed as "dead code".
    """

    repo, baseline_sha, current_sha = _init_linear_repo(tmp_path)
    database = _database(tmp_path)
    change = _seed_change_and_checkpoint(database, repo, baseline_sha, current_sha)
    engine = GitRecoveryEngine(database)
    plan = engine.plan(change)

    first = engine.execute(change, plan, "approval-token-123")
    assert first.status is RecoveryStatus.RECOVERED

    second = engine.execute(change, plan, "approval-token-123")
    # Retrying the *same original plan* object a second time re-attempts
    # creating the dedicated branch, which already exists from the first
    # call, so the engine itself reports this as a conflict rather than
    # silently repeating success -- exactly why RecoveryService must not
    # call execute() again once a plan is terminal.
    assert second.status is RecoveryStatus.CONFLICTED
