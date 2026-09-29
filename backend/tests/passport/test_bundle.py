"""Portable bundle uses only redacted records and truthful card claims."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.assurance.store import EvidenceStore
from backend.app.assurance.engine import contract_digest
from backend.app.contracts.models import (ChangeContract, DiffCoverageFile,
                                          DiffCoverageResult, JournalEventType)
from backend.app.core.journal import JournalWriter
from backend.app.passport.bundle import BundleExporter
from backend.app.passport.card import card_facts, render_html, render_svg
from backend.app.passport.cng import CngKey
from backend.app.passport.jcs import parse_canonical
from backend.app.git.state import GitStateTracker
from backend.tests.passport.test_builder import _database, _seed_change
from backend.tests.passport.test_v2 import _launch
from backend.tests.support_kb import make_repo, write
from backend.app.passport.verify import verify_bundle
from backend.app.passport.trust import TrustRegistry


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_selected_preset_and_denials_are_signed_in_bundle_and_card(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    database = _database(tmp_path)
    change = _seed_change(database)
    selected = ChangeContract(schema_version=3, policy_preset_name="strict",
                              policy_change_type="code")
    with database.connection() as connection:
        connection.execute("UPDATE changes SET repository_path = ?, contract_json = ?, "
                           "revision = revision + 1 WHERE id = ?",
                           (str(root), selected.model_dump_json(), str(change.id)))
    captured = GitStateTracker().capture(change.id, "measured", str(root), 1, 1_048_576)
    now = datetime.now(UTC)
    EvidenceStore(database).save_diff_coverage(DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=uuid4(), tested_checkpoint_id=uuid4(),
        head_sha=captured.head_sha, status_digest=captured.status_digest,
        contract_digest=contract_digest(change.model_copy(update={"contract": selected})),
        started_at=now, completed_at=now, collector_status="COLLECTED",
        checks_passed=True, diff_exercised="PASS", freshness="CURRENT",
        changed_executable_lines=1, executed_changed_lines=1, measured_percent=100,
        files=[DiffCoverageFile(path="module.py", changed_lines=[1],
                                executable_lines=[1], executed_lines=[1])],
    ))
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        artifact = BundleExporter(database, key_name=key_name).export(change.id)
        path = tmp_path / artifact.filename
        path.write_bytes(artifact.content)
        with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
            passport = parse_canonical(archive.read("passport.json"))
            signature = parse_canonical(archive.read("signature.json"))
            html = archive.read("visuals/passport.html")
        claims = passport["claims"]
        assert claims["policy_preset_name"] == "strict"
        assert claims["policy_preset_version"] == "1.0.0"
        assert claims["policy_decision"] == "DENY"
        assert any("confined checks" in reason for reason in claims["policy_denials"])
        assert any("AppContainer" in reason for reason in claims["policy_denials"])
        assert b"Policy preset" in html and b"Policy decision" in html
        trust = TrustRegistry(tmp_path / "trusted_keys.json")
        trust.add(spki=base64.b64decode(signature["public_spki_b64"]), label="Lab")
        verdict = verify_bundle(path, trust=trust)
        assert verdict.verdict == "VALID", verdict.reason
        assert verdict.claims["policy_decision"] == "DENY"
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_export_is_canonical_redacted_and_card_matches_claims(tmp_path: Path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    canary = "SENTINEL_SECRET_CANARY_7q9Z"
    source = tmp_path / "repo" / "source.py"
    source.parent.mkdir()
    source.write_text(f"TOKEN = '{canary}'\n", encoding="utf-8")
    JournalWriter(database).append(change.id, JournalEventType.PASSPORT_BUILT,
                                   payload={"log": canary})
    run_id = _launch(database, change.id)
    now = datetime.now(UTC).isoformat()
    with database.connection() as connection:
        connection.execute("UPDATE changes SET repository_path = ?, intent = ? WHERE id = ?",
                           (str(source.parent), canary, str(change.id)))
        connection.execute("INSERT INTO environment_passports "
                           "(id, change_id, payload_json, captured_at) VALUES (?, ?, ?, ?)",
                           (str(uuid4()), str(change.id), json.dumps({"environment": canary}), now))
        connection.execute("UPDATE agent_runs SET payload_json = ? WHERE id = ?",
                           (json.dumps({"id": run_id, "change_id": str(change.id),
                                        "status": "SUCCEEDED", "tool_output": canary}), run_id))
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        bundle = BundleExporter(database, key_name=key_name).export(change.id)
        assert bundle.filename == f"change-{change.id}.sentinel"
        assert canary.encode() not in bundle.content
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            names = archive.namelist()
            assert names == ["manifest.json", "passport.json", "evidence/records.json",
                             "journal/events.jsonl", "visuals/passport.svg",
                             "visuals/passport.html", "signature.json"]
            assert all(canary.encode() not in archive.read(name) for name in names)
            manifest = parse_canonical(archive.read("manifest.json"))
            passport = parse_canonical(archive.read("passport.json"))
            assert manifest["payload_sha256"] == hashlib.sha256(
                archive.read("passport.json")).hexdigest()
            digest = manifest["payload_sha256"]
            assert digest.encode() in archive.read("visuals/passport.svg")
            assert digest.encode() in archive.read("visuals/passport.html")
            assert archive.read("visuals/passport.svg") == render_svg(passport,
                                                                         payload_digest=digest)
            assert archive.read("visuals/passport.html") == render_html(passport,
                                                                           payload_digest=digest)
            assert ("Execution boundary", "UNKNOWN") in card_facts(passport,
                                                                      payload_digest=digest)
            assert ("Runs later", "UNKNOWN") in card_facts(passport,
                                                             payload_digest=digest)
            assert b"AppContainer applied" not in bundle.content
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_stale_diff_result_remains_stale_in_card(tmp_path: Path) -> None:
    database = _database(tmp_path)
    change = _seed_change(database)
    now = datetime.now(UTC)
    result = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=uuid4(), tested_checkpoint_id=uuid4(),
        head_sha="a" * 40, status_digest="b" * 64, contract_digest="c" * 64,
        started_at=now, completed_at=now, collector_status="OK", checks_passed=True,
        diff_exercised="STALE", freshness="STALE",
        changed_executable_lines=5, executed_changed_lines=4,
    )
    EvidenceStore(database).save_diff_coverage(result)
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        bundle = BundleExporter(database, key_name=key_name).export(change.id)
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            passport = parse_canonical(archive.read("passport.json"))
            assert passport["claims"]["diff_coverage"]["freshness"] == "STALE"
            assert b"STALE" in archive.read("visuals/passport.html")
            assert b"STALE" in archive.read("visuals/passport.svg")
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_repo_movement_after_measurement_becomes_stale_in_every_view(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", {"module.py": "VALUE = 1\n"})
    database = _database(tmp_path)
    change = _seed_change(database)
    with database.connection() as connection:
        connection.execute("UPDATE changes SET repository_path = ? WHERE id = ?",
                           (str(root), str(change.id)))
    captured = GitStateTracker().capture(change.id, "measured", str(root), 1, 1_048_576)
    now = datetime.now(UTC)
    result = DiffCoverageResult(
        change_id=change.id, baseline_checkpoint_id=uuid4(), tested_checkpoint_id=uuid4(),
        head_sha=captured.head_sha, status_digest=captured.status_digest,
        contract_digest="c" * 64, started_at=now, completed_at=now,
        collector_status="OK", checks_passed=True, diff_exercised="PASS",
        freshness="CURRENT", changed_executable_lines=1, executed_changed_lines=1,
        measured_percent=100,
    )
    EvidenceStore(database).save_diff_coverage(result)
    write(root, "module.py", "VALUE = 2\n")
    key_name = f"Sentinel disposable test {uuid4()}"
    try:
        bundle = BundleExporter(database, key_name=key_name).export(change.id)
        path = tmp_path / bundle.filename
        path.write_bytes(bundle.content)
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            passport = parse_canonical(archive.read("passport.json"))
            signature = parse_canonical(archive.read("signature.json"))
            assert b"STALE" in archive.read("visuals/passport.svg")
        diff = passport["claims"]["diff_coverage"]
        assert diff["freshness"] == "STALE" and diff["diff_exercised"] == "STALE"
        spki = base64.b64decode(signature["public_spki_b64"])
        trust = TrustRegistry(tmp_path / "trusted_keys.json")
        trust.add(spki=spki, label="Lab")
        verdict = verify_bundle(path, trust=trust)
        assert verdict.verdict == "VALID"
        assert verdict.claims["freshness"] == "STALE"
        assert verdict.claims["diff_exercised"] == "STALE"
    finally:
        with CngKey.open(name=key_name) as key:
            key.delete_for_test()
