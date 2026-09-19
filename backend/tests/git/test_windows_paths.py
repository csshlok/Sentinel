"""Windows path canonicalization edge cases for repository validation.

Covers the test family explicitly called out on page 24 of the project
proposal: case folding, 8.3 aliases, junctions, reparse points, and long
paths. `GitRepositoryInspector._canonical_root` relies on `Path.resolve()`
for canonicalization; these tests prove that reliance is actually correct
on this platform rather than merely assumed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.git.adapter import GitRepositoryInspector
from backend.app.git.errors import RepositoryValidationError

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only path semantics")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    _git(path, "config", "user.name", "Tester")
    _git(path, "config", "user.email", "tester@example.com")
    (path / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    return path


def test_junction_resolves_to_same_canonical_root_as_real_path(tmp_path: Path) -> None:
    """A junction to a repo must canonicalize to the same root as the real path.

    Otherwise a user could accidentally create two "different" Changes that
    both point at the same underlying repository.
    """

    real = _init_repo(tmp_path / "real_repo")
    link = tmp_path / "junction_repo"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)],
        capture_output=True,
        text=True,
        shell=False,
    )
    assert result.returncode == 0, f"mklink /J failed: {result.stderr}"

    inspector = GitRepositoryInspector()
    via_real = inspector.validate_repository(str(real))
    via_junction = inspector.validate_repository(str(link))

    assert via_junction.root == via_real.root
    assert via_junction.head_sha == via_real.head_sha
    assert via_junction == via_real


def test_case_folded_path_resolves_to_same_canonical_root(tmp_path: Path) -> None:
    """NTFS is case-insensitive but case-preserving; validation must fold consistently."""

    real = _init_repo(tmp_path / "CaseRepo")

    lower = str(real).replace("CaseRepo", "caserepo")
    upper = str(real).replace("CaseRepo", "CASEREPO")

    inspector = GitRepositoryInspector()
    canonical = inspector.validate_repository(str(real))
    via_lower = inspector.validate_repository(lower)
    via_upper = inspector.validate_repository(upper)

    assert via_lower.root == canonical.root
    assert via_upper.root == canonical.root


@pytest.mark.skip(
    reason=(
        "8.3 short-name generation is disabled system-wide on this machine "
        "(HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\"
        "NtfsDisable8dot3NameCreation == 2, confirmed via registry read; "
        "`fsutil 8dot3name query` itself requires admin rights and could not "
        "run either). No real 8.3 alias can be generated on this volume, and "
        "faking one would not prove anything about actual OS behavior."
    )
)
def test_8dot3_alias_resolves_to_same_canonical_root() -> None:
    raise AssertionError("should not run; see skip reason")


def test_long_path_repository_validates_or_fails_safely(tmp_path: Path) -> None:
    """A repo path exceeding MAX_PATH (260) must work, or fail with a typed AppError.

    It must not raise a raw/confusing OS exception.

    On this machine, `HKLM\\SYSTEM\\CurrentControlSet\\Control\\FileSystem\\
    LongPathsEnabled == 0` (confirmed via registry read), which means the OS
    itself refuses ordinary `CreateDirectory`/`CreateFile` calls beyond
    MAX_PATH: `Path.mkdir()` on a >260-char path raises `WinError 3` before
    any application code runs. Using the `\\\\?\\` long-path prefix to bypass
    that at the mkdir layer does not help either -- `git init`/`git -C` on
    this system's Git for Windows build reject the same `\\\\?\\` paths with
    "Filename too long", and a plain (non-prefixed) `Path.resolve(strict=True)`
    on the resulting directory raises `FileNotFoundError` because it isn't
    reachable without the prefix. So a *working* long-path repository cannot
    be constructed end-to-end (git + plain paths) on this machine without an
    admin-level registry change, which is out of scope for a test run.

    What this test verifies instead, without needing OS long-path support:
    `GitRepositoryInspector.validate_repository` given a real (unprefixed)
    path string longer than MAX_PATH that does not exist fails with the
    same typed, stable `RepositoryValidationError`/`INVALID_REPOSITORY_PATH`
    used for any other missing path -- i.e. `Path(...).resolve(strict=True)`
    raising `FileNotFoundError` for a long path is caught by the adapter's
    existing `except (OSError, ValueError, RuntimeError)` guard exactly like
    a short missing path, not surfaced as a raw crash.
    """

    segment = "a_long_directory_segment_name_used_to_exceed_max_path_"[:50]
    long_path = tmp_path
    while len(str(long_path)) < 300:
        long_path = long_path / segment
    assert len(str(long_path)) > 260
    assert not long_path.exists()

    inspector = GitRepositoryInspector()
    with pytest.raises(RepositoryValidationError) as excinfo:
        inspector.validate_repository(str(long_path))

    assert excinfo.value.code == "INVALID_REPOSITORY_PATH"
    assert excinfo.value.status_code == 400
