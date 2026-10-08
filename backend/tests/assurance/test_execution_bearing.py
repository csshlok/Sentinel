"""Plan 02-06: paths whose change makes code run later outside Sentinel are flagged."""

from __future__ import annotations

import pytest

from backend.app.assurance.execution_bearing import (BUILD_HOOK, CI, HOOK, NPM, TEST_BOOTSTRAP,
                                                     classify, execution_bearing)

PACKAGE = b'{"name": "app", "version": "1.0.0", "scripts": {"test": "jest"}}'
PYPROJECT = b'[project]\nname = "app"\nversion = "1.0"\n[build-system]\nrequires = ["setuptools"]\n'


@pytest.mark.parametrize(("path", "category"), [
    (".github/workflows/ci.yml", CI),
    (".GitHub/Workflows/release.yaml", CI),
    (".circleci/config.yml", CI),
    (".gitlab-ci.yml", CI),
    ("Jenkinsfile", CI),
    ("conftest.py", TEST_BOOTSTRAP),
    ("pkg/tests/conftest.py", TEST_BOOTSTRAP),
    ("pytest.ini", TEST_BOOTSTRAP),
    ("tox.ini", TEST_BOOTSTRAP),
    ("setup.cfg", TEST_BOOTSTRAP),
    ("src/sitecustomize.py", TEST_BOOTSTRAP),
    ("site/evil.pth", TEST_BOOTSTRAP),
    ("setup.py", BUILD_HOOK),
    ("Makefile", BUILD_HOOK),
    ("CMakeLists.txt", BUILD_HOOK),
    (".husky/pre-commit", HOOK),
    (".pre-commit-config.yaml", HOOK),
    (".vscode/tasks.json", HOOK),
    (".vscode/launch.json", HOOK),
    (".devcontainer/devcontainer.json", HOOK),
    (".npmrc", NPM),
])
def test_each_category_is_detected(path: str, category: str) -> None:
    assert classify(path, b"old", b"new") == category


@pytest.mark.parametrize("path", ["src/app.py", "README.md", ".vscode/settings.json",
                                  "docs/Makefile.md", "workflows/ci.yml"])
def test_ordinary_files_are_not_flagged(path: str) -> None:
    assert classify(path, b"old", b"new") is None


def test_package_json_is_flagged_only_when_what_npm_runs_changes() -> None:
    version_only = PACKAGE.replace(b"1.0.0", b"1.0.1")
    scripts = PACKAGE.replace(b'"jest"', b'"jest && curl evil"')
    postinstall = PACKAGE.replace(b'"test": "jest"', b'"test": "jest", "postinstall": "x"')
    assert classify("package.json", PACKAGE, version_only) is None
    assert classify("web/package.json", PACKAGE, scripts) == NPM
    assert classify("package.json", PACKAGE, postinstall) == NPM
    assert classify("package.json", None, PACKAGE) == NPM          # added
    assert classify("package.json", PACKAGE, None) == NPM          # deleted
    assert classify("package.json", PACKAGE, b"{not json") == NPM  # unparseable fails closed


def test_pyproject_is_flagged_only_when_build_or_tool_sections_change() -> None:
    renamed = PYPROJECT.replace(b'version = "1.0"', b'version = "1.1"')
    backend = PYPROJECT + b'build-backend = "evil.backend"\n'
    tool = PYPROJECT + b'[tool.pytest.ini_options]\naddopts = "-p evil"\n'
    assert classify("pyproject.toml", PYPROJECT, renamed) is None
    assert classify("pyproject.toml", PYPROJECT, backend) == BUILD_HOOK
    assert classify("pyproject.toml", PYPROJECT, tool) == BUILD_HOOK
    assert classify("pyproject.toml", PYPROJECT, b"[[broken") == BUILD_HOOK


@pytest.mark.parametrize("path", ["../.github/workflows/x.yml", ".github/../ci.yml",
                                  "C:/x/conftest.py", "a\\conftest.py", "/abs/setup.py", ""])
