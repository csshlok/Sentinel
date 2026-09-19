from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.contracts.models import ChangedPathStatus
from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.errors import GitCommandError, RepositoryValidationError
from backend.tests.git.test_git_adapter import repo, git


@pytest.mark.parametrize("record", [
    "invalid\t0\ta\0", "-1\t0\ta\0", "1\t-\ta\0", "-\t1\ta\0",
    "1.2\t0\ta\0", "1\t0\ta", "1\t0\t\0old\0", "1\t0\t\0\0new\0",
    "1\t0\t../a\0", "1\t0\t/a\0", "1\t0\ta\0\0",
    "1\t0\ta\0" * 2, "short\0", "9999999999999999999\t0\ta\0",
])
def test_malformed_numstat_has_stable_error(record):
    with pytest.raises(GitCommandError) as error:
        GitRepositoryInspector._parse_numstat(record)
    assert error.value.code == "GIT_COMMAND_FAILED"
    assert record not in str(error.value)


@pytest.mark.parametrize("record", [
    "? path", "? \0", "? ../outside\0", "? /absolute\0", "? a//b\0",
    "? a/./b\0", "? a\0? a\0", "\0", "unsupported\0", "1 short\0",
    "2 short\0", "u short\0", "? a\0\0",
    "1 XX N... 100644 100644 100644 a b p\0",
    "1 X N... 100644 100644 100644 a b p\0",
    "2 R. N... 100644 100644 100644 a b R101 p\0old\0",
    "2 R. N... 100644 100644 100644 a b R100 p\0\0",
])
def test_malformed_status_has_stable_error(record):
    with pytest.raises(GitCommandError):
        GitRepositoryInspector._parse_status(record)


def test_ignored_and_empty_records():
    assert GitRepositoryInspector._parse_status("") == []
    assert GitRepositoryInspector._parse_status("! ignored\0") == []
    assert GitRepositoryInspector._parse_numstat("") == {}


def test_rename_numstat_and_literal_filename_characters():
    stats = GitRepositoryInspector._parse_numstat("2\t1\t\0old name\0new\tname\0")
    assert stats["new\tname"].additions == 2
    assert stats["new\tname"].deletions == 1
    parsed = GitRepositoryInspector._parse_status("? literal\\name\0? line\nbreak\0")
    assert parsed[0].path == "literal\\name"
    assert parsed[1].path == "line\nbreak"


def test_no_repository_mutation(repo):
    (repo / "modify.py").write_text("first\nsecond\n", encoding="utf-8")
    before = {str(p.relative_to(repo)): (p.read_bytes(), p.stat().st_mtime_ns)
              for p in repo.rglob("*") if p.is_file()}
    GitRepositoryInspector().inspect(str(repo), 1000)
    after = {str(p.relative_to(repo)): (p.read_bytes(), p.stat().st_mtime_ns)
             for p in repo.rglob("*") if p.is_file()}
    assert before == after


