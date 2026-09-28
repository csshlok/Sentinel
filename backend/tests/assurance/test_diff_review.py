"""Adversarial regression probes from the Phase 6 independent review."""

from __future__ import annotations

from backend.app.assurance.diff_map import DiffMap, _parse_patch


def test_source_lines_cannot_forge_diff_headers() -> None:
    patch = (
        "diff --git a.py a.py\nindex 111..222 100644\n--- a.py\n+++ a.py\n"
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
    patch = "diff --git a.py a.py\n--- a.py\n+++ a.py\n@@ -0,0 +1,2 @@\n+one\n"
    mapped = DiffMap()
    _parse_patch(patch, mapped)
    assert mapped.error is not None
