"""Offline verification rejects forged, malformed and hostile ZIP bundles."""

from __future__ import annotations

import base64
import io
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.passport.bundle import BundleExporter
from backend.app.passport.cng import CngKey
from backend.app.passport.format import MAX_MEMBER_BYTES
from backend.app.passport.jcs import canonicalize, parse_canonical
from backend.app.passport.trust import TrustRegistry
from backend.app.passport.verify import verify_bundle
from backend.app.contracts.models import JournalEventType
from backend.app.core.journal import JournalWriter
from backend.tests.passport.test_builder import _database, _seed_change


@pytest.fixture(scope="module")
def signed_bundle(tmp_path_factory: pytest.TempPathFactory):
    if os.name != "nt":
        pytest.skip("Windows CNG required")
    root = tmp_path_factory.mktemp("portable")
    database = _database(root)
    change = _seed_change(database)
    JournalWriter(database).append(change.id, JournalEventType.PASSPORT_BUILT,
                                   payload={"source": "signed fixture"})
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        bundle = BundleExporter(database, key_name=key_name,
                                installation_label="Lab").export(change.id)
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            signature = parse_canonical(archive.read("signature.json"))
        spki = base64.b64decode(signature["public_spki_b64"])
        path = root / bundle.filename
        path.write_bytes(bundle.content)
        yield path, spki, root
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


def _rewrite(source: Path, destination: Path, *, replacement: dict[str, bytes] | None = None,
             omit: set[str] | None = None, append: list[tuple[str, bytes, int]] | None = None) -> Path:
    replacement = replacement or {}
    omit = omit or set()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "w") as target:
        for item in original.infolist():
            if item.filename in omit:
                continue
            body = replacement.get(item.filename, original.read(item))
            info = zipfile.ZipInfo(item.filename, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            target.writestr(info, body)
        for name, body, mode in append or []:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            target.writestr(info, body)
    return destination


def test_trusted_bundle_valid_without_sender_database(signed_bundle) -> None:
    path, spki, root = signed_bundle
    trust = TrustRegistry(root / "trusted_keys.json")
    trust.add(spki=spki, label="Recipient label")
    result = verify_bundle(path, trust=trust)
    assert result.verdict == "VALID", result.reason
    assert result.signer_identity == "Sentinel installation Recipient label"
    assert result.claims["execution_boundary"] == "UNKNOWN"
    assert result.claims["runs_later"] == "UNKNOWN"
    assert result.claims["diff_exercised"] == "UNKNOWN"
    # The verifier reads only the archive and recipient trust path.
    for db_file in root.glob("*.sqlite3*"):
        db_file.unlink()
    assert verify_bundle(path, trust=trust).verdict == "VALID"


def test_untrusted_and_revoked_signers_are_indeterminate(signed_bundle) -> None:
    path, spki, root = signed_bundle
    trust = TrustRegistry(root / "other_trust.json")
    assert verify_bundle(path, trust=trust).verdict == "INDETERMINATE"
    value = trust.add(spki=spki, label="Lab")
    trust.revoke(value)
    assert verify_bundle(path, trust=trust).verdict == "INDETERMINATE"
    assert verify_bundle(path, trust=trust,
                         expected_fingerprint=value).verdict == "INDETERMINATE"


@pytest.mark.parametrize("member", [
    "manifest.json", "passport.json", "evidence/records.json",
    "journal/events.jsonl", "visuals/passport.svg", "visuals/passport.html", "signature.json",
])
def test_one_byte_member_change_is_invalid(signed_bundle, member: str) -> None:
    path, spki, root = signed_bundle
    with zipfile.ZipFile(path) as archive:
        original = archive.read(member)
    changed = bytes([original[0] ^ 1]) + original[1:]
    target = _rewrite(path, root / f"mutated-{member.replace('/', '-')}.sentinel",
                      replacement={member: changed})
    trust = TrustRegistry(root / "mutate_trust.json")
    trust.add(spki=spki, label="Lab")
    assert verify_bundle(target, trust=trust).verdict == "INVALID"


@pytest.mark.parametrize("unsafe", [
    "../escape", "/absolute", "C:/drive", "bad\\slash", "evidence/../escape",
])
def test_unsafe_member_path_is_invalid(signed_bundle, unsafe: str) -> None:
    path, _, root = signed_bundle
    target = _rewrite(path, root / f"unsafe-{uuid4()}.sentinel",
                      omit={"signature.json"}, append=[(unsafe, b"x", 0o100644)])
    assert verify_bundle(target, trust=TrustRegistry(root / "empty.json")).verdict == "INVALID"


def test_symlink_and_duplicate_normalized_names_are_invalid(signed_bundle) -> None:
    path, _, root = signed_bundle
    symlink = _rewrite(path, root / "symlink.sentinel", omit={"signature.json"},
                       append=[("signature.json", b"target", 0o120777)])
    assert "Symlink" in verify_bundle(symlink).reason
    duplicate = _rewrite(path, root / "duplicate.sentinel", omit={"signature.json"},
                         append=[("PASSPORT.JSON", b"x", 0o100644)])
    assert "Duplicate" in verify_bundle(duplicate).reason
    nfc = _rewrite(path, root / "nfc.sentinel", omit={"signature.json", "visuals/passport.svg"},
                   append=[("evidence/café", b"x", 0o100644),
                           ("evidence/cafe\u0301", b"y", 0o100644)])
    assert "Duplicate" in verify_bundle(nfc).reason


def test_oversized_zip_bomb_missing_and_malformed_are_invalid(signed_bundle) -> None:
    path, _, root = signed_bundle
    oversized = _rewrite(path, root / "oversized.sentinel", omit={"signature.json"},
                         append=[("signature.json", b"x" * (MAX_MEMBER_BYTES + 1), 0o100644)])
    assert verify_bundle(oversized).verdict == "INVALID"
    bomb = root / "bomb.sentinel"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"A" * 50_000)
    assert "compression ratio" in verify_bundle(bomb).reason
    missing = _rewrite(path, root / "missing.sentinel", omit={"evidence/records.json"})
    assert verify_bundle(missing).verdict == "INVALID"
    malformed = _rewrite(path, root / "malformed.sentinel",
                         replacement={"manifest.json": b"{broken"})
    assert verify_bundle(malformed).verdict == "INVALID"
    with zipfile.ZipFile(path) as archive:
        manifest = parse_canonical(archive.read("manifest.json"))
    manifest["schema_version"] = 3
    unsupported = _rewrite(path, root / "unsupported.sentinel",
                           replacement={"manifest.json": canonicalize(manifest)})
    assert verify_bundle(unsupported).verdict == "INVALID"
