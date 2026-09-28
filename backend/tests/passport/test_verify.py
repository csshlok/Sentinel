"""Offline verification rejects forged, malformed and hostile ZIP bundles."""

from __future__ import annotations

import base64
import json
import struct
import io
import os
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from backend.app.passport.bundle import BundleExporter
from backend.app.passport.cng import CngKey
from backend.app.passport.format import MAX_MEMBER_BYTES
from backend.app.passport.jcs import canonicalize, parse_canonical
from backend.app.passport.trust import TrustRegistry
from backend.app.passport.verify import _validate_claims, verify_bundle
from backend.app.cli.main import app as cli_app
from backend.app.passport.card import card_facts
from backend.app.contracts.models import JournalEventType
from backend.app.core.journal import JournalWriter
from backend.tests.passport.test_builder import _database, _seed_change

GOLDEN = Path(__file__).parent / "fixtures" / "golden-v2.sentinel"
GOLDEN_CHANGE = "cd12e3f4-2eed-4bf3-8505-ecc145cb4db5"
GOLDEN_PAYLOAD = "30e1a6b04055c17a8eb73d4a26ff85f3f1ac2e4f120ec128b5c06fcfc7b41612"


def _golden_trust(tmp_path: Path) -> TrustRegistry:
    with zipfile.ZipFile(GOLDEN) as archive:
        signature = parse_canonical(archive.read("signature.json"))
    trust = TrustRegistry(tmp_path / "golden_trust.json")
    trust.add(spki=base64.b64decode(signature["public_spki_b64"]), label="Golden")
    return trust


def test_zip64_record_is_rejected_even_with_valid_signed_members(tmp_path: Path) -> None:
    """A second ZIP64 directory must not steer Python away from Windows readers."""
    raw = GOLDEN.read_bytes()
    directory_offset = int.from_bytes(raw[-6:-2], "little")
    directory_size = int.from_bytes(raw[-10:-6], "little")
    record = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, 7, 7,
                         directory_size, directory_offset)
    locator = struct.pack("<IIQI", 0x07064B50, 0,
                          directory_offset + directory_size, 1)
    eocd = bytearray(raw[-22:])
    eocd[12:16] = (directory_size + len(record) + len(locator)).to_bytes(4, "little")
    hostile = tmp_path / "zip64.sentinel"
    hostile.write_bytes(raw[:-22] + record + locator + eocd)
    result = verify_bundle(hostile, trust=_golden_trust(tmp_path))
    assert result.verdict == "INVALID", result.reason
    assert "ZIP" in result.reason


def test_stored_member_size_slack_cannot_hide_unsigned_bytes(tmp_path: Path) -> None:
    """One extractor must not see extra passport bytes that the verifier omits."""
    with zipfile.ZipFile(GOLDEN) as archive:
        members = [(info.filename, archive.read(info)) for info in archive.infolist()]
    locals_ = bytearray()
    directory = bytearray()
    slack = b"PK\x03\x04UNSIGNED-FORGED-CARD"
    for name, body in members:
        raw_name = name.encode("ascii")
        offset = len(locals_)
        crc = zipfile.crc32(body)
        extra = slack if name == "passport.json" else b""
        stored_size = len(body) + len(extra)
        locals_ += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21,
                               crc, stored_size, len(body), len(raw_name), 0)
        locals_ += raw_name + body + extra
        directory += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 0x0314, 20,
                                 0, 0, 0, 0x21, crc, stored_size, len(body),
                                 len(raw_name), 0, 0, 0, 0, 0o100644 << 16, offset)
        directory += raw_name
    offset = len(locals_)
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(members), len(members),
                       len(directory), offset, 0)
    hostile = tmp_path / "stored-slack.sentinel"
    hostile.write_bytes(locals_ + directory + eocd)
    result = verify_bundle(hostile, trust=_golden_trust(tmp_path))
    assert result.verdict == "INVALID", result.reason
    assert "ZIP" in result.reason


