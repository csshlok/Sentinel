"""Portable bundle uses only redacted records and truthful card claims."""

from __future__ import annotations

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
from backend.app.contracts.models import DiffCoverageResult, JournalEventType
from backend.app.core.journal import JournalWriter
from backend.app.passport.bundle import BundleExporter
from backend.app.passport.card import card_facts, render_html, render_svg
from backend.app.passport.cng import CngKey
from backend.app.passport.jcs import parse_canonical
from backend.tests.passport.test_builder import _database, _seed_change
from backend.tests.passport.test_v2 import _launch


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
