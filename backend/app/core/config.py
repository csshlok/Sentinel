"""Local API configuration with bounded, explicit defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.evidence_store import default_database_path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    ui_origin: str = "http://localhost:5173"
    patch_limit_bytes: int = 1_048_576
    verification_output_limit_bytes: int = 262_144
    list_limit: int = 100
    api_token: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        configured = os.environ.get("CHANGE_ASSURANCE_DB_PATH")
        database_path = (
            Path(configured) if configured else default_database_path(os.environ)
        ).resolve()
        return cls(
            database_path=database_path,
            ui_origin=os.environ.get(
                "CHANGE_ASSURANCE_UI_ORIGIN", "http://localhost:5173"
            ),
            api_token=os.environ.get("CHANGE_ASSURANCE_API_TOKEN"),
        )

