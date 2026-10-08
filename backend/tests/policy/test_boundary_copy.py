"""Plan 02-04 (SC3/SC4): boundary wording is precise and never an unqualified isolation claim."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from backend.app.core.boundary_text import boundary_line, boundary_lines

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "backend" / "app"
CLAIM = re.compile(r"\b(sandbox(?:ed|es|ing)?|isolat(?:ed|ion|es|e))\b", re.IGNORECASE)
# A claim word is allowed only inside one of these qualified phrases.
QUALIFIED = re.compile(
    r"not a sandbox|no filesystem or network isolation|not filesystem/network isolation"
    r"|not a sandbox or isolation boundary|does not isolate|make no isolation claim"
    r"|Electron's context isolation|Electron renderer sandbox", re.IGNORECASE)

BOX = {"kind": "APPCONTAINER", "capabilities": ["internetClient"], "integrity_rid": "0x1000",
       "job_verified": True, "workspace_drive": "Z:"}


def _user_facing_strings() -> list[tuple[str, str]]:
    """Every non-docstring string constant in backend/app (messages, limitations, CLI/TUI)."""

    found: list[tuple[str, str]] = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                           ast.AsyncFunctionDef))
                      and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings):
                found.append((f"{path.relative_to(ROOT)}:{node.lineno}", node.value))
    for name in ("README.md", "SECURITY.md"):
        for number, line in enumerate((ROOT / name).read_text(encoding="utf-8").splitlines(), 1):
            found.append((f"{name}:{number}", line))
    return found


def _unqualified(text: str) -> list[str]:
    allowed = [match.span() for match in QUALIFIED.finditer(text)]
    return [match.group(0) for match in CLAIM.finditer(text)
            if not any(start <= match.start() < end for start, end in allowed)]


def test_no_user_facing_text_makes_an_unqualified_isolation_claim() -> None:
    hits = [f"{where}: {words}" for where, text in _user_facing_strings()
            if (words := _unqualified(text))]
    assert hits == []


@pytest.mark.parametrize(("run", "expected"), [
    ({"execution_boundary": BOX},
     "Boundary: AppContainer (capabilities: internetClient; integrity low; Job verified; "
     "workspace drive Z:)"),
    ({"execution_boundary": {"kind": "RESTRICTED_TOKEN", "job_verified": True}},
     "Boundary: reduced token only (restricted token in a Job Object; not a sandbox, "
     "no filesystem or network restriction)"),
    ({"execution_boundary": {"kind": "NONE"}},
     "Boundary: none (attached or unreduced run; no boundary was observed)"),
    ({"execution_boundary": None},
     "Boundary: not observed (the run did not start, or was recorded before boundaries were)"),
])
def test_each_boundary_kind_has_its_own_line(run, expected) -> None:
    assert boundary_line(run) == expected


def test_appcontainer_and_reduced_token_lines_cannot_be_confused() -> None:
    box = boundary_line({"execution_boundary": BOX})
    reduced = boundary_line({"execution_boundary": {"kind": "RESTRICTED_TOKEN"}})
    assert "AppContainer" in box and "AppContainer" not in reduced
    assert "reduced token" in reduced and "reduced token" not in box


def test_lines_for_one_run_and_a_list() -> None:
    run = {"id": "r1", "status": "PASSED", "adapter": "claude", "execution_boundary": BOX}
    assert boundary_lines(run) == [boundary_line(run)]
    assert boundary_lines({"items": [run]}) == [f"r1: {boundary_line(run)}"]
    assert boundary_lines({"items": []}) == [] and boundary_lines("text") == []
