"""Product version read from installed package metadata, the release source of truth."""

from __future__ import annotations

from importlib.metadata import version


def product_version() -> str:
    return version("change-assurance")
