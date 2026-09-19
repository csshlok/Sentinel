from __future__ import annotations

import os

import pytest

from backend.app.git import reader
from backend.app.git.errors import GitCommandError
from backend.tests.support_kb import git, make_repo, write


def test_head_paths_and_committed_reads(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "one\n", "dir/b.txt": "two\n"})
    root = str(repo)
    head = reader.head_sha(root)
    assert head == git(repo, "rev-parse", "HEAD").strip()
    write(repo, "untracked.txt", "u")
    (repo / "a.txt").unlink()
    assert reader.list_paths(root, head) == ["a.txt", "dir/b.txt", "untracked.txt"]
    assert reader.read_committed(root, head, "a.txt", 100) == b"one\n"
    assert reader.read_committed(root, head, "missing.txt", 100) is None
    with pytest.raises(GitCommandError):
        reader.read_committed(root, head, "dir/b.txt", 2)


@pytest.mark.parametrize("call", ["list_paths", "read_committed"])
def test_full_commit_identity_is_required(tmp_path, call):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(GitCommandError):
        if call == "list_paths":
            reader.list_paths(str(repo), "HEAD")
        else:
            reader.read_committed(str(repo), "HEAD", "README.md", 10)


def test_working_reads_are_bounded_and_symlink_safe(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "abc"})
    root = str(repo)
    assert reader.read_working(root, "a.txt", 10) == b"abc"
    assert reader.read_working(root, "nope.txt", 10) is None
    (repo / "sub").mkdir()
    assert reader.read_working(root, "sub", 10) is None
    with pytest.raises(GitCommandError):
        reader.read_working(root, "a.txt", 1)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    try:
        os.symlink(outside, repo / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    with pytest.raises(GitCommandError):
        reader.read_working(root, "link.txt", 100)


def test_unsupported_head_and_encoding_are_domain_errors(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")

    class Fake:
        truncated = False
        stdout = b"not-a-sha\n"

    monkeypatch.setattr(reader, "_run", lambda *a, **k: Fake())
    with pytest.raises(GitCommandError):
        reader.head_sha(str(repo))
    with pytest.raises(GitCommandError):
        reader._paths(b"\xff\xfe")


def test_oversized_metadata_is_refused(tmp_path):
    repo = make_repo(tmp_path / "r", {f"f{i}.txt": "x" for i in range(30)})
    with pytest.raises(GitCommandError):
        reader._run(str(repo), ["ls-files", "-z"], 10)