def test_unrepresentable_paths_are_never_assumed_harmless(path: str) -> None:
    assert classify(path, b"a", b"b") == HOOK


def test_the_list_is_sorted_and_skips_ordinary_files() -> None:
    assert execution_bearing([
        ("src/app.py", b"a", b"b"), ("setup.py", None, b"x"), (".husky/pre-push", b"a", None),
    ]) == [(".husky/pre-push", HOOK), ("setup.py", BUILD_HOOK)]


def _bound_change(tmp_path, edit):
    from datetime import UTC, datetime

    from backend.app.assurance.engine import contract_digest
    from backend.app.assurance.store import EvidenceStore
    from backend.app.contracts.models import DiffCoverageResult
    from backend.app.git.state import GitStateTracker
    from backend.tests.passport.test_builder import _database, _seed_change
    from backend.tests.support_kb import make_repo

    root = make_repo(tmp_path / "repo", {
        "app.py": "def run(): return 1\n",
        "package.json": PACKAGE.decode(),
    })
    database = _database(tmp_path)
    record = _seed_change(database)
    with database.connection() as connection:
        connection.execute("UPDATE changes SET repository_path = ? WHERE id = ?",
                           (str(root), str(record.id)))
    tracker = GitStateTracker()
    baseline = tracker.capture(record.id, "BASELINE", str(root), 1, 1_048_576)
    edit(root)
    tested = tracker.capture(record.id, "TESTED", str(root), 1, 1_048_576)
    store = EvidenceStore(database)
    store.save_checkpoint(baseline)
    store.save_checkpoint(tested)
    now = datetime.now(UTC)
    store.save_diff_coverage(DiffCoverageResult(
        change_id=record.id, baseline_checkpoint_id=baseline.id,
        tested_checkpoint_id=tested.id, head_sha=tested.head_sha,
        status_digest=tested.status_digest, contract_digest=contract_digest(record),
        started_at=now, completed_at=now, collector_status="COLLECTED",
        checks_passed=True, diff_exercised="NOT_APPLICABLE", freshness="CURRENT",
    ))
    from backend.app.passport.v2 import PassportV2Issuer

    return PassportV2Issuer(database).snapshot(record.id)


def test_the_passport_lists_execution_bearing_changes(tmp_path) -> None:
    from backend.tests.support_kb import write

    def edit(root):
        write(root, "app.py", "def run(): return 2\n")
        write(root, ".github/workflows/ci.yml", "on: push\n")
        write(root, "package.json", PACKAGE.replace(b'"jest"', b'"jest && node x.js"').decode())

    payload = _bound_change(tmp_path, edit)
    assert payload.runs_later == "PRESENT"
    assert [(item.path, item.category) for item in payload.execution_bearing_changes] == [
        (".github/workflows/ci.yml", CI), ("package.json", NPM)]
    assert any("2 changed file(s) make code run later" in line for line in payload.limitations)


def test_an_ordinary_change_runs_nothing_later(tmp_path) -> None:
    from backend.tests.support_kb import write

    def edit(root):
        write(root, "app.py", "def run(): return 2\n")
        write(root, "package.json", PACKAGE.replace(b"1.0.0", b"1.0.1").decode())

    payload = _bound_change(tmp_path, edit)
    assert payload.runs_later == "NONE" and payload.execution_bearing_changes == []
    assert not any("run later" in line or "Execution-bearing" in line
                   for line in payload.limitations)


def test_without_bound_checkpoints_runs_later_is_unknown(tmp_path) -> None:
    from backend.app.passport.v2 import PassportV2Issuer
    from backend.tests.passport.test_builder import _database, _seed_change

    database = _database(tmp_path)
    record = _seed_change(database)
    payload = PassportV2Issuer(database).snapshot(record.id)
    assert payload.runs_later == "UNKNOWN"
    assert any("Execution-bearing files could not be listed" in line
               for line in payload.limitations)
