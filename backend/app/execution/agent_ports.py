"""What the launcher needs from the workspace and credential modules, without importing them.

``execution/`` must not depend on ``workspace/`` or ``credentials/`` (the
dependency runs the other way), so the launcher programs against these
structural Protocols. ``WorkspaceManager`` and ``CredentialBroker`` satisfy them
by shape.

A :class:`CredentialFingerprint` identifies a staged model credential by
digests only: Git blob ids of the staged bytes and SHA-256 digests of every
long JSON string value (and its common encodings). It can be persisted and
compared against a diff (:func:`contains_credential_material`) without anyone
holding the secret again. Pure module: no Win32, no process starts, no I/O.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

# JSON string values at least this long are treated as token material.
TOKEN_MIN_LENGTH = 16
# Detector bound: runs up to this many characters are searched exhaustively.
TOKEN_RUN_EXHAUSTIVE_LIMIT = 4096
_TOKEN_RUN = re.compile(rb"[A-Za-z0-9+/=_.\-]+")


def git_blob_id(data: bytes) -> str:
    """The Git (SHA-1) blob id Git would give ``data``."""

    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)


def credential_token_values(data: bytes) -> tuple[str, ...]:
    """Every JSON string value of ``data`` that is at least ``TOKEN_MIN_LENGTH`` long.

    Longest first (so a redactor replaces the longest match first). A file
    that is not JSON yields nothing; its blob ids still identify it.
    """

    try:
        document = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return ()
    values = {text for text in _string_values(document) if len(text) >= TOKEN_MIN_LENGTH}
    return tuple(sorted(values, key=lambda text: (-len(text), text)))


def _encodings(value: str) -> tuple[bytes, ...]:
    raw = value.encode("utf-8")
    return (
        raw,
        base64.b64encode(raw),
        base64.urlsafe_b64encode(raw),
        raw.hex().encode("ascii"),
    )


@dataclass(frozen=True, slots=True)
class CredentialFingerprint:
    """Digest-only identity of one staged credential file (safe to persist)."""

    kind: str
    blob_ids: tuple[str, ...]
    file_sha256: str
    token_digests: tuple[str, ...]
    token_lengths: tuple[int, ...]

    @classmethod
    def from_bytes(cls, kind: str, data: bytes) -> CredentialFingerprint:
        """Fingerprint ``data``: blob ids of it and its CRLF/LF variants, token digests."""

        lf = data.replace(b"\r\n", b"\n")
        crlf = lf.replace(b"\n", b"\r\n")
        blob_ids = tuple(dict.fromkeys(git_blob_id(item) for item in (data, lf, crlf)))
        digests: dict[str, None] = {}
        lengths: set[int] = set()
        for value in credential_token_values(data):
            for encoded in _encodings(value):
                digests[_sha256(encoded)] = None
                lengths.add(len(encoded))
        return cls(
            kind=kind, blob_ids=blob_ids, file_sha256=_sha256(data),
            token_digests=tuple(sorted(digests)), token_lengths=tuple(sorted(lengths)),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "blob_ids": list(self.blob_ids),
            "file_sha256": self.file_sha256,
            "token_digests": list(self.token_digests),
            "token_lengths": list(self.token_lengths),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CredentialFingerprint:
        return cls(
            kind=str(payload["kind"]),
            blob_ids=tuple(str(item) for item in payload.get("blob_ids") or ()),
            file_sha256=str(payload["file_sha256"]),
            token_digests=tuple(str(item) for item in payload.get("token_digests") or ()),
            token_lengths=tuple(int(item) for item in payload.get("token_lengths") or ()),
        )


@dataclass(frozen=True, slots=True)
class StagedCredential:
    """A credential the broker copied into a staged home for one run (never persisted).

    ``redaction_values`` are the token strings themselves, handed to the
    launcher's output redaction; they are excluded from ``repr``.
    """

    kind: str
    path: Path
    fingerprint: CredentialFingerprint
    staged_sha256: str
    redaction_values: tuple[str, ...] = field(default=(), repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class CredentialRevocation:
    deleted: bool
    changed_during_run: bool


def contains_credential_material(
    fingerprint: CredentialFingerprint, *, blob_ids: Iterable[str] = (), text: bytes = b"",
) -> bool:
    """Whether a blob id or a window of ``text`` matches the staged credential.

    ``text`` is split into maximal runs of ``[A-Za-z0-9+/=_.-]``. For runs up to
    ``TOKEN_RUN_EXHAUSTIVE_LIMIT`` characters every window whose length is a
    recorded token length is hashed; longer runs are checked as a whole and at
    both edges only (a documented best-effort bound). Only digests are
    compared: no raw secret is needed. Arbitrary transformations (splitting,
    compression, custom encodings) are not detected.
    """

    known_blobs = {item.lower() for item in fingerprint.blob_ids}
    if any(str(item).lower() in known_blobs for item in blob_ids):
        return True
    digests = set(fingerprint.token_digests)
    lengths = sorted(set(fingerprint.token_lengths))
    if not digests or not lengths or not text:
        return False
    shortest = lengths[0]
    for match in _TOKEN_RUN.finditer(text):
        run = match.group()
        size = len(run)
        if size < shortest:
            continue
        if size <= TOKEN_RUN_EXHAUSTIVE_LIMIT:
            for length in lengths:
                if length > size:
                    break
                for start in range(size - length + 1):
                    if _sha256(run[start:start + length]) in digests:
                        return True
        else:
            if _sha256(run) in digests:
                return True
            for length in lengths:
                if length > size:
                    break
                if (_sha256(run[:length]) in digests
                        or _sha256(run[size - length:]) in digests):
                    return True
    return False


@runtime_checkable
class WorkspaceLease(Protocol):
    """The workspace facts a launch needs (``WorkspaceRecord`` provides them)."""

    id: UUID
    profile_name: str
    package_sid: str | None
    container_path: Path | None
    workspace_path: Path | None


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Leases a Change's workspace to one run and records its outcome."""

    def ensure(
        self, change_id: UUID, source_repository: str, *, run_id: UUID,
    ) -> WorkspaceLease: ...

    def finish_run(
        self, workspace_id: UUID, run_id: UUID, *, facts: Mapping[str, object] | None,
        status: str, limitations: Sequence[str] = (),
    ) -> None: ...

    def record_credential(
        self, workspace_id: UUID, fingerprint: CredentialFingerprint,
    ) -> None: ...


@runtime_checkable
class CredentialStager(Protocol):
    """Stages a model credential into a staged home and guarantees its removal."""

    def stage_agent_credential(
        self, change_id: UUID, kind: str, home: Path,
    ) -> StagedCredential | None: ...

    def revoke_staged_credential(self, staged: StagedCredential) -> CredentialRevocation: ...

    def purge_staged_credentials(self, home: Path) -> bool: ...
