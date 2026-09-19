"""Local API configuration with bounded, explicit defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    ui_origin: str = "http://localhost:5173"
    patch_limit_bytes: int = 1_048_576
    verification_output_limit_bytes: int = 262_144
    list_limit: int = 100

    @classmethod
    def from_environment(cls) -> "Settings":
        database_path = Path(
            os.environ.get(
                "CHANGE_ASSURANCE_DB_PATH",
                str(Path.cwd() / ".change-assurance" / "change_assurance.sqlite3"),
            )
        ).resolve()
        return cls(
            database_path=database_path,
            ui_origin=os.environ.get(
                "CHANGE_ASSURANCE_UI_ORIGIN", "http://localhost:5173"
            ),
        )

