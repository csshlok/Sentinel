"""Per-run DOS drives: real DefineDosDeviceW mappings in this logon session, always removed."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.execution import dos_drive
from backend.app.execution.dos_drive import (
    CANDIDATE_LETTERS,
    map_drive,
    query_drive,
    sweep_drives,
    unmap_drive,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="DOS drive mappings are Windows-only")


@pytest.fixture
def cleanup():
    made: list[tuple[str, Path]] = []
    yield made
    for letter, target in made:
        unmap_drive(letter, target)


def test_map_resolves_to_the_target_and_unmap_removes_it(tmp_path, cleanup):
    target = tmp_path / "AC"
    (target / "ws").mkdir(parents=True)
    letter = map_drive(target)
    cleanup.append((letter, target))
    assert letter in CANDIDATE_LETTERS
    (Path(letter + "\\") / "ws" / "probe.txt").write_text("via drive", encoding="utf-8")
    assert (target / "ws" / "probe.txt").read_text(encoding="utf-8") == "via drive"
    assert unmap_drive(letter, target) is True
    assert query_drive(letter) == []
    assert not os.path.exists(letter + "\\")


def test_taken_letters_are_skipped(tmp_path, cleanup):
    first_target = tmp_path / "one"
    second_target = tmp_path / "two"
    first_target.mkdir()
    second_target.mkdir()
    first = map_drive(first_target)
    cleanup.append((first, first_target))
    second = map_drive(second_target)
    cleanup.append((second, second_target))
    assert first != second
    assert CANDIDATE_LETTERS.index(second) > CANDIDATE_LETTERS.index(first)


def test_unmap_never_removes_another_mapping_on_the_same_letter(tmp_path, cleanup):
    ours = tmp_path / "ours"
    foreign = tmp_path / "foreign"
    ours.mkdir()
    foreign.mkdir()
    letter = map_drive(foreign)
    cleanup.append((letter, foreign))
    assert unmap_drive(letter, ours) is True  # nothing of ours was there
    assert len(query_drive(letter)) == 1  # the foreign mapping survives
    assert os.path.exists(letter + "\\")


def test_map_refuses_a_missing_target(tmp_path):
    with pytest.raises(OSError):
        map_drive(tmp_path / "missing")


def test_map_raises_when_no_letter_is_free(tmp_path, monkeypatch):
    target = tmp_path / "AC"
    target.mkdir()
    monkeypatch.setattr(dos_drive, "_logical_letters", lambda: set(CANDIDATE_LETTERS))
    with pytest.raises(OSError, match="No free drive letter"):
        map_drive(target)


def test_sweep_removes_only_prefixed_targets_under_root(tmp_path, cleanup):
    packages = tmp_path / "Packages"
    ours = packages / "sentinel.w.abc" / "AC"
    other_profile = packages / "someone.else" / "AC"
    outside = tmp_path / "elsewhere"
    for path in (ours, other_profile, outside):
        path.mkdir(parents=True)
    mapped = {target: map_drive(target) for target in (ours, other_profile, outside)}
    cleanup.extend((letter, target) for target, letter in mapped.items())
    removed = sweep_drives(packages, name_prefix="sentinel.w.")
    assert removed == [f"{mapped[ours]} -> {ours}"]
    assert query_drive(mapped[ours]) == []
    assert query_drive(mapped[other_profile]) and query_drive(mapped[outside])
