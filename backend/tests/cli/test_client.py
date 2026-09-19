import pytest

from backend.app.cli.client import ApiClient, ApiConnectionError, ApiError
from backend.app.providers.http_transport import TransportTimeout
from backend.tests.providers.fakes import FakeHttpTransport, json_response


def test_successful_request_returns_parsed_json() -> None:
    transport = FakeHttpTransport([json_response(201, {"id": "abc", "title": "Test"})])
    client = ApiClient("http://127.0.0.1:8000", transport=transport)

    result = client.create_change("Test", "intent", "C:\\repo")

    assert result == {"id": "abc", "title": "Test"}
    assert transport.calls[0]["headers"]["Content-Type"] == "application/json"


def test_error_envelope_raises_api_error_with_code() -> None:
    transport = FakeHttpTransport(
        [json_response(404, {"error": {"code": "CHANGE_NOT_FOUND", "message": "no", "details": {}}})]
    )
    client = ApiClient("http://127.0.0.1:8000", transport=transport)

    with pytest.raises(ApiError) as excinfo:
        client.get_change("00000000-0000-0000-0000-000000000000")
    assert excinfo.value.code == "CHANGE_NOT_FOUND"
    assert excinfo.value.status_code == 404


def test_timeout_raises_connection_error() -> None:
    transport = FakeHttpTransport([TransportTimeout("boom")])
    client = ApiClient("http://127.0.0.1:8000", transport=transport)

    with pytest.raises(ApiConnectionError):
        client.capabilities()


def test_no_content_response_returns_none() -> None:
    from backend.app.providers.http_transport import HttpResponse

    transport = FakeHttpTransport([HttpResponse(status_code=204, headers={}, body=b"")])
    client = ApiClient("http://127.0.0.1:8000", transport=transport)

    assert client.revoke_delegation("00000000-0000-0000-0000-000000000000") is None


def test_idempotency_key_header_is_sent() -> None:
    transport = FakeHttpTransport([json_response(201, {"id": "abc"})])
    client = ApiClient("http://127.0.0.1:8000", transport=transport)

    client.create_change("Test", "intent", "C:\\repo", idempotency_key="key-1")

    assert transport.calls[0]["headers"]["Idempotency-Key"] == "key-1"
