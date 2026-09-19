from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.contracts.models import ChangedPathStatus
from backend.app.contracts.ports import GitStatePort
from backend.app.core.errors import AppError
from backend.app.git import state
from backend.app.git.state import GitStateTracker, summary_digest
from backend.tests.support_kb import git, make_repo, write

CHANGE = uuid4()
tracker = GitStateTracker()


def cap(repo, name="cp", revision=1, limit=100_000):
    return tracker.capture(CHANGE, name, str(repo), revision, limit)


def test_conformance_and_clean_capture(tmp_path):
    repo = make_repo(tmp_path / "r")
    assert isinstance(tracker, GitStatePort)
    cp = cap(repo)
    assert cp.branch == "main" and cp.summary.is_clean
    assert cp.head_sha == git(repo, "rev-parse", "HEAD").strip()
    assert cp.change_id == CHANGE and cp.evidence_revision == 1
    assert type(cp).model_validate_json(cp.model_dump_json()) == cp


def test_digest_is_deterministic_and_time_independent(tmp_path):
    repo = make_repo(tmp_path / "r")
    write(repo, "a.py", "x = 1\n")
    a, b = cap(repo), cap(repo)
    assert a.id != b.id and a.captured_at <= b.captured_at
    assert a.status_digest == b.status_digest
    assert summary_digest(a.summary) != a.status_digest  # untracked content is bound in


def test_digest_moves_with_every_kind_of_change(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "one\n", "b.txt": "two\n"})
    digests = [cap(repo).status_digest]
    write(repo, "a.txt", "ONE\n")
    digests.append(cap(repo).status_digest)
    git(repo, "add", "a.txt")
    digests.append(cap(repo).status_digest)
    write(repo, "new.txt", "n1\n")
    digests.append(cap(repo).status_digest)
    write(repo, "new.txt", "n2\n")
    digests.append(cap(repo).status_digest)
    assert len(set(digests)) == len(digests)


def test_same_count_edit_changes_digest_via_patch(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "aaaa\n"})
    write(repo, "a.txt", "bbbb\n")
    first = cap(repo).status_digest
    write(repo, "a.txt", "cccc\n")
    assert cap(repo).status_digest != first


def test_rename_delete_binary_unicode_and_spaces(tmp_path):
    repo = make_repo(tmp_path / "with space", {
        "old name.txt": "content that is long enough to detect a rename\n" * 5,
        "gone.txt": "bye\n", "ünï.txt": "u\n"})
    git(repo, "mv", "old name.txt", "new name.txt")
    (repo / "gone.txt").unlink()
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02")
    write(repo, "ünï.txt", "changed\n")
    by_path = {f.path: f for f in cap(repo).summary.files}
    assert by_path["new name.txt"].status is ChangedPathStatus.RENAMED
    assert by_path["new name.txt"].old_path == "old name.txt"
    assert by_path["gone.txt"].status is ChangedPathStatus.DELETED
    assert by_path["blob.bin"].status is ChangedPathStatus.UNTRACKED
    assert by_path["ünï.txt"].status is ChangedPathStatus.MODIFIED


def test_merge_conflict_is_represented(tmp_path):
    repo = make_repo(tmp_path / "r", {"c.txt": "base\n"})
    git(repo, "checkout", "-q", "-b", "side")
    write(repo, "c.txt", "side\n")
    git(repo, "commit", "-qam", "side")
    git(repo, "checkout", "-q", "main")
    write(repo, "c.txt", "main\n")
    git(repo, "commit", "-qam", "main")
    git(repo, "merge", "side", check=False)
    assert [f.status for f in cap(repo).summary.files] == [ChangedPathStatus.CONFLICTED]


def test_detached_head_and_unborn_repository(tmp_path):
    repo = make_repo(tmp_path / "r")
    git(repo, "checkout", "-q", "--detach")
    assert cap(repo).branch is None
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    with pytest.raises(AppError) as info:
        cap(empty)
    assert info.value.code == "REPOSITORY_HAS_NO_COMMITS"


@pytest.mark.parametrize(("rev", "limit", "code"), [
    (0, 10, "INVALID_EVIDENCE_REVISION"), (True, 10, "INVALID_EVIDENCE_REVISION"),
    (1, -1, "INVALID_PATCH_LIMIT"), (1, 2_000_000, "INVALID_PATCH_LIMIT"),
    (1, 1.5, "INVALID_PATCH_LIMIT"),
])
def test_capture_bounds(tmp_path, rev, limit, code):
    repo = make_repo(tmp_path / "r")
    with pytest.raises(AppError) as info:
        tracker.capture(CHANGE, "x", str(repo), rev, limit)
    assert info.value.code == code


def test_invalid_path_is_domain_error(tmp_path):
    with pytest.raises(AppError):
        cap(tmp_path / "nope")


