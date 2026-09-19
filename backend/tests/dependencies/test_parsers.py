from __future__ import annotations

import json
import random
import string

import pytest

from backend.app.dependencies import parsers
from backend.app.dependencies.parsers import ParseError, parse_package_json, parse_package_lock


def names(entries):
    return {(e.name, e.version, e.scope) for e in entries}


def test_requirements_forms():
    text = (
        "# comment\n\nFlask[async]==2.0.1 ; python_version>'3'\nRequests>=2,<3  # trailing\n"
        "my_pkg\n-r other.txt\n--index-url https://example.test/simple\n-e ./local\n"
        "pkg @ https://example.test/p.whl\nlong==1.0 \\\n  --hash=sha256:abc\n"
        "git+https://example.test/x.git#egg=x\n./wheel.whl\n"
    )
    entries = {e.name: e for e in parsers.parse_requirements(text)}
    assert entries["flask"].version == "2.0.1" and entries["flask"].exact
    assert entries["requests"].version == ">=2,<3" and not entries["requests"].exact
    assert entries["my-pkg"].version == "(unpinned)"
    assert entries["pkg"].source == "url"
    assert entries["long"].version == "1.0"
    assert entries["<include:other.txt>"].scope == "include"
    assert entries["<editable:./local>"].source == "path"
    assert any(n.startswith("<direct:git+") for n in entries)
    assert any(n.startswith("<direct:./wheel") for n in entries)


def test_requirements_pending_continuation_and_bad_line():
    assert parsers.parse_requirements("a==1 \\") [0].name == "a"
    with pytest.raises(ParseError):
        parsers.parse_requirements("== nonsense")


def test_pyproject_pep621_groups_and_poetry():
    text = """
[build-system]
requires = ["setuptools>=75"]
[project]
name = "x"
dependencies = ["FastAPI>=0.115,<1", "pydantic==2.10.0"]
[project.optional-dependencies]
test = ["pytest>=8"]
[dependency-groups]
dev = ["ruff", {include-group = "test"}]
[tool.poetry.dependencies]
python = "^3.12"
requests = "^2.31"
pinned = "1.2.3"
local = {path = "../local"}
gitdep = {git = "https://example.test/g.git"}
urldep = {url = "https://example.test/u.whl"}
plain = {version = "==4.5.6"}
multi = [{version = "1.0"}]
[tool.poetry.group.lint.dependencies]
black = "24.1.0"
"""
    got = names(parsers.parse_pyproject(text))
    assert ("fastapi", ">=0.115,<1", "") in got
    assert ("pydantic", "2.10.0", "") in got
    assert ("pytest", ">=8", "optional:test") in got
    assert ("ruff", "(unpinned)", "group:dev") in got
    assert ("setuptools", ">=75", "build") in got
    assert ("requests", "^2.31", "") in got and ("pinned", "1.2.3", "") in got
    assert ("black", "24.1.0", "group:lint") in got
    by = {e.name: e for e in parsers.parse_pyproject(text)}
    assert by["local"].source == "path" and by["gitdep"].source == "git"
    assert by["urldep"].source == "url" and by["plain"].version == "4.5.6"
    assert by["multi"].version == "1.0"
    assert "python" not in by


@pytest.mark.parametrize("text", [
    "not = toml =", "[project]\ndependencies = 3", "[project]\ndependencies = [1]",
    "[project.optional-dependencies]\nx = 1", "project = 1",
    "[tool.poetry]\ndependencies = 3", "[tool.poetry.dependencies]\nx = 3",
    "[dependency-groups]\nx = 1", "dependency-groups = 3",
])
def test_pyproject_malformed(text):
    with pytest.raises(ParseError):
        parsers.parse_pyproject(text)


def test_poetry_lock():
    text = '[[package]]\nname = "Foo_Bar"\nversion = "1.0"\n[[package]]\nname = "loc"\nversion = "2"\n[package.source]\ntype = "directory"\n'
    got = parsers.parse_poetry_lock(text, {"foo-bar"})
    assert got[0].name == "foo-bar" and got[0].direct is True and got[0].kind == "resolved"
    assert got[1].source == "path" and got[1].direct is False
    assert parsers.parse_poetry_lock(text)[0].direct is None
    for bad in ("[[package]]\nname = 1", "package = 3", "= x"):
        with pytest.raises(ParseError):
            parsers.parse_poetry_lock(bad)


