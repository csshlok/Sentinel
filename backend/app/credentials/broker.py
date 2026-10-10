"""Issues short-lived internal grants and gates access to durable secrets.

Implements `backend.app.contracts.ports.CredentialBrokerPort`. The
durable provider secret lives only in a `CredentialStorePort`
implementation. `resolve_secret` is the single boundary where that
secret leaves the store, and only for a grant that is present,
unrevoked, unexpired, and scoped to the request. No other method on
this class or on `CredentialGrant` ever exposes the raw secret.

Staged agent credentials (D-06) follow the same boundary: this class is
the only code that reads an agent's model credential file (for
``claude``, ``~/.claude/.credentials.json``; for ``codex``,
``~/.codex/auth.json``). `stage_agent_credential`
copies it into one run's staged home (exclusive create, journaled
without secret material before it is handed out),
`revoke_staged_credential` deletes it when the run ends (never copying
anything back), and `purge_staged_credentials` removes a leftover one
during the workspace sweep. The launcher only ever receives digests and
the redaction values it needs to scrub the run's output.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import time
import types
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath
from uuid import UUID, uuid4

from backend.app.contracts.models import CredentialGrant, JournalEventType
from backend.app.contracts.ports import CredentialStorePort
from backend.app.credentials.errors import (
    agent_credential_staging_failed,
    agent_credential_unsupported,
    grant_denied,
    grant_not_found,
    provider_secret_not_configured,
)
from backend.app.core.errors import AppError
from backend.app.core.journal import JournalWriter
from backend.app.execution.agent_ports import (
    CredentialFingerprint,
    CredentialRevocation,
    StagedCredential,
    credential_token_values,
)

# Where each agent credential kind lives inside a staged home.
AGENT_CREDENTIAL_DESTINATIONS: Mapping[str, PurePath] = types.MappingProxyType({
    "claude-oauth-file": PurePath(".claude", ".credentials.json"),
    "codex-auth-file": PurePath(".codex", "auth.json"),
})
_AGENT_CREDENTIAL_PROVIDERS = types.MappingProxyType({
    "claude-oauth-file": "anthropic", "codex-auth-file": "openai",
})
AGENT_CREDENTIAL_MAX_BYTES = 1_048_576
_DELETE_ATTEMPTS = 5
_DELETE_BACKOFF_SECONDS = 0.2
_O_BINARY = getattr(os, "O_BINARY", 0)


def _default_agent_credential_sources() -> dict[str, Path]:
    return {
        "claude-oauth-file": Path.home() / ".claude" / ".credentials.json",
        "codex-auth-file": _codex_home() / "auth.json",
    }


def _codex_home() -> Path:
    """Where the host's Codex keeps auth.json: ``CODEX_HOME`` when set (as Codex itself does), else ``~/.codex``."""

    configured = os.environ.get("CODEX_HOME")
    return Path(configured) if configured else Path.home() / ".codex"


def _is_reparse(path: Path) -> bool:
    info = os.lstat(path)
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(info.st_mode)


def _real_directory(path: Path) -> bool:
    try:
        return not _is_reparse(path) and stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _read_bounded(path: Path) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(AGENT_CREDENTIAL_MAX_BYTES + 1)
    if len(data) > AGENT_CREDENTIAL_MAX_BYTES:
        raise agent_credential_staging_failed("the credential file is too large")
    return data


def _unlink_with_retries(path: Path) -> None:
    """Remove the entry ``path`` itself (a file or a link, never a link target)."""

    for attempt in range(1, _DELETE_ATTEMPTS + 1):
        try:
            if not os.path.lexists(path):
                return
            info = os.lstat(path)
            is_directory = bool(getattr(info, "st_file_attributes", 0)
                                & stat.FILE_ATTRIBUTE_DIRECTORY)
            reparse = _is_reparse(path)
            if is_directory and reparse:
                os.rmdir(path)  # a directory link: removes the link only
            elif reparse:
                os.unlink(path)  # a file link: never chmod through it
            else:
                try:
                    os.unlink(path)
                except PermissionError:
                    os.chmod(path, stat.S_IWRITE)
                    os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == _DELETE_ATTEMPTS:
                raise
            time.sleep(_DELETE_BACKOFF_SECONDS * attempt)


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _provider_from_scopes(scopes: Sequence[str]) -> str:
    first = scopes[0]
    return first.split(".", 1)[0] if "." in first else first


