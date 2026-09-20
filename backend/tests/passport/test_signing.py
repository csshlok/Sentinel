"""Real Ed25519 round-trip coverage for `backend.app.passport.signing` (A.7).

No mocked crypto: a real keypair signs a real `ChangePassport` (built the
same way `backend/tests/passport/test_builder.py` does), and verification
is checked for correctness (passes), tamper-detection (fails), and
wrong-key rejection (fails) against real signature bytes.
"""

from __future__ import annotations

from backend.app.credentials.memory_store import InMemoryCredentialStore
from backend.app.identity.repository import DelegationRepository
from backend.app.passport.builder import PassportBuilder
from backend.app.passport.signing import SigningService, verify
from backend.tests.passport.test_builder import _database, _seed_change


def _real_passport(tmp_path):
    database = _database(tmp_path)
    change = _seed_change(database)
    builder = PassportBuilder(database, DelegationRepository(database))
    return builder.build(change)


def test_sign_then_verify_with_the_correct_public_key_passes(tmp_path) -> None:
    passport = _real_passport(tmp_path)
    signing = SigningService(InMemoryCredentialStore())

    bundle = signing.sign(passport)

    assert verify(bundle, signing.public_key()) is True


def test_tampering_the_passport_after_signing_fails_verification(tmp_path) -> None:
    passport = _real_passport(tmp_path)
    signing = SigningService(InMemoryCredentialStore())
    bundle = signing.sign(passport)

    tampered_passport = passport.model_copy(update={"limitations": ["tampered"]})
    tampered_bundle = bundle.model_copy(update={"passport": tampered_passport})

    assert verify(tampered_bundle, signing.public_key()) is False


def test_verifying_with_a_different_public_key_fails(tmp_path) -> None:
    passport = _real_passport(tmp_path)
    signing = SigningService(InMemoryCredentialStore())
    other_signing = SigningService(InMemoryCredentialStore())
    bundle = signing.sign(passport)

    assert verify(bundle, other_signing.public_key()) is False


def test_the_signing_key_is_persisted_and_stable_across_restarts(tmp_path) -> None:
    store = InMemoryCredentialStore()

    first = SigningService(store)
    # A fresh instance backed by the same underlying store simulates a
    # process restart: the key must be loaded, not regenerated.
    second = SigningService(store)

    assert first.public_key() == second.public_key()


def test_the_private_key_never_appears_in_the_signed_export_or_public_key(
    tmp_path,
) -> None:
    passport = _real_passport(tmp_path)
    store = InMemoryCredentialStore()
    signing = SigningService(store)
    bundle = signing.sign(passport)

    raw_private_key_material = store.get("signing-key")
    assert raw_private_key_material is not None
    # The persisted secret must never leak into the signed bundle we hand
    # back to a caller.
    assert raw_private_key_material not in bundle.model_dump_json()
    assert raw_private_key_material != bundle.signature
    assert raw_private_key_material != bundle.signer_public_key
