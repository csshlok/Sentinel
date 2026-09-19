"""In-memory `CredentialStorePort` fake for tests and non-Windows development."""

from __future__ import annotations


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def set_secret(self, name: str, value: str) -> None:
        self._secrets[name] = value

    def get_secret(self, name: str) -> str | None:
        return self._secrets.get(name)

    def delete_secret(self, name: str) -> None:
        self._secrets.pop(name, None)
