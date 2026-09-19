"""A scriptable, local `HttpTransport` fake. No network, no real credential."""

from __future__ import annotations

from collections.abc import Mapping

from backend.app.providers.http_transport import HttpResponse


class FakeHttpTransport:
    def __init__(self, queue: list[HttpResponse | Exception]) -> None:
        self._queue = list(queue)
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse:
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body}
        )
        if not self._queue:
            raise AssertionError("FakeHttpTransport queue exhausted")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def json_response(status_code: int, payload: object, headers: dict | None = None) -> HttpResponse:
    import json

    return HttpResponse(
        status_code=status_code,
        headers=headers or {},
        body=json.dumps(payload).encode("utf-8"),
    )
