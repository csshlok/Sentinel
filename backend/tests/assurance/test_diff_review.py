"""Adversarial regression probes from the Phase 6 independent review."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from backend.app.assurance.diff_map import DiffMap, _parse_patch
from backend.app.assurance.diff_map import map_diff
from backend.app.git.state import GitStateTracker
from backend.tests.support_kb import git, make_repo, write


def test_source_lines_cannot_forge_diff_headers() -> None:
    patch = (
        "diff --git a/a.py b/a.py\nindex 111..222 100644\n--- a/a.py\n+++ b/a.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+# note\u2028+++ covered.py\n"
        "+# note\x0c@@ -1 +1,99 @@\n"
        "+++ covered.py\n"
    )
    mapped = DiffMap()
    _parse_patch(patch, mapped)
    assert mapped.error is None
    assert mapped.lines == {"a.py": {1, 2, 3}}


def test_hunk_count_mismatch_fails_closed() -> None:
    patch = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1,2 @@\n+one\n"
    mapped = DiffMap()
    _parse_patch(patch, mapped)
    assert mapped.error is not None


def test_repository_color_and_inter_hunk_config_cannot_change_mapping(tmp_path: Path) -> None:
    source = "".join(f"value_{index} = {index}\n" for index in range(1, 13))
    root = make_repo(tmp_path / "repo", {"module.py": source})
    tracker = GitStateTracker()
    change_id = uuid4()
    baseline = tracker.capture(change_id, "baseline", str(root), 1, 1_048_576)
    git(root, "config", "color.diff", "always")
    git(root, "config", "diff.interHunkContext", "99")
    write(root, "module.py", source.replace("value_1 = 1", "value_1 = 100")
          .replace("value_12 = 12", "value_12 = 1200"))
    tested = tracker.capture(change_id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert mapped.lines == {"module.py": {1, 12}}


def test_diverged_baseline_commit_is_not_a_valid_diff_origin(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {"module.py": "value = 1\n"})
    tracker = GitStateTracker()
    change_id = uuid4()
    git(root, "checkout", "-q", "-b", "side")
    write(root, "module.py", "value = 2\n")
    git(root, "add", "module.py")
    git(root, "commit", "-q", "-m", "side")
    baseline = tracker.capture(change_id, "baseline", str(root), 1, 1_048_576)
    git(root, "checkout", "-q", "main")
    write(root, "module.py", "value = 3\n")
    git(root, "add", "module.py")
    git(root, "commit", "-q", "-m", "main")
    tested = tracker.capture(change_id, "tested", str(root), 1, 1_048_576)
    assert "not proven" in map_diff(baseline=baseline, tested=tested).error


def test_spaces_and_unicode_paths_map_to_their_real_new_file(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {"a b.py": "value = 1\n", "é.py": "value = 1\n"})
    tracker = GitStateTracker()
    change_id = uuid4()
    baseline = tracker.capture(change_id, "baseline", str(root), 1, 1_048_576)
    write(root, "a b.py", "value = 2\n")
    write(root, "é.py", "value = 3\n")
    tested = tracker.capture(change_id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert mapped.lines == {"a b.py": {1}, "é.py": {1}}


def test_binary_asset_is_listed_without_hiding_python_diff(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {"module.py": "value = 1\n"})
    (root / "logo.png").write_bytes(b"\x89PNG\x00one")
    git(root, "add", "logo.png")
    git(root, "commit", "-q", "-m", "asset")
    tracker = GitStateTracker()
    change_id = uuid4()
    baseline = tracker.capture(change_id, "baseline", str(root), 1, 1_048_576)
    (root / "logo.png").write_bytes(b"\x89PNG\x00two")
    write(root, "module.py", "value = 2\n")
    tested = tracker.capture(change_id, "tested", str(root), 1, 1_048_576)
    mapped = map_diff(baseline=baseline, tested=tested)
    assert mapped.error is None
    assert mapped.lines == {"module.py": {1}}
    assert mapped.excluded["logo.png"] == "binary"
