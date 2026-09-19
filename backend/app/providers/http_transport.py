"""HTTP transport seam: production uses urllib, tests use a local fake."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class TransportTimeout(Exception):
    """Raised by a transport when a request times out or the network fails."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse:
        """Perform one HTTP request. Raise TransportTimeout on timeout/network failure."""


class UrllibHttpTransport:
    """Production `HttpTransport` using only the standard library."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url, data=body, headers=dict(headers), method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return HttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers),
                    body=response.read(),
                )
        except urllib.error.HTTPError as error:
            return HttpResponse(
                status_code=error.code,
                headers=dict(error.headers or {}),
                body=error.read(),
            )
        except TimeoutError as error:
            raise TransportTimeout(str(error)) from error
        except urllib.error.URLError as error:
            raise TransportTimeout(str(error.reason)) from error
