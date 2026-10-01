import os
from pathlib import Path

import pytest

from backend.app.contracts.models import VerificationRequest
from backend.app.core.errors import AppError
from backend.app.verification.validation import resolve_executable


def _request(executable: str) -> VerificationRequest:
    return VerificationRequest(executable=executable, args=[])


def test_allowed_and_present_executable_resolves(tmp_path: Path) -> None:
    resolved = resolve_executable(_request("python"), root=tmp_path)
    assert resolved


def test_disallowed_executable_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("rm"), root=tmp_path)
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"


def test_path_qualified_executable_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("./python"), root=tmp_path)
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"


def test_missing_allowlisted_executable_is_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "backend.app.execution.resolve.shutil.which", lambda _name: None
    )
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("cargo"), root=tmp_path)
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_FOUND"


def test_not_allowed_and_not_found_are_distinct_codes(tmp_path: Path) -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("bash"), root=tmp_path)
    assert excinfo.value.code != "VERIFICATION_EXECUTABLE_NOT_FOUND"


@pytest.mark.skipif(os.name != "nt", reason="PATHEXT batch resolution is Windows-specific")
def test_an_agent_tool_on_a_repository_path_entry_is_never_resolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """WR-07: a repository directory on the user's PATH cannot shadow the real tool."""

    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "cargo.cmd").write_text("@echo agent\r\n", encoding="ascii")
    real = tmp_path / "toolchain"
    real.mkdir()
    (real / "cargo.exe").write_bytes(b"MZ")
    # An activated project environment puts the repository first; cwd is the repository too.
    monkeypatch.setenv("PATH", os.pathsep.join([str(repo / "tools"), str(real),
                                                os.environ.get("PATH", "")]))
    monkeypatch.chdir(repo / "tools")
    resolved = Path(resolve_executable(_request("cargo"), root=repo))
    assert resolved == (real / "cargo.exe").resolve()
    # With only the repository entry, nothing outside it is found: refused, not shadowed.
    monkeypatch.setenv("PATH", str(repo / "tools"))
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("cargo"), root=repo)
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_FOUND"
