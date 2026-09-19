from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest

from backend.app.contracts.ports import DependencyPort
from backend.app.core.errors import AppError
from backend.app.dependencies import tracker as tracker_module
from backend.app.dependencies.tracker import DependencyTracker
from backend.app.git.state import GitStateTracker
from backend.tests.support_kb import git, make_repo, write

CHANGE = uuid4()
state = GitStateTracker()


def scan(repo, **kw):
    cp = state.capture(CHANGE, "cp", str(repo), 1, 1000)
    return DependencyTracker(**kw).scan(CHANGE, cp, str(repo)), cp


def by_pkg(report, package=None):
    return {(c.package, c.source_path): c for c in report.changes
            if package is None or c.package == package}


def lock(**packages):
    body = {"": {"dependencies": {name: "^1" for name in packages}}}
    for name, version in packages.items():
        body[f"node_modules/{name}"] = {"version": version}
    return json.dumps({"lockfileVersion": 3, "packages": body})


def test_conformance_and_clean_repo(tmp_path):
    repo = make_repo(tmp_path / "r", {"requirements.txt": "flask==2.0.0\n"})
    report, cp = scan(repo)
    assert isinstance(DependencyTracker(), DependencyPort)
    assert report.changes == [] and report.unsupported_ecosystems == []
    assert report.checkpoint_id == cp.id and report.change_id == CHANGE
    assert type(report).model_validate_json(report.model_dump_json()) == report


def test_python_add_remove_upgrade_downgrade_and_ranges(tmp_path):
    repo = make_repo(tmp_path / "r", {
        "requirements.txt": "flask==2.0.0\nold==1.0\ndown==3.0.0\nsame==1\nrange>=1\n"})
    write(repo, "requirements.txt",
          "flask==3.0.0\nnew==1.0\ndown==2.0.0\nsame==1\nrange>=2\n")
    report, _ = scan(repo)
    got = by_pkg(report)
    src = "requirements.txt"
    assert (got[("flask", src)].old_version, got[("flask", src)].new_version) == ("2.0.0", "3.0.0")
    assert "Major version increased." in got[("flask", src)].risk_notes
    assert got[("old", src)].new_version is None and got[("old", src)].old_version == "1.0"
    assert got[("new", src)].old_version is None
    assert "Version decreased." in got[("down", src)].risk_notes
    assert ("same", src) not in got
    assert "Unpinned version range; the resolved version can vary." in got[("range", src)].risk_notes
    assert all(c.direct is True and c.causal_attribution_available is False for c in report.changes)


def test_pyproject_and_poetry_lock_provenance(tmp_path):
    repo = make_repo(tmp_path / "r", {
        "pyproject.toml": '[project]\nname="x"\ndependencies=["a==1.0"]\n',
        "poetry.lock": '[[package]]\nname = "a"\nversion = "1.0"\n[[package]]\nname = "t"\nversion = "1"\n'})
    write(repo, "pyproject.toml", '[project]\nname="x"\ndependencies=["a==2.0"]\n')
    write(repo, "poetry.lock",
          '[[package]]\nname = "a"\nversion = "2.0"\n[[package]]\nname = "t"\nversion = "9"\n')
    got = by_pkg(scan(repo)[0])
    assert got[("a", "pyproject.toml")].direct is True
    assert got[("a", "poetry.lock")].direct is True     # declared in the sibling manifest
    assert got[("t", "poetry.lock")].direct is False    # transitive
    assert got[("t", "poetry.lock")].new_version == "9"


