"""SQLite lifecycle, ordered migrations, and transaction boundaries."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from backend.migrations import LATEST_SCHEMA_VERSION, MIGRATIONS


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(immediate=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            if applied and max(applied) > LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    "Database schema is newer than this application supports."
                )
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                migration.apply(connection)
                connection.execute(
                    """
                    INSERT INTO schema_migrations (version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        migration.version,
                        migration.name,
                        datetime.now(UTC).isoformat(),
                    ),
                )

    def schema_version(self) -> int:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"]) if row is not None else 0

    @contextmanager
    def connection_or(
        self, connection: sqlite3.Connection | None, *, immediate: bool = False
    ) -> Iterator[sqlite3.Connection]:
        """Use an already-open transaction if the caller supplied one, else open one.

        Lets a repository write and a paired `JournalWriter.append` share one
        atomic transaction when a caller composes them (commit or roll back
        together), while every existing call site that does not pass a
        connection keeps opening its own short transaction exactly as before.
        When `connection` is given, this method does not commit, roll back,
        or close it -- that stays the owning caller's responsibility.
        """

        if connection is not None:
            yield connection
            return
        with self.connection(immediate=immediate) as new_connection:
            yield new_connection

    @contextmanager
    def connection(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
