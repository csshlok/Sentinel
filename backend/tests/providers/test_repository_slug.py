"""GitHub slug resolution through the hardened Git harness."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.providers.repository_slug import resolve_github_repository_slug


def _init(root: Path, origin: str | None) -> str:
    root.mkdir(parents=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    if origin is not None:
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", origin],
                       check=True, capture_output=True)
    return str(root)


@pytest.mark.parametrize(("origin", "expected"), [
    ("https://github.com/acme/widgets.git", "acme/widgets"),
    ("https://github.com/acme/widgets", "acme/widgets"),
    ("git@github.com:acme/widgets.git", "acme/widgets"),
    ("git@github.com:acme/widgets", "acme/widgets"),
    ("https://gitlab.com/acme/widgets.git", None),
])
def test_origin_urls_resolve_to_github_slugs_only(tmp_path, origin, expected) -> None:
    assert resolve_github_repository_slug(_init(tmp_path / "repo", origin)) == expected


def test_repository_without_origin_returns_none(tmp_path) -> None:
    assert resolve_github_repository_slug(_init(tmp_path / "repo", None)) is None


def test_non_repository_directory_returns_none(tmp_path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert resolve_github_repository_slug(str(plain)) is None


def test_missing_git_returns_none(tmp_path, monkeypatch) -> None:
    repo = _init(tmp_path / "repo", "https://github.com/acme/widgets.git")
    monkeypatch.setattr("backend.app.git.safe_exec.shutil.which", lambda _: None)
    assert resolve_github_repository_slug(repo) is None
