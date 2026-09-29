"""Public security guidance must expose a reporting route and boundary limits."""

from __future__ import annotations

from pathlib import Path


def test_security_guidance_has_reporting_route_and_honest_limits() -> None:
    root = Path(__file__).resolve().parents[3]
    text = (root / "SECURITY.md").read_text(encoding="utf-8")
    assert "https://github.com/csshlok/Sentinel/security/advisories/new" in text
    assert "same user" in text and "DPAPI" in text
    assert "restricted token" in text and "does not isolate filesystem or network" in text
    assert "UNKNOWN" in text and "STALE" in text