def test_node_manifest_lock_mismatch_and_missing_lock(tmp_path):
    repo = make_repo(tmp_path / "r", {
        "package.json": json.dumps({"dependencies": {"a": "1.0.0", "b": "1.0.0"}}),
        "package-lock.json": lock(a="1.0.0", b="1.0.0")})
    write(repo, "package.json", json.dumps({"dependencies": {"a": "2.0.0", "b": "1.0.0", "c": "1.0.0"}}))
    write(repo, "package-lock.json", lock(a="1.5.0", b="1.0.0"))
    got = by_pkg(scan(repo)[0])
    manifest_a = got[("a", "package.json")]
    assert any("Manifest pins 2.0.0 but the lockfile resolves 1.5.0" in n for n in manifest_a.risk_notes)
    assert got[("a", "package-lock.json")].direct is True
    assert ("b", "package.json") not in got
    (repo / "package-lock.json").unlink()
    got = by_pkg(scan(repo)[0])
    assert any("No package-lock.json" in n for n in got[("a", "package.json")].risk_notes)
    assert got[("a", "package-lock.json")].new_version is None    # lock deleted -> removal evidence


def test_nested_and_source_risks(tmp_path):
    repo = make_repo(tmp_path / "r", {"package.json": json.dumps({"dependencies": {}})})
    write(repo, "package.json", json.dumps({"dependencies": {
        "loc": "file:../loc", "gitp": "github:a/b", "urlp": "https://example.test/u.tgz"}}))
    got = by_pkg(scan(repo)[0])
    assert any("Non-registry source (path)" in n for n in got[("loc", "package.json")].risk_notes)
    assert any("(git)" in n for n in got[("gitp", "package.json")].risk_notes)
    assert any("(url)" in n for n in got[("urlp", "package.json")].risk_notes)


def test_transitive_lock_entries_are_labelled(tmp_path):
    body = {"lockfileVersion": 3, "packages": {
        "": {"dependencies": {"a": "1"}},
        "node_modules/a": {"version": "1.0.0"},
        "node_modules/a/node_modules/c": {"version": "3.0.0"}}}
    repo = make_repo(tmp_path / "r", {"package-lock.json": json.dumps(body)})
    body["packages"]["node_modules/a/node_modules/c"]["version"] = "4.0.0"
    write(repo, "package-lock.json", json.dumps(body))
    change = scan(repo)[0].changes[0]
    assert change.package == "c" and change.direct is False
    assert any("transitive" in n for n in change.risk_notes)


def test_workspace_and_spaced_paths(tmp_path):
    repo = make_repo(tmp_path / "r", {
        "packages/web app/package.json": json.dumps({"dependencies": {"x": "1.0.0"}}),
        "packages/api/requirements.txt": "y==1\n"})
    write(repo, "packages/web app/package.json", json.dumps({"dependencies": {"x": "2.0.0"}}))
    write(repo, "packages/api/requirements.txt", "y==2\n")
    write(repo, "packages/new/package.json", json.dumps({"dependencies": {"z": "1.0.0"}}))
    sources = {c.source_path for c in scan(repo)[0].changes}
    assert sources == {"packages/web app/package.json", "packages/api/requirements.txt",
                       "packages/new/package.json"}


def test_unsupported_and_malformed_are_reported_not_guessed(tmp_path):
    repo = make_repo(tmp_path / "r", {
        "yarn.lock": "a@1:\n  version 1\n", "Cargo.toml": "[package]\n", "go.mod": "module x\n",
        "package.json": json.dumps({"dependencies": {"a": "1.0.0"}}),
        "pyproject.toml": '[project]\ndependencies=["a==1"]\n'})
    write(repo, "yarn.lock", "changed\n")
    write(repo, "Cargo.toml", "[package]\nname='x'\n")
    write(repo, "package.json", "{ not json")
    write(repo, "pyproject.toml", "= broken")
    report, _ = scan(repo)
    assert report.changes == []
    text = "\n".join(report.unsupported_ecosystems)
    assert "node: yarn.lock (format not supported)" in text
    assert "rust: Cargo.toml (format not supported)" in text
    assert "node: package.json (malformed; not compared)" in text
    assert "python: pyproject.toml (malformed; not compared)" in text
    assert "go.mod" not in text     # unchanged unsupported files are not noise


