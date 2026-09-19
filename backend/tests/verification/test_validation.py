import pytest

from backend.app.contracts.models import VerificationRequest
from backend.app.core.errors import AppError
from backend.app.verification.validation import resolve_executable


def _request(executable: str) -> VerificationRequest:
    return VerificationRequest(executable=executable, args=[])


def test_allowed_and_present_executable_resolves() -> None:
    resolved = resolve_executable(_request("python"))
    assert resolved


def test_disallowed_executable_is_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("rm"))
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"


def test_path_qualified_executable_is_rejected() -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("./python"))
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_ALLOWED"


def test_missing_allowlisted_executable_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "backend.app.verification.validation.shutil.which", lambda _name: None
    )
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("cargo"))
    assert excinfo.value.code == "VERIFICATION_EXECUTABLE_NOT_FOUND"


def test_not_allowed_and_not_found_are_distinct_codes() -> None:
    with pytest.raises(AppError) as excinfo:
        resolve_executable(_request("bash"))
    assert excinfo.value.code != "VERIFICATION_EXECUTABLE_NOT_FOUND"
