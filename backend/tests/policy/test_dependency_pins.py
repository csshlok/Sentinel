"""Release dependencies are explicit and match the verified test environment."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement


def test_runtime_and_test_dependencies_are_exactly_pinned() -> None:
    root = Path(__file__).resolve().parents[3]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    groups = [project["project"]["dependencies"]]
    groups.extend(project["project"]["optional-dependencies"].values())
    for group in groups:
        for declared in group:
            requirement = Requirement(declared)
            assert len(requirement.specifier) == 1, declared
            pin = next(iter(requirement.specifier))
            assert pin.operator == "==" and "*" not in pin.version, declared
            assert version(requirement.name) == pin.version, declared
