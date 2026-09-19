"""In-memory `CredentialStorePort` fake for tests and non-Windows development."""

from __future__ import annotations


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def put(self, key: str, secret: str) -> None:
        self._secrets[key] = secret

    def get(self, key: str) -> str | None:
        return self._secrets.get(key)

    def delete(self, key: str) -> bool:
        return self._secrets.pop(key, None) is not None