def test_non_utf8_and_oversize_files(tmp_path):
    repo = make_repo(tmp_path / "r", {"requirements.txt": "a==1\n", "package.json": "{}"})
    (repo / "requirements.txt").write_bytes(b"\xff\xfe=bad")
    write(repo, "package.json", json.dumps({"dependencies": {"pad": "1" * 300}}))
    report, _ = scan(repo, file_limit=200)
    text = "\n".join(report.unsupported_ecosystems)
    assert "package.json (unreadable or oversized)" in text
    report, _ = scan(repo)
    assert "python: requirements.txt (malformed; not compared)" in "\n".join(report.unsupported_ecosystems)


def test_symlinked_dependency_file_is_not_followed(tmp_path):
    repo = make_repo(tmp_path / "r", {"requirements.txt": "a==1\n"})
    outside = tmp_path / "outside.txt"
    outside.write_text("secret==9\n")
    (repo / "requirements.txt").unlink()
    try:
        os.symlink(outside, repo / "requirements.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    report, _ = scan(repo)
    assert "secret" not in report.model_dump_json()
    assert any("unreadable" in item for item in report.unsupported_ecosystems)


def test_scan_is_deterministic_and_never_executes_repository_content(tmp_path):
    marker = tmp_path / "executed.txt"
    repo = make_repo(tmp_path / "r", {"package.json": json.dumps({
        "scripts": {"postinstall": f"python -c \"open(r'{marker}','w')\""},
        "dependencies": {"b": "1.0.0", "a": "1.0.0"}})})
    write(repo, "package.json", json.dumps({
        "scripts": {"postinstall": f"python -c \"open(r'{marker}','w')\""},
        "dependencies": {"a": "2.0.0", "b": "2.0.0"}}))
    first, second = scan(repo)[0], scan(repo)[0]
    assert [c.model_dump() for c in first.changes] == [c.model_dump() for c in second.changes]
    assert [c.package for c in first.changes] == ["a", "b"]
    assert not marker.exists()


def test_stale_and_foreign_checkpoints_are_refused(tmp_path):
    repo = make_repo(tmp_path / "r", {"a.txt": "1"})
    cp = state.capture(CHANGE, "cp", str(repo), 1, 100)
    write(repo, "a.txt", "2")
    git(repo, "commit", "-qam", "move")
    with pytest.raises(AppError) as info:
        DependencyTracker().scan(CHANGE, cp, str(repo))
    assert info.value.code == "DEPENDENCY_CHECKPOINT_STALE" and info.value.status_code == 409
    other = make_repo(tmp_path / "o")
    with pytest.raises(AppError) as info:
        DependencyTracker().scan(CHANGE, cp, str(other))
    assert info.value.code == "CHECKPOINT_REPOSITORY_MISMATCH"
    with pytest.raises(AppError):
        DependencyTracker().scan(CHANGE, cp, str(tmp_path / "missing"))


def test_file_count_and_change_caps(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "r", {f"p{i}/requirements.txt": "a==1\n" for i in range(4)})
    for i in range(4):
        write(repo, f"p{i}/requirements.txt", "a==2\nb==1\n")
    monkeypatch.setattr(tracker_module, "MAX_FILES", 2)
    report, _ = scan(repo)
    assert any("only 2 examined" in item for item in report.unsupported_ecosystems)
    monkeypatch.setattr(tracker_module, "MAX_FILES", 300)
    monkeypatch.setattr(tracker_module, "MAX_CHANGES", 3)
    report, _ = scan(repo)
    assert len(report.changes) == 3
    assert any("only 3 reported" in item for item in report.unsupported_ecosystems)


def test_committed_change_is_compared_from_checkpoint_head(tmp_path):
    """The baseline is the checkpoint's HEAD, so a committed edit is not drift."""

    repo = make_repo(tmp_path / "r", {"requirements.txt": "a==1\n"})
    write(repo, "requirements.txt", "a==2\n")
    git(repo, "commit", "-qam", "bump")
    report, _ = scan(repo)
    assert report.changes == []
    write(repo, "requirements.txt", "a==3\n")
    assert by_pkg(scan(repo)[0])[("a", "requirements.txt")].old_version == "2"
