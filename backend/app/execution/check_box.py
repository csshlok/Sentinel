"""Disposable confined check boxes: one AppContainer profile per check run.

A box is ``sentinel.check.<run-id>``. Its ``check_runs`` row is written
(CREATING) before the profile exists; the tree copy, the runtime ACEs and the
profile are all removed by ``close()``, and a DB-driven sweep at startup
finishes any row that is not CLEANED. The sweep only ever touches profiles,
folders and runtime entries its own rows name.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.app.contracts.models import JournalEventType, utc_now
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.execution import acl, appcontainer
from backend.app.execution.check_repository import (
    CheckRunRecord,
    CheckRunRepository,
    CheckRunState,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_PROFILE_PREFIX = "sentinel.check."
# Box-owned folders under the container folder (removed before the profile is deleted).
CONTAINER_SUBDIRECTORIES = ("tree", "scratch", "Temp")
_REMOVE_ATTEMPTS = 6
_REMOVE_BACKOFF_SECONDS = 0.25
_TRANSIENT_WINERRORS = frozenset({5, 32})


def check_box_cleanup_failed(reason: str) -> AppError:
    return AppError(
        "CHECK_BOX_CLEANUP_FAILED",
        "The confined check box could not be fully removed; it is recorded for the sweep.",
        status_code=500,
        details={"reason": reason},
    )


# ---------------------------------------------------------------------- platform seam


@dataclass(frozen=True, slots=True)
class BoxPlatform:
    """The Windows operations a box uses; unit tests substitute fakes."""

    derive_package_sid: Callable[[str], str] = appcontainer.derive_package_sid
    ensure_profile: Callable[..., Any] = appcontainer.ensure_profile
    delete_profile: Callable[[str], None] = appcontainer.delete_profile
    profile_exists: Callable[[str], bool] = appcontainer.profile_exists
    container_folder: Callable[[str], Path] = appcontainer.container_folder
    local_appdata: Callable[[], Path] = appcontainer.local_appdata_known_folder
    base_environment: Callable[..., dict[str, str]] = appcontainer.base_environment
    spawn: Callable[..., Any] = appcontainer.spawn_appcontainer_supervised
    grant: Callable[..., None] = acl.grant_package_read
    revoke: Callable[..., None] = acl.revoke_package_read
    remove_tree: Callable[[str | Path], None] = appcontainer.remove_tree_no_follow


@dataclass(frozen=True, slots=True)
class SweepReport:
    cleaned: tuple[UUID, ...] = ()
    failed: tuple[tuple[UUID, str], ...] = ()


def _same_path(left: str | Path, right: str | Path) -> bool:
    return (os.path.normcase(os.path.abspath(left))
            == os.path.normcase(os.path.abspath(right)))


# ---------------------------------------------------------------------- manager


class CheckBoxes:
    """Opens confined check boxes and owns their persistence, journal and cleanup."""

    def __init__(
        self, database: Database, *, journal: JournalWriter | None = None,
        profile_prefix: str = DEFAULT_PROFILE_PREFIX, runtime_root: str | Path | None = None,
        platform: BoxPlatform | None = None, clock: Callable[[], datetime] = utc_now,
    ) -> None:
        appcontainer.validate_profile_name(profile_prefix + "0" * 32)
        self.repository = CheckRunRepository(database)
        self._journal = journal
        self._prefix = profile_prefix
        self._runtime_root = None if runtime_root is None else Path(runtime_root)
        self._platform = platform or BoxPlatform()
        self._clock = clock
        # Boxes open in THIS process; the sweep never touches them.
        self._live: set[UUID] = set()

    # ------------------------------------------------------------------ persistence

    def _save(
        self, record: CheckRunRecord, expected: CheckRunState, *,
        event: JournalEventType | None = None, payload: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> CheckRunRecord:
        """Persist ``record`` with ``changes`` (compare-and-set on ``expected``).

        With ``event`` (and a journal) the row update and the journal event
        commit in ONE transaction. The append is skipped, never failed, when the
        Change row no longer exists (the check row outlives its Change).
        """

        updated = replace(record, updated_at=self._clock(), **changes)
        if event is None or self._journal is None:
            return self.repository.update(updated, expected_state=expected)
        with self.repository.database.connection(immediate=True) as connection:
            self.repository.update(updated, expected_state=expected, connection=connection)
            exists = connection.execute(
                "SELECT 1 FROM changes WHERE id = ?", (str(record.change_id),)
            ).fetchone()
            if exists is not None:
                self._journal.append(
                    record.change_id, event, subject_type="check_run", subject_id=record.id,
                    payload=dict(payload or {}), connection=connection,
                )
        return updated

    # ------------------------------------------------------------------ cleanup

    def _packages_folder(self, record: CheckRunRecord) -> Path:
        return self._platform.local_appdata() / "Packages" / record.profile_name

    def _remove_with_retries(self, target: Path) -> None:
        for attempt in range(1, _REMOVE_ATTEMPTS + 1):
            try:
                self._platform.remove_tree(target)
                return
            except OSError as exc:
                transient = (isinstance(exc, PermissionError)
                             or getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS)
                if not transient or attempt == _REMOVE_ATTEMPTS:
                    raise
                time.sleep(_REMOVE_BACKOFF_SECONDS * attempt)

    def _revoke_grants(self, record: CheckRunRecord, problems: list[str]) -> None:
        for grant in record.runtime_grants:
            if not os.path.lexists(grant.path):
                continue  # the cache entry is gone, so no ACE remains on it
            try:
                self._platform.revoke(grant.path, record.package_sid,
                                      allowed_root=self._runtime_root)
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else type(exc).__name__
                problems.append(f"could not revoke a runtime grant ({code})")

    def _remove_box(self, record: CheckRunRecord, problems: list[str]) -> bool:
        """Revoke ACEs, remove box folders no-follow, delete the profile; True when all gone."""

        self._revoke_grants(record, problems)
        packages = self._packages_folder(record)
        container = packages / "AC"
        for name in CONTAINER_SUBDIRECTORIES:
            target = container / name
            if os.path.lexists(target):
                try:
                    self._remove_with_retries(target)
                except OSError as exc:
                    problems.append(f"could not remove {name} ({type(exc).__name__})")
        if problems:
            return False
        try:
            self._platform.delete_profile(record.profile_name)
        except AppError as exc:
            problems.append(f"profile delete failed ({exc.details.get('hresult')})")
            return False
        if os.path.lexists(packages):
            try:
                self._remove_with_retries(packages)
            except OSError as exc:
                problems.append(f"could not remove the profile folder ({type(exc).__name__})")
        return (not os.path.lexists(packages)
                and not self._platform.profile_exists(record.profile_name))

    def cleanup(self, run_id: UUID) -> CheckRunRecord:
        """Remove the box of ``run_id``; idempotent for CLEANED, CLEANUP_FAILED on any failure."""

        record = self.repository.get(run_id)
        if record is None:
            raise AppError("CHECK_RUN_NOT_FOUND", "The check run does not exist.",
                           status_code=404, details={"check_run_id": str(run_id)})
        if record.state == CheckRunState.CLEANED:
            return record
        problems: list[str] = []
        try:
            removed = self._remove_box(record, problems)
        except Exception as exc:  # any failure must end CLEANUP_FAILED, never silent
            code = exc.code if isinstance(exc, AppError) else type(exc).__name__
            problems.append(f"cleanup could not run ({code})")
            removed = False
        if removed and not problems:
            return self._save(record, record.state, state=CheckRunState.CLEANED)
        if not problems:
            problems.append("the profile folder or mapping still exists")
        LOGGER.warning("check run %s cleanup failed (was %s)", record.id, record.state.value)
        self._save(record, record.state, state=CheckRunState.CLEANUP_FAILED)
        raise check_box_cleanup_failed("; ".join(problems))

    def sweep(self, *, live_run_ids: Collection[UUID] | None = None) -> SweepReport:
        """Finish every check row recorded in THIS database that is not CLEANED.

        Driven only by ``repository.list_unclean()``: Packages folders and the
        AppContainer registry are never enumerated. Boxes open in this process
        (``live_run_ids``, default: this manager's open boxes) are skipped.
        """

        live = set(self._live if live_run_ids is None else live_run_ids)
        cleaned: list[UUID] = []
        failed: list[tuple[UUID, str]] = []
        for record in self.repository.list_unclean():
            if record.id in live:
                continue
            try:
                self.cleanup(record.id)
                LOGGER.info("sweep: check run %s cleaned (was %s)", record.id,
                            record.state.value)
                cleaned.append(record.id)
            except Exception as exc:  # collected, never raised: one row must not stop the rest
                reason = (str(exc.details.get("reason") or exc.code)
                          if isinstance(exc, AppError) else type(exc).__name__)
                LOGGER.warning("sweep: check run %s failed (%s)", record.id, reason)
                failed.append((record.id, reason))
        return SweepReport(cleaned=tuple(cleaned), failed=tuple(failed))
