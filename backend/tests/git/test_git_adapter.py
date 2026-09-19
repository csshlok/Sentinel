from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.git.adapter import GitRepositoryInspector, classify_path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Tester"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "tester@example.com"], check=True)
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True, text=True)
    return repo


def test_validate_repository_accepts_git_work_tree(repo: Path) -> None:
    result = GitRepositoryInspector().validate_repository(str(repo))

    assert result["root"] == str(repo.resolve())
    assert result["branch"] is not None
    assert result["head_sha"]


def test_validate_repository_rejects_non_repo(tmp_path: Path) -> None:
    missing = tmp_path / "not-a-repo"
    missing.mkdir()

    with pytest.raises(ValueError):
        GitRepositoryInspector().validate_repository(str(missing))


def test_inspect_tracks_summary_and_classification(repo: Path) -> None:
    (repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = GitRepositoryInspector().inspect(str(repo), patch_limit_bytes=1024 * 1024)

    assert result["is_clean"] is False
    assert any(item["path"] == "app.py" for item in result["files"])
    assert any(item["path"] == "tests/test_app.py" for item in result["files"])
    assert result["total_additions"] >= 1
    assert result["total_deletions"] >= 0
    assert isinstance(result["patch"], str)


def test_classify_path_respects_precedence() -> None:
    assert classify_path("requirements.txt") == "DEPENDENCY"
    assert classify_path("tests/test_demo.py") == "TEST"
    assert classify_path("docs/guide.md") == "DOCUMENTATION"
    assert classify_path("src/services/service.py") == "SOURCE"
    assert classify_path("notes.txt") == "OTHER"


def test_inspect_handles_untracked_and_truncated_patch(repo: Path) -> None:
    large_text = "x\n" * 5000
    (repo / "large.txt").write_text(large_text, encoding="utf-8")

    result = GitRepositoryInspector().inspect(str(repo), patch_limit_bytes=200)

    assert result["untracked_patch_omitted"] is True
    assert result["patch_truncated"] is True
    assert "large.txt" in {item["path"] for item in result["files"]}
