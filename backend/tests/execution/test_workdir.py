"""Sentinel temporary directories are refused inside a supervised repository (WR-02)."""

from __future__ import annotations

import tempfile

import pytest

from backend.app.execution.workdir import (
    WorkdirInsideRepositoryError,
    ensure_outside,
    is_inside,
    temporary_base,
)


def test_is_inside_matches_the_root_itself_and_descendants_only(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    assert is_inside(repo, [repo])
    assert is_inside(repo / "sub", [repo])
    assert is_inside(repo / "missing" / "deeper", [repo])
    assert not is_inside(tmp_path, [repo])
    assert not is_inside(tmp_path / "repo-sibling", [repo])


def test_temporary_base_is_the_system_temp_when_no_repository_encloses_it(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert temporary_base([repo]) == ensure_outside(tempfile.gettempdir(), [])


def test_temporary_base_refuses_a_repository_that_encloses_temp(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "home"
    temp = repo / "AppData" / "Local" / "Temp"
    temp.mkdir(parents=True)
    monkeypatch.setattr(tempfile, "tempdir", str(temp))

    with pytest.raises(WorkdirInsideRepositoryError) as caught:
        temporary_base([repo])
    assert isinstance(caught.value, OSError)
    assert "TEMP" in str(caught.value)


def test_a_junction_from_temp_into_the_repository_is_refused(tmp_path, monkeypatch) -> None:
    import os

    if os.name != "nt":
        pytest.skip("junctions are Windows-only")
    import _winapi

    repo = tmp_path / "repo"
    (repo / "tmp").mkdir(parents=True)
    link = tmp_path / "temp-link"
    try:
        _winapi.CreateJunction(str(repo / "tmp"), str(link))
    except OSError as error:
        pytest.skip(f"cannot create a junction here: {error}")
    monkeypatch.setattr(tempfile, "tempdir", str(link))

    with pytest.raises(WorkdirInsideRepositoryError):
        temporary_base([repo])