def test_capture_never_mutates_the_repository(tmp_path):
    repo = make_repo(tmp_path / "r")
    write(repo, "a.txt", "x\n")
    git(repo, "add", "a.txt")
    write(repo, "b.txt", "y\n")
    commands = ("rev-parse HEAD", "status --porcelain=v2", "config --list",
                "remote -v", "ls-files --stage")
    before = {n: git(repo, *n.split()) for n in commands}
    index_bytes = (repo / ".git" / "index").read_bytes()
    for _ in range(3):
        cap(repo)
    assert before == {n: git(repo, *n.split()) for n in commands}
    assert (repo / ".git" / "index").read_bytes() == index_bytes
    assert (repo / "b.txt").read_bytes() == b"y\n"


def test_three_checkpoint_comparison_flow(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "1\n", "b.txt": "1\n"})
    base = cap(repo, "baseline", 1)
    write(repo, "a.txt", "2\n")
    write(repo, "c.txt", "new\n")
    mid = cap(repo, "mid", 2)
    write(repo, "a.txt", "3\n")
    (repo / "c.txt").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "move")
    last = cap(repo, "last", 3)

    one = tracker.compare(base, mid)
    assert one.added_paths == ["a.txt", "c.txt"] and one.removed_paths == []
    assert not one.head_changed and not one.branch_moved

    two = tracker.compare(mid, last)
    # mid -> last commits a.txt's edit (its uncommitted status at `mid`
    # simply stops showing once committed) and c.txt is deleted again before
    # ever being committed, so the real commit range never touches it.
    # a.txt genuinely changed content, not disappeared -- reporting it as
    # "removed" (status-only, pre-fix behavior) rather than "changed" would
    # be exactly the audit-found bug: a committed edit misclassified because
    # a working-tree-status snapshot alone cannot distinguish "committed" from
    # "reverted to clean".
    assert two.head_changed
    assert two.removed_paths == ["c.txt"]
    assert two.changed_paths == ["a.txt"]

    three = tracker.compare(base, last)
    # base -> last is a real commit range (a.txt "1" -> "3"); c.txt never
    # existed in any commit (added and deleted purely in uncommitted working
    # -tree stages), so it correctly does not appear at all. The
    # status-only comparison alone would see two clean trees and wrongly
    # report zero differences despite the real, committed a.txt edit --
    # the exact class of defect this fix closes.
    assert three.head_changed
    assert three.added_paths == []
    assert three.changed_paths == ["a.txt"]

    same = tracker.compare(mid, mid)
    assert not (same.added_paths or same.removed_paths or same.changed_paths)


def test_compare_detects_changed_record_and_branch_move(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "1\n"})
    write(repo, "a.txt", "2\n")
    first = cap(repo)
    git(repo, "add", "a.txt")
    second = cap(repo)
    git(repo, "checkout", "-q", "-b", "feature")
    third = cap(repo)
    assert tracker.compare(first, second).changed_paths == ["a.txt"]
    assert tracker.compare(second, third).branch_moved is True


def test_compare_rejects_other_repository(tmp_path):
    a = cap(make_repo(tmp_path / "a"))
    b = cap(make_repo(tmp_path / "b"))
    with pytest.raises(AppError) as info:
        tracker.compare(a, b)
    assert info.value.code == "CHECKPOINT_REPOSITORY_MISMATCH"


def test_freshness_including_untracked_edits(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "1\n"})
    cp = cap(repo)
    assert tracker.is_current(cp)
    write(repo, "u.txt", "1")
    assert tracker.is_current(cp) is False
    cp2 = cap(repo)
    assert tracker.is_current(cp2, str(repo))
    write(repo, "u.txt", "2")
    assert not tracker.is_current(cp2)


def test_freshness_for_truncated_patch(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "1\n"})
    write(repo, "a.txt", "line\n" * 200)
    cp = cap(repo, limit=64)
    assert cp.summary.patch_truncated
    assert tracker.is_current(cp) is False
    assert tracker.is_current(cp, patch_limit_bytes=64) is True
    write(repo, "a.txt", "LINE\n" * 200)
    assert tracker.is_current(cp, patch_limit_bytes=64) is False


def test_untracked_content_bounds(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r")
    write(repo, "big.dat", "x" * 50)
    write(repo, "small.dat", "s")
    files = cap(repo).summary.files
    assert state._untracked_content(str(repo), files)["small.dat"].startswith("sha256:")
    monkeypatch.setattr(state, "UNTRACKED_FILE_LIMIT", 10)
    assert state._untracked_content(str(repo), files)["big.dat"] == "oversize:50"
    monkeypatch.setattr(state, "UNTRACKED_FILE_COUNT", 1)
    assert "<more>" in state._untracked_content(str(repo), files)
    (repo / "big.dat").unlink()
    monkeypatch.setattr(state, "UNTRACKED_FILE_COUNT", 100)
    assert state._untracked_content(str(repo), files)["big.dat"] == "special"
    (repo / "small.dat").unlink()
    (repo / "small.dat").mkdir()
    assert state._untracked_content(str(repo), files)["small.dat"] == "special"