class CredentialBroker:
    """Implements `CredentialBrokerPort`."""

    def __init__(
        self,
        store: CredentialStorePort,
        *,
        clock: Callable[[], datetime] = _default_clock,
        journal: JournalWriter | None = None,
        grant_lookup: Callable[[UUID], CredentialGrant | None] | None = None,
        agent_credential_sources: Mapping[str, Path] | None = None,
    ) -> None:
        self.store = store
        # Resolved lazily at stage time so constructing a broker never looks at
        # the user's home directory.
        self._agent_credential_sources = (
            dict(agent_credential_sources) if agent_credential_sources is not None else None)
        self._clock = clock
        self._grants: dict[UUID, CredentialGrant] = {}
        self._journal = journal
        # Grants are durably persisted by `CredentialGrantRepository`
        # (composition-layer, `[SD]`-owned), but this broker previously
        # consulted only its own in-process `_grants` cache -- so every
        # grant became unreachable to `revoke`/`resolve_secret` the moment
        # the process restarted, even though it was still visible through
        # `GET`-style lookups backed by that repository. `grant_lookup`
        # (typically `CredentialGrantRepository.get`) is the durable source
        # of truth when supplied; the in-memory cache remains for callers
        # (mainly tests) that construct this broker standalone.
        self._grant_lookup = grant_lookup

    def store_provider_secret(self, provider: str, token: str) -> None:
        self.store.put(self._secret_key(provider), token)

    def revoke_provider_secret(self, provider: str) -> None:
        self.store.delete(self._secret_key(provider))

    def issue_grant(
        self,
        actor_id: UUID,
        change_id: UUID,
        scopes: list[str],
        ttl_seconds: int,
    ) -> CredentialGrant:
        now = self._clock()
        grant = CredentialGrant(
            id=uuid4(),
            actor_id=actor_id,
            change_id=change_id,
            provider=_provider_from_scopes(scopes),
            scopes=list(scopes),
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._grants[grant.id] = grant
        return grant

    def _get_grant(self, grant_id: UUID) -> CredentialGrant | None:
        if self._grant_lookup is not None:
            durable = self._grant_lookup(grant_id)
            if durable is not None:
                return durable
        return self._grants.get(grant_id)

    def revoke(self, grant_id: UUID) -> CredentialGrant:
        grant = self._get_grant(grant_id)
        if grant is None:
            raise grant_not_found(str(grant_id))
        if grant.revoked_at is not None:
            return grant
        revoked = grant.model_copy(update={"revoked_at": self._clock()})
        self._grants[grant_id] = revoked
        return revoked

    def get_grant(self, grant_id: UUID) -> CredentialGrant | None:
        return self._get_grant(grant_id)

    def resolve_secret(self, grant_id: UUID, *, scope: str) -> str:
        grant = self._get_grant(grant_id)
        if grant is None:
            raise grant_not_found(str(grant_id))
        now = self._clock()
        if grant.revoked_at is not None or now >= grant.expires_at:
            raise grant_denied(str(grant_id))
        if scope not in grant.scopes:
            raise grant_denied(str(grant_id))
        secret = self.store.get(self._secret_key(grant.provider))
        if secret is None:
            raise provider_secret_not_configured(grant.provider)
        # The single highest-risk emission point in the whole journal (A.5):
        # the payload carries only {grant_id, scope, provider} -- exactly the
        # fields available *without* touching `secret` -- so the raw value
        # can never reach `journal_events.payload_json`. See
        # backend/tests/credentials/test_broker.py's canary-secret test.
        if self._journal is not None:
            self._journal.append(
                grant.change_id, JournalEventType.CREDENTIAL_SECRET_RESOLVED,
                actor_id=grant.actor_id, subject_type="credential_grant",
                subject_id=grant.id,
                payload={"grant_id": str(grant.id), "scope": scope, "provider": grant.provider},
            )
        return secret

    @staticmethod
    def _secret_key(provider: str) -> str:
        return f"provider:{provider}"

    # -- staged agent credentials (D-06) --------------------------------------

    def _agent_source(self, kind: str) -> Path:
        sources = (self._agent_credential_sources
                   if self._agent_credential_sources is not None
                   else _default_agent_credential_sources())
        source = sources.get(kind)
        if source is None:
            raise agent_credential_unsupported(kind)
        return Path(source)

    def stage_agent_credential(
        self, change_id: UUID, kind: str, home: Path,
    ) -> StagedCredential | None:
        """Copy the ``kind`` credential into ``home`` for one run; None if there is none.

        The destination must not exist yet (exclusive create) and neither the
        home nor its ``.claude`` directory may be a link. The release is
        journaled (provider, scope, delivery, kind only) before the credential
        is returned; if that fails the staged file is deleted and staging fails.
        """

        destination_path = AGENT_CREDENTIAL_DESTINATIONS.get(kind)
        if destination_path is None:
            raise agent_credential_unsupported(kind)
        source = self._agent_source(kind)
        try:
            data = _read_bounded(source)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise agent_credential_staging_failed(
                f"the credential source could not be read ({type(exc).__name__})") from exc
        home_path = Path(home)
        destination = home_path.joinpath(*destination_path.parts)
        parent = destination.parent
        if not _real_directory(home_path):
            raise agent_credential_staging_failed("the staged home is not a real directory")
        if not os.path.lexists(parent):
            try:
                parent.mkdir(parents=False)
            except OSError as exc:
                raise agent_credential_staging_failed(
                    f"the staged credential directory could not be created ({type(exc).__name__})"
                ) from exc
        if not _real_directory(parent):
            raise agent_credential_staging_failed(
                "the staged credential directory is not a real directory")
        if os.path.lexists(destination):
            raise agent_credential_staging_failed("the staged credential destination exists")
        created = False
        try:
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
            created = True
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            staged = StagedCredential(
                kind=kind, path=destination,
                fingerprint=CredentialFingerprint.from_bytes(kind, data),
                staged_sha256=hashlib.sha256(data).hexdigest(),
                redaction_values=credential_token_values(data),
            )
            if self._journal is not None:
                self._journal.append(
                    change_id, JournalEventType.CREDENTIAL_SECRET_RESOLVED,
                    subject_type="agent_credential",
                    payload={
                        "provider": _AGENT_CREDENTIAL_PROVIDERS.get(kind, kind),
                        "scope": "agent.run",
                        "delivery": "staged_home_file",
                        "kind": kind,
                    },
                )
            return staged
        except BaseException as exc:
            if created:
                try:
                    _unlink_with_retries(destination)
                except OSError:
                    pass
            if isinstance(exc, AppError) and exc.code == "AGENT_CREDENTIAL_STAGING_FAILED":
                raise
            if isinstance(exc, Exception):
                reason = ("the destination already exists"
                          if isinstance(exc, FileExistsError)
                          or getattr(exc, "errno", None) == errno.EEXIST
                          else f"staging failed ({type(exc).__name__})")
                raise agent_credential_staging_failed(reason) from exc
            raise

    def revoke_staged_credential(self, staged: StagedCredential) -> CredentialRevocation:
        """Delete the staged file; report whether it changed during the run.

        Never writes the source and never copies anything back (research
        Pitfall 10). A home or ``.claude`` directory that became a link is not
        followed: the file is then reported as not deleted, and the next
        staged-home rebuild or the sweep removes the home without following it.
        """

        path = Path(staged.path)
        for directory in (path.parent, path.parent.parent):
            if os.path.lexists(directory) and not _real_directory(directory):
                return CredentialRevocation(deleted=False, changed_during_run=True)
        changed = False
        if os.path.lexists(path):
            try:
                if _is_reparse(path) or not stat.S_ISREG(os.lstat(path).st_mode):
                    changed = True
                else:
                    changed = hashlib.sha256(_read_bounded(path)).hexdigest() != staged.staged_sha256
            except (OSError, AppError):
                changed = True
            try:
                _unlink_with_retries(path)
            except OSError:
                pass
        return CredentialRevocation(deleted=not os.path.lexists(path),
                                    changed_during_run=changed)

    def purge_staged_credentials(self, home: Path) -> bool:
        """Remove every staged credential under ``home`` (sweep); True when none remains.

        Links are never followed: if ``home`` or a credential directory is a
        link, nothing is deleted through it (the caller removes the home as a
        link), and that counts as none remaining here.
        """

        home_path = Path(home)
        if not os.path.lexists(home_path) or not _real_directory(home_path):
            return True
        clean = True
        for relative in AGENT_CREDENTIAL_DESTINATIONS.values():
            target = home_path.joinpath(*relative.parts)
            if not os.path.lexists(target.parent) or not _real_directory(target.parent):
                continue
            try:
                _unlink_with_retries(target)
            except OSError:
                clean = False
            if os.path.lexists(target):
                clean = False
        return clean
