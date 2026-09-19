from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.contracts.models import (
    ChangedPathStatus,
    GitSummary,
    PathCategory,
    RepositoryInfo,
)
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.classifier import classify_path
from backend.app.git.errors import GitCommandError, RepositoryValidationError


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample repository with spaces"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "Tester")
    git(repo, "config", "user.email", "tester@example.com")
    (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
    (repo / "modify.py").write_text("first\n", encoding="utf-8")
    (repo / "delete.py").write_text("delete\n", encoding="utf-8")
    (repo / "rename.py").write_text("rename\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    return repo


def by_path(summary: GitSummary) -> dict[str, object]:
    return {item.path: item for item in summary.files}


def test_validate_repository_returns_contract_and_accepts_nested_path(repo: Path) -> None:
    nested = repo / "nested"
    nested.mkdir()

    result = GitRepositoryInspector().validate_repository(str(nested))

    assert isinstance(result, RepositoryInfo)
    assert result.root == str(repo.resolve())
    assert result.branch is not None
    assert len(result.head_sha) == 40


def test_validate_repository_returns_stable_errors(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(RepositoryValidationError) as invalid:
        GitRepositoryInspector().validate_repository(str(missing))
    assert invalid.value.code == "INVALID_REPOSITORY_PATH"

    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    with pytest.raises(RepositoryValidationError) as not_git:
        GitRepositoryInspector().validate_repository(str(non_repo))
    assert not_git.value.code == "NOT_A_GIT_REPOSITORY"


def test_validate_repository_rejects_repository_without_commit(tmp_path: Path) -> None:
    empty_repo = tmp_path / "empty-repo"
    subprocess.run(["git", "init", str(empty_repo)], check=True, capture_output=True)

    with pytest.raises(RepositoryValidationError) as error:
        GitRepositoryInspector().validate_repository(str(empty_repo))

    assert error.value.code == "REPOSITORY_HAS_NO_COMMITS"


def test_validate_repository_preserves_git_startup_errors(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr("backend.app.execution._process.subprocess.Popen", unavailable)

    with pytest.raises(GitCommandError) as error:
        GitRepositoryInspector().validate_repository(str(repo))

    assert error.value.code == "GIT_COMMAND_FAILED"
    assert error.value.details == {}


def test_validate_repository_allows_detached_head(repo: Path) -> None:
    git(repo, "checkout", "--detach")

    result = GitRepositoryInspector().validate_repository(str(repo))

    assert result.branch is None
    assert len(result.head_sha) == 40


def test_inspect_parses_modified_deleted_and_renamed_paths(repo: Path) -> None:
    (repo / "modify.py").write_text("first\nsecond\n", encoding="utf-8")
    git(repo, "rm", "delete.py")
    git(repo, "mv", "rename.py", "renamed.py")

    result = GitRepositoryInspector().inspect(str(repo), 1_048_576)
    files = by_path(result)

    assert isinstance(result, GitSummary)
    modified = files["modify.py"]
    assert modified.status is ChangedPathStatus.MODIFIED
    assert modified.staged is False
    assert modified.unstaged is True
    assert modified.additions == 1
    assert modified.deletions == 0

    deleted = files["delete.py"]
    assert deleted.status is ChangedPathStatus.DELETED
    assert deleted.staged is True
    assert deleted.unstaged is False
    assert deleted.deletions == 1

    renamed = files["renamed.py"]
    assert renamed.status is ChangedPathStatus.RENAMED
    assert renamed.old_path == "rename.py"
    assert renamed.staged is True
    assert renamed.unstaged is False
    assert result.total_additions == 1
    assert result.total_deletions == 1


def test_inspect_reports_untracked_without_reading_it_into_patch(repo: Path) -> None:
    (repo / "untracked.txt").write_text("not part of tracked diff\n", encoding="utf-8")

    result = GitRepositoryInspector().inspect(str(repo), 1_048_576)
    untracked = by_path(result)["untracked.txt"]

    assert untracked.status is ChangedPathStatus.UNTRACKED
    assert untracked.additions is None
    assert untracked.deletions is None
    assert result.total_additions == 0
    assert result.untracked_patch_omitted is True
    assert result.patch_truncated is False
    assert "not part of tracked diff" not in result.patch


def test_inspect_marks_binary_file(repo: Path) -> None:
    binary = repo / "asset.bin"
    binary.write_bytes(bytes(range(256)))
    git(repo, "add", "asset.bin")
    git(repo, "commit", "-m", "binary baseline")
    binary.write_bytes(bytes(reversed(range(256))))

    result = GitRepositoryInspector().inspect(str(repo), 1_048_576)
    changed = by_path(result)["asset.bin"]

    assert changed.binary is True
    assert changed.additions is None
    assert changed.deletions is None


def test_patch_limit_is_utf8_byte_accurate(repo: Path) -> None:
    (repo / "modify.py").write_text("first\n" + "é" * 500, encoding="utf-8")

    result = GitRepositoryInspector().inspect(str(repo), 101)

    assert result.patch_truncated is True
    assert len(result.patch.encode("utf-8")) <= 101


def test_conflict_record_parser() -> None:
    record = (
        "u UU N... 100644 100644 100644 100644 "
        + "a" * 40
        + " "
        + "b" * 40
        + " "
        + "c" * 40
        + " conflict.py\0"
    )

    parsed = GitRepositoryInspector._parse_status(record)

    assert len(parsed) == 1
    assert parsed[0].status is ChangedPathStatus.CONFLICTED


def test_copy_record_parser_preserves_old_path() -> None:
    record = (
        "2 C. N... 100644 100644 100644 "
        + "a" * 40
        + " "
        + "b" * 40
        + " C100 copied.py\0original.py\0"
    )

    parsed = GitRepositoryInspector._parse_status(record)

    assert len(parsed) == 1
    assert parsed[0].status is ChangedPathStatus.COPIED
    assert parsed[0].path == "copied.py"
    assert parsed[0].old_path == "original.py"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("requirements.txt", PathCategory.DEPENDENCY),
        ("src/package_utils.py", PathCategory.SOURCE),
        ("tests/test_demo.py", PathCategory.TEST),
        ("src/widget.spec.ts", PathCategory.TEST),
        (".circleci/config.yml", PathCategory.CONFIG),
        ("docs/guide.md", PathCategory.DOCUMENTATION),
        ("src/services/service.py", PathCategory.SOURCE),
        ("notes.txt", PathCategory.OTHER),
    ],
)
def test_classify_path_respects_precedence(
    path: str, expected: PathCategory
) -> None:
    assert classify_path(path) is expected