@pytest.mark.parametrize("field,relative_offset,replacement", [
    ("local-version", 4, b"\xff\xff"),
    ("local-time", 10, b"\xef\xbe"),
    ("central-made-by", None, b"\xff\xff"),
    ("central-internal-attributes", None, b"\xff\xff"),
])
def test_unsigned_zip_header_fields_are_rejected(
    tmp_path: Path, field: str, relative_offset: int | None, replacement: bytes,
) -> None:
    raw = bytearray(GOLDEN.read_bytes())
    directory_offset = int.from_bytes(raw[-6:-2], "little")
    offset = relative_offset
    if field == "central-made-by":
        offset = directory_offset + 4
    elif field == "central-internal-attributes":
        offset = directory_offset + 36
    assert offset is not None
    raw[offset:offset + 2] = replacement
    hostile = tmp_path / f"{field}.sentinel"
    hostile.write_bytes(raw)
    result = verify_bundle(hostile, trust=_golden_trust(tmp_path))
    assert result.verdict == "INVALID", (field, result.reason)
    assert "ZIP" in result.reason


def test_committed_golden_bundle_card_and_verifier_agree(tmp_path: Path) -> None:
    with zipfile.ZipFile(GOLDEN) as archive:
        signature = parse_canonical(archive.read("signature.json"))
        passport = parse_canonical(archive.read("passport.json"))
        html = archive.read("visuals/passport.html").decode("utf-8")
        svg = archive.read("visuals/passport.svg").decode("utf-8")
    trust = TrustRegistry(tmp_path / "trusted_keys.json")
    trust.add(spki=base64.b64decode(signature["public_spki_b64"]), label="Golden fixture")
    result = verify_bundle(GOLDEN, trust=trust)
    assert result.verdict == "VALID", result.reason
    assert result.change_id == GOLDEN_CHANGE
    assert result.payload_sha256 == GOLDEN_PAYLOAD
    expected = {
        "Change": GOLDEN_CHANGE, "Payload SHA-256": GOLDEN_PAYLOAD,
        "Checks passed": "UNKNOWN", "Freshness": "UNKNOWN",
        "Execution boundary": "UNKNOWN", "Runs later": "UNKNOWN",
    }
    facts = dict(card_facts(passport, payload_digest=GOLDEN_PAYLOAD))
    for label, value in expected.items():
        assert facts[label] == value
        assert value in html and value in svg
    assert result.claims["freshness"] == facts["Freshness"]
    assert result.claims["execution_boundary"] == facts["Execution boundary"]
    assert result.claims["runs_later"] == facts["Runs later"]
    for limitation in result.claims["limitations"]:
        assert limitation in html and limitation in svg


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
    assert result.signer_identity == "Sentinel installation Lab"
    assert result.trusted_as == "Sentinel installation Recipient label"
    assert result.claims["execution_boundary"] == "UNKNOWN"
    assert result.claims["runs_later"] == "UNKNOWN"
    assert result.claims["diff_exercised"] == "UNKNOWN"
    with zipfile.ZipFile(path) as archive:
        passport = parse_canonical(archive.read("passport.json"))
        manifest = parse_canonical(archive.read("manifest.json"))
        html = archive.read("visuals/passport.html").decode("utf-8")
        svg = archive.read("visuals/passport.svg").decode("utf-8")
    assert result.payload_sha256 == manifest["payload_sha256"]
    assert result.signer_identity == passport["signer"]["identity"]
    for field, expected in (
        ("Checks passed", "UNKNOWN"), ("Diff exercised", "UNKNOWN"),
        ("Freshness", "UNKNOWN"), ("Execution boundary", "UNKNOWN"),
        ("Runs later", "UNKNOWN"),
    ):
        assert f"{field}: {expected}" in svg
        assert expected in html
    for limitation in result.claims["limitations"]:
        assert limitation in html and limitation in svg
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
    "../escape", "/absolute", "C:/drive", "evidence/../escape",
    "passport.json:stream",
])
def test_unsafe_member_path_is_invalid(signed_bundle, unsafe: str) -> None:
    path, _, root = signed_bundle
    target = _rewrite(path, root / f"unsafe-{uuid4()}.sentinel",
                      omit={"signature.json"}, append=[(unsafe, b"x", 0o100644)])
    result = verify_bundle(target, trust=TrustRegistry(root / "empty.json"))
    assert result.verdict == "INVALID"
    assert "Unsafe ZIP member path" in result.reason


def test_backslash_member_name_is_rejected_before_signature(tmp_path: Path) -> None:
    raw = GOLDEN.read_bytes().replace(b"signature.json", b"signature\\json")
    target = tmp_path / "backslash.sentinel"
    target.write_bytes(raw)
    assert "Unsafe ZIP member path" in verify_bundle(target).reason


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