def test_package_json_sources_and_workspaces():
    text = json.dumps({
        "workspaces": ["packages/*"],
        "dependencies": {"React": "18.2.0", "left": "^1.0.0", "loc": "file:../loc",
                         "u": "https://example.test/u.tgz", "g": "github:a/b", "g2": "a/b#main",
                         "w": "workspace:*", "alias": "npm:other@1"},
        "devDependencies": {"jest": "29.0.0-beta.1"}, "optionalDependencies": {"o": "1.0.0"},
        "peerDependencies": {"p": ">=1"},
    })
    entries, workspaces = parse_package_json(text)
    by = {e.name: e for e in entries}
    assert workspaces and by["react"].exact and by["jest"].scope == "dev" and by["jest"].exact
    assert not by["left"].exact and by["loc"].source == "path" and by["u"].source == "url"
    assert by["g"].source == "git" and by["g2"].source == "git" and by["w"].source == "workspace"
    assert by["alias"].source == "registry" and by["o"].scope == "optional" and by["p"].scope == "peer"


@pytest.mark.parametrize("text", [
    "[]", "{bad", '{"dependencies": []}', '{"dependencies": {"a": 1}}',
])
def test_package_json_malformed(text):
    with pytest.raises(ParseError):
        parse_package_json(text)


def test_deeply_nested_json_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_package_json("[" * 100_000)


def test_package_lock_v3_and_direct_labels():
    lock = json.dumps({"lockfileVersion": 3, "packages": {
        "": {"dependencies": {"a": "^1"}, "devDependencies": {"@s/b": "1"}},
        "node_modules/a": {"version": "1.2.0", "resolved": "https://registry.npmjs.org/a/-/a-1.2.0.tgz"},
        "node_modules/@s/b": {"version": "1.0.0"},
        "node_modules/a/node_modules/c": {"version": "3.0.0"},
        "node_modules/loc": {"resolved": "../loc", "link": True},
        "node_modules/git": {"version": "1.0.0", "resolved": "git+https://example.test/g.git"},
        "node_modules/url": {"version": "1.0.0", "resolved": "https://example.test/u.tgz"},
        "node_modules/skip": {"dev": True},
        "packages/ws": {"version": "1.0.0"}, "packages/linked": {"link": True},
        "junk": 5,
    }})
    by = {(e.name, e.scope): e for e in parse_package_lock(lock)}
    assert by[("a", "")].direct and by[("@s/b", "")].direct and by[("a", "")].source == "registry"
    assert by[("c", "nested:node_modules/a/node_modules/c")].direct is False
    assert by[("loc", "")].source == "path" and by[("git", "")].source == "git"
    assert by[("url", "")].source == "url"
    assert ("skip", "") not in by
    manifest_direct = {e.name: e for e in parse_package_lock(lock, {"c"})}
    assert manifest_direct["c"].direct is False  # nested is never direct


def test_package_lock_v1():
    lock = json.dumps({"lockfileVersion": 1, "dependencies": {
        "a": {"version": "1.0.0", "dependencies": {"b": {"version": "2.0.0"}}},
        "u": {"version": "https://example.test/u.tgz"}}})
    by = {(e.name, e.scope): e for e in parse_package_lock(lock, {"a"})}
    assert by[("a", "")].direct and by[("b", "nested:a>b")].direct is False
    assert by[("u", "")].source == "url"
    with pytest.raises(ParseError):
        parse_package_lock(json.dumps({"dependencies": {"a": {}}}))
    deep: dict = {"version": "1"}
    for _ in range(80):
        deep = {"version": "1", "dependencies": {"x": deep}}
    with pytest.raises(ParseError):
        parse_package_lock(json.dumps({"dependencies": {"x": deep}}))


@pytest.mark.parametrize("text", ["[]", "{}", "nope"])
def test_package_lock_malformed_or_unsupported(text):
    with pytest.raises(ParseError):
        parse_package_lock(text)


def test_support_tables():
    assert parsers.is_supported("a/requirements-dev.txt") and parsers.is_supported("Package.JSON")
    assert not parsers.is_supported("yarn.lock")
    assert parsers.unsupported_ecosystem("x/Cargo.toml") == "rust"
    assert parsers.unsupported_ecosystem("x.py") is None
    assert parsers.normalize_python("A_b.C--d") == "a-b-c-d"


def test_fuzzed_input_only_raises_parse_error():
    rng = random.Random(1234)
    alphabet = string.printable + "é中{}[]=\"'@#\\"
    for _ in range(300):
        blob = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 200)))
        for parse in (parsers.parse_requirements, parsers.parse_pyproject,
                      parsers.parse_package_json, parsers.parse_package_lock,
                      parsers.parse_poetry_lock):
            try:
                parse(blob)
            except ParseError:
                pass
