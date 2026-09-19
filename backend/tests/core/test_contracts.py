from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.contracts.models import (
    ChangeCreateRequest,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
)


def test_change_request_strips_title_and_intent() -> None:
    request = ChangeCreateRequest(
        title="  Review auth change  ",
        intent="  Confirm the token change  ",
        repository_path=" C:\\work\\repo ",
    )

    assert request.title == "Review auth change"
    assert request.intent == "Confirm the token change"
    assert request.repository_path == "C:\\work\\repo"


def test_verification_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate(
            {"executable": "pytest", "args": [], "shell": True}
        )


def test_verification_result_round_trips_json() -> None:
    now = datetime.now(UTC)
    result = VerificationResult(
        executable="pytest",
        args=["-q"],
        status=VerificationStatus.PASSED,
        exit_code=0,
        duration_ms=12,
        stdout="1 passed",
        stderr="",
        started_at=now,
        completed_at=now,
    )

    assert VerificationResult.model_validate_json(result.model_dump_json()) == result