def test_environment_git_overrides_cannot_redirect_inspection(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "not-this-repo"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "other"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    assert GitRepositoryInspector().validate_repository(str(repo)).root == str(repo.resolve())


def test_external_diff_textconv_and_fsmonitor_do_not_execute(repo):
    marker = repo / "command-executed"
    command = "echo unsafe > command-executed"
    git(repo, "config", "core.fsmonitor", command)
    git(repo, "config", "diff.external", command)
    git(repo, "config", "diff.probe.textconv", command)
    (repo / ".gitattributes").write_text("*.py diff=probe\n", encoding="utf-8")
    (repo / "modify.py").write_text("modified\n", encoding="utf-8")
    result = GitRepositoryInspector().inspect(str(repo), 10000)
    assert "modified" in result.patch
    assert not marker.exists()


def test_content_filter_is_explicitly_unsupported_without_running_it(repo):
    marker = repo / "filter-executed"
    git(repo, "config", "filter.probe.clean", "echo unsafe > filter-executed")
    git(repo, "config", "filter.probe.required", "true")
    (repo / ".gitattributes").write_text("*.py filter=probe\n", encoding="utf-8")
    (repo / "modify.py").write_text("changed\n", encoding="utf-8")
    with pytest.raises(GitCommandError, match="content filters are unsupported"):
        GitRepositoryInspector().inspect(str(repo), 1000)
    assert not marker.exists()


def test_change_beyond_truncated_patch_is_detected(repo, monkeypatch):
    target = repo / "modify.py"
    target.write_text("first\n" + "a" * 1000 + "\n", encoding="utf-8")
    original = GitRepositoryInspector._capture_git
    patch_count = 0
    def moving(root, args, limit):
        nonlocal patch_count
        if args[0] == "diff" and "--numstat" not in args:
            patch_count += 1
            if patch_count == 2:
                target.write_text("first\n" + "b" * 1000 + "\n", encoding="utf-8")
        return original(root, args, limit)
    monkeypatch.setattr(GitRepositoryInspector, "_capture_git", staticmethod(moving))
    with pytest.raises(GitCommandError, match="changed during inspection"):
        GitRepositoryInspector().inspect(str(repo), 1)


def test_real_merge_conflict(repo):
    original_branch = git(repo, "branch", "--show-current").stdout.strip()
    git(repo, "checkout", "-b", "conflicting")
    (repo / "modify.py").write_text("side\n", encoding="utf-8")
    git(repo, "commit", "-am", "side")
    git(repo, "checkout", original_branch)
    (repo / "modify.py").write_text("main\n", encoding="utf-8")
    git(repo, "commit", "-am", "main")
    merged = subprocess.run(["git", "-C", str(repo), "merge", "conflicting"], capture_output=True)
    assert merged.returncode != 0
    result = GitRepositoryInspector().inspect(str(repo), 10000)
    assert any(item.status == ChangedPathStatus.CONFLICTED for item in result.files)


def test_unicode_filename_and_staged_then_reverted_worktree(repo):
    filename = "caf\u00e9 \u6d4b\u8bd5.py"
    (repo / filename).write_text("one\n", encoding="utf-8")
    git(repo, "add", filename)
    result = GitRepositoryInspector().inspect(str(repo), 10000)
    assert any(item.path == filename and item.staged for item in result.files)
    original = (repo / "modify.py").read_bytes()
    (repo / "modify.py").write_text("staged value\n", encoding="utf-8")
    git(repo, "add", "modify.py")
    (repo / "modify.py").write_bytes(original)
    result = GitRepositoryInspector().inspect(str(repo), 10000)
    changed = next(item for item in result.files if item.path == "modify.py")
    assert changed.staged and changed.unstaged
    assert changed.additions is None  # HEAD vs working file has no net diff.


def test_invalid_path_and_patch_limit(repo):
    with pytest.raises(RepositoryValidationError):
        GitRepositoryInspector().validate_repository("\0")
    for limit in (-1, 1_048_577, 0.5, True, None, "100"):
        with pytest.raises(GitCommandError, match="patch limit"):
            GitRepositoryInspector().inspect(str(repo), limit)


def test_metadata_limit_and_invalid_encoding(monkeypatch):
    from backend.app.execution._process import CapturedProcess
    def result(stdout=b"", truncated=False):
        return CapturedProcess(0, stdout, b"", truncated, False, False, "digest")
    monkeypatch.setattr(GitRepositoryInspector, "_capture_git", staticmethod(lambda *_: result(truncated=True)))
    with pytest.raises(GitCommandError, match="metadata exceeded"):
        GitRepositoryInspector._run_git(".", ["status"])
    monkeypatch.setattr(GitRepositoryInspector, "_capture_git", staticmethod(lambda *_: result(b"\xff")))
    with pytest.raises(GitCommandError, match="text encoding"):
        GitRepositoryInspector._run_git(".", ["status"])


def test_head_startup_failure_is_not_misreported_as_no_commits(repo, monkeypatch):
    original = GitRepositoryInspector._run_git
    def fail(root, args):
        if "--verify" in args:
            raise GitCommandError("Synthetic startup failure")
        return original(root, args)
    monkeypatch.setattr(GitRepositoryInspector, "_run_git", staticmethod(fail))
    with pytest.raises(GitCommandError, match="Synthetic startup"):
        GitRepositoryInspector().validate_repository(str(repo))


def test_unsupported_sha_has_domain_error(repo, monkeypatch):
    original = GitRepositoryInspector._run_git
    monkeypatch.setattr(GitRepositoryInspector, "_run_git", staticmethod(
        lambda root, args: "a" * 64 if "--verify" in args else original(root, args)))
    with pytest.raises(GitCommandError, match="unsupported"):
        GitRepositoryInspector().validate_repository(str(repo))


def test_git_executable_resolution_rejects_repository_and_wrappers(tmp_path, monkeypatch):
    import os
    root = tmp_path / "repo"
    external = tmp_path / "external"
    monkeypatch.setenv("PATH", os.pathsep.join([".", str(root), str(external)]))
    for found in (None, str(root / "git.exe"), str(external / "git.cmd")):
        monkeypatch.setattr("backend.app.git.adapter.shutil.which", lambda _, found=found: found)
        with pytest.raises(GitCommandError, match="could not be located"):
            GitRepositoryInspector._capture_git(str(root), ["status"], 100)


@pytest.mark.parametrize(("stage", "failure"), [
    ("config", "timeout"), ("config", "incomplete"), ("config", "truncated"),
    ("config", "exit"), ("config", "encoding"), ("config", "oserror"),
    ("ls-files", "timeout"), ("ls-files", "exit"), ("ls-files", "invalid"),
    ("ls-files", "record"),
    ("check-attr", "exit"), ("check-attr", "timeout"), ("check-attr", "invalid"),
    ("status", "timeout"), ("status", "incomplete"), ("status", "exit"),
])
def test_git_boundary_failures_are_stable_and_safe(tmp_path, monkeypatch, stage, failure):
    from dataclasses import replace
    from backend.app.execution._process import CapturedProcess
    baseline = CapturedProcess(0, b"", b"", False, False, False, "digest")
    monkeypatch.setattr("backend.app.git.adapter.shutil.which", lambda _: str(tmp_path / "git.exe"))
    monkeypatch.setenv("PATH", str(tmp_path))
    def fake(argv, **_):
        command = argv[argv.index("-C") + 2]
        result = baseline
        if command == "ls-files":
            result = replace(result, stdout=b"100644 " + b"a" * 40 + b" 0\tfile.py\0")
        elif command == "check-attr":
            result = replace(result, stdout=b"file.py\0filter\0unspecified\0")
        if command == stage:
            if failure == "oserror":
                raise OSError("sensitive-path-canary")
            result = replace(result, **{
                "timeout": {"timed_out": True}, "incomplete": {"incomplete": True},
                "truncated": {"truncated": True}, "exit": {"returncode": 128},
                "encoding": {"stdout": b"\xff\0"}, "invalid": {"stdout": b"bad"},
                "record": {"stdout": b"bad\0"},
            }[failure])
        return result
    monkeypatch.setattr("backend.app.git.adapter.capture", fake)
    with pytest.raises(GitCommandError) as error:
        GitRepositoryInspector._capture_git(str(tmp_path / "repo"), ["status"], 100)
    assert "sensitive-path-canary" not in str(error.value)


def test_status_unknown_record_and_ordinary_conflict():
    with pytest.raises(GitCommandError):
        GitRepositoryInspector._parse_status("x record\0")
    assert GitRepositoryInspector._ordinary_status("UU") == ChangedPathStatus.CONFLICTED
    assert GitRepositoryInspector._bound_utf8("\u00e9\u00e9", 3) == ("\u00e9", True)


def test_submodule_status_is_not_delegated_to_unreviewed_nested_configuration(repo, tmp_path):
    nested = tmp_path / "nested-source"
    nested.mkdir()
    subprocess.run(["git", "init", str(nested)], check=True, capture_output=True)
    git(nested, "config", "user.name", "Test")
    git(nested, "config", "user.email", "test@example.com")
    (nested / "file.py").write_text("baseline\n", encoding="utf-8")
    git(nested, "add", ".")
    git(nested, "commit", "-m", "baseline")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", str(nested), "nested")
    with pytest.raises(GitCommandError, match="Submodule inspection"):
        GitRepositoryInspector().inspect(str(repo), 100)
