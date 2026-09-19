"""Narrow port for durable secret storage, kept out of ordinary data models."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialStorePort(Protocol):
    def set_secret(self, name: str, value: str) -> None:
        """Persist a secret value, replacing any prior value for `name`."""

    def get_secret(self, name: str) -> str | None:
        """Return the stored secret for `name`, or None if absent."""

    def delete_secret(self, name: str) -> None:
        """Remove the stored secret for `name`. A no-op if already absent."""