def test_encrypted_zip_entry_is_rejected_before_read(signed_bundle) -> None:
    path, _, root = signed_bundle
    data = bytearray(path.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    data[local + 6] |= 1
    data[central + 8] |= 1
    target = root / "encrypted.sentinel"
    target.write_bytes(data)
    assert "Encrypted" in verify_bundle(target).reason


def test_zip_prefix_and_trailer_are_rejected(signed_bundle) -> None:
    path, _, root = signed_bundle
    prefix = root / "prefix.sentinel"
    prefix.write_bytes(b"MZ" + path.read_bytes())
    assert verify_bundle(prefix).verdict == "INVALID"
    trailer = root / "trailer.sentinel"
    trailer.write_bytes(path.read_bytes() + b"hidden")
    assert verify_bundle(trailer).verdict == "INVALID"


def test_oversized_zip_bomb_missing_and_malformed_are_invalid(signed_bundle) -> None:
    path, _, root = signed_bundle
    oversized = _rewrite(path, root / "oversized.sentinel", omit={"signature.json"},
                         append=[("signature.json", b"x" * (MAX_MEMBER_BYTES + 1), 0o100644)])
    assert "Oversized ZIP member" in verify_bundle(oversized).reason
    bomb = root / "bomb.sentinel"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", b"A" * 50_000)
    assert "compression" in verify_bundle(bomb).reason
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


def test_unsupported_public_key_algorithm_returns_invalid(tmp_path: Path) -> None:
    with zipfile.ZipFile(GOLDEN) as archive:
        signature = parse_canonical(archive.read("signature.json"))
    # SubjectPublicKeyInfo with an unsupported algorithm OID (1.2.3.4).
    signature["public_spki_b64"] = base64.b64encode(
        bytes.fromhex("300b300506032a030403020001")
    ).decode("ascii")
    target = _rewrite(GOLDEN, tmp_path / "unknown-algorithm.sentinel",
                      replacement={"signature.json": canonicalize(signature)})
    result = verify_bundle(target, trust=TrustRegistry(tmp_path / "trust.json"))
    assert result.verdict == "INVALID"
    assert "UnsupportedAlgorithm" in result.reason
    cli = CliRunner().invoke(cli_app, ["verify", str(target), "--json"])
    assert cli.exit_code == 1
    assert json.loads(cli.stdout)["verdict"] == "INVALID"


def test_unexpected_verifier_exception_still_returns_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedVerificationFailure(Exception):
        pass

    def unexpected(_: bytes) -> str:
        raise UnexpectedVerificationFailure()

    monkeypatch.setattr("backend.app.passport.verify.fingerprint", unexpected)
    result = verify_bundle(GOLDEN, trust=_golden_trust(tmp_path))
    assert result.verdict == "INVALID"
    assert "UnexpectedVerificationFailure" in result.reason


def test_hidden_bytes_before_central_directory_are_invalid(tmp_path: Path) -> None:
    raw = GOLDEN.read_bytes()
    offset = int.from_bytes(raw[-6:-2], "little")
    hidden = b"PK\x03\x04forged visuals/passport.html"
    modified = bytearray(raw[:offset] + hidden + raw[offset:])
    modified[-6:-2] = (offset + len(hidden)).to_bytes(4, "little")
    target = tmp_path / "hidden-local-entry.sentinel"
    target.write_bytes(modified)
    result = verify_bundle(target, trust=TrustRegistry(tmp_path / "trust.json"))
    assert result.verdict == "INVALID"
    assert "hidden data" in result.reason


def test_local_header_method_mismatch_is_invalid(tmp_path: Path) -> None:
    raw = bytearray(GOLDEN.read_bytes())
    assert raw[:4] == b"PK\x03\x04"
    raw[8:10] = (8).to_bytes(2, "little")
    target = tmp_path / "local-method.sentinel"
    target.write_bytes(raw)
    result = verify_bundle(target, trust=TrustRegistry(tmp_path / "trust.json"))
    assert result.verdict == "INVALID"
    assert "compression" in result.reason


def test_claim_type_coercion_cannot_make_card_and_verifier_disagree() -> None:
    with zipfile.ZipFile(GOLDEN) as archive:
        content = {name: archive.read(name) for name in archive.namelist()}
    passport = parse_canonical(content["passport.json"])
    manifest = parse_canonical(content["manifest.json"])
    passport["claims"]["diff_coverage"]["checks_passed"] = 1
    passport["claims"]["diff_coverage"]["changed_executable_lines"] = True
    with pytest.raises(ValueError, match="normalization"):
        _validate_claims(passport, manifest, content, manifest["payload_sha256"])
