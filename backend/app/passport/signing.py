"""Ed25519 signing for exported Change Passports (A.7).

Reuses the existing OS-protected `CredentialStorePort` (in production,
`WindowsCredentialStore`, the same Windows Credential Manager binding this
codebase already trusts for provider tokens) to persist this operator's
private signing key -- no new key-storage mechanism is invented here, and
the private key is never returned by any method or route this module
exposes.

Canonicalization matches the convention already established in this
codebase (`backend/app/passport/builder.py::PassportBuilder.build`'s
`canonical_digest`, `backend/app/core/journal.py::_canonical`):
`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
over the model's own `mode="json"` dump.

Explicit non-goal, matching A.7/A.9 of
`PROCESS_SUPERVISOR_AND_CONTAINER_SHARING_PLAN.md`: no other party's public
key is stored, trusted, or looked up anywhere in this module or codebase.
This is "we can sign what we already export," nothing about a second
party's access to anything, and nothing here implies a built-in transport
for the resulting artifact -- that is Part B, unimplemented.

Dependency note: this module uses the third-party `cryptography` package
for Ed25519 (`cryptography.hazmat.primitives.asymmetric.ed25519`). It is
present in this environment only as an undeclared transitive dependency of
an unrelated package (`google-auth`), not as a declared project dependency
in `pyproject.toml`. Implementing Ed25519 by hand in pure Python was
deliberately rejected -- rolling one's own asymmetric-crypto primitive is
exactly the kind of subtly-wrong security surface this project's "no safety
theater" principle warns against. Adding `cryptography` to
`pyproject.toml`'s `dependencies` needs `[SD]`'s sign-off per
`AGENT_COORDINATION.md`'s dependency-manifest rules; this module does not
edit that manifest itself.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from backend.app.contracts.models import ChangePassport, SignedPassportExport, utc_now
from backend.app.contracts.ports import CredentialStorePort

SIGNING_KEY_CREDENTIAL_NAME = "signing-key"


def canonical_passport_bytes(passport: ChangePassport) -> bytes:
    """The exact bytes that are signed and, on verification, re-derived.

    Matches the sorted-key, compact-separator JSON convention already used
    for `ChangePassport.canonical_digest` and journal-event hash chaining --
    not a new canonicalization scheme. Public so callers that need the
    exported content's own digest (e.g. the journal payload emitted for
    `PASSPORT_EXPORT_SIGNED`) hash the identical bytes that were signed,
    rather than a second, possibly-drifting canonicalization.
    """

    content = passport.model_dump(mode="json")
    return json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class SigningService:
    """Owns this operator's Ed25519 signing identity.

    The private key is generated once and persisted via the injected
    `CredentialStorePort`; every later instance backed by the same store
    loads the existing key rather than regenerating, so the signing
    identity is stable across process restarts.
    """

    def __init__(
        self,
        credential_store: CredentialStorePort,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._store = credential_store
        self._clock = clock
        self._private_key = self._load_or_create_key()

    def _load_or_create_key(self) -> Ed25519PrivateKey:
        existing = self._store.get(SIGNING_KEY_CREDENTIAL_NAME)
        if existing is not None:
            raw = base64.b64decode(existing)
            return Ed25519PrivateKey.from_private_bytes(raw)

        private_key = Ed25519PrivateKey.generate()
        raw = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self._store.put(SIGNING_KEY_CREDENTIAL_NAME, base64.b64encode(raw).decode("ascii"))
        return private_key

    def public_key(self) -> str:
        """This operator's own public key, base64-encoded raw Ed25519 bytes."""

        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    def sign(self, passport: ChangePassport) -> SignedPassportExport:
        """Sign the passport's canonical bytes with this operator's private key."""

        message = canonical_passport_bytes(passport)
        signature = self._private_key.sign(message)
        return SignedPassportExport(
            passport=passport,
            signature=base64.b64encode(signature).decode("ascii"),
            signer_public_key=self.public_key(),
            signed_at=self._clock(),
        )


def verify(bundle: SignedPassportExport, expected_public_key: str) -> bool:
    """Verify `bundle.signature` against `bundle.passport`'s canonical bytes.

    Not exposed as an API route: a recipient verifying our export is, by
    definition, not us. Exists for our own round-trip proof and for a
    future verifier to call directly (out of process/language) with a
    matching implementation of the same canonicalization.
    """

    try:
        raw_public = base64.b64decode(expected_public_key)
        public_key = Ed25519PublicKey.from_public_bytes(raw_public)
        signature = base64.b64decode(bundle.signature)
    except (ValueError, TypeError):
        return False

    message = canonical_passport_bytes(bundle.passport)
    try:
        public_key.verify(signature, message)
    except InvalidSignature:
        return False
    return True
