"""Recipient trust commands work offline with a temporary local registry."""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from typer.testing import CliRunner

from backend.app.cli.main import app
from backend.app.passport.cng import fingerprint


def test_offline_trust_add_list_remove_and_revoke(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    public = ec.generate_private_key(ec.SECP256R1()).public_key()
    spki = public.public_bytes(serialization.Encoding.DER,
                               serialization.PublicFormat.SubjectPublicKeyInfo)
    key = tmp_path / "sender.der"
    key.write_bytes(spki)
    runner = CliRunner()
    added = runner.invoke(app, ["trust", "add", "--key", str(key), "--label", "Office", "--json"])
    assert added.exit_code == 0, added.output
    value = fingerprint(spki)
    assert json.loads(added.stdout)["fingerprint"] == value
    assert json.loads(runner.invoke(app, ["trust", "list", "--json"]).stdout)["count"] == 1
    removed = runner.invoke(app, ["trust", "remove", value, "--json"])
    assert removed.exit_code == 0 and json.loads(removed.stdout)["removed"] is True
    revoked = runner.invoke(app, ["trust", "revoke", value, "--json"])
    assert revoked.exit_code == 0 and json.loads(revoked.stdout)["revoked"] is True


def test_trust_add_rejects_mismatched_fingerprint(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    first = ec.generate_private_key(ec.SECP256R1()).public_key()
    second = ec.generate_private_key(ec.SECP256R1()).public_key()
    key = tmp_path / "sender.der"
    key.write_bytes(first.public_bytes(serialization.Encoding.DER,
                                       serialization.PublicFormat.SubjectPublicKeyInfo))
    other = second.public_bytes(serialization.Encoding.DER,
                                serialization.PublicFormat.SubjectPublicKeyInfo)
    result = CliRunner().invoke(app, ["trust", "add", fingerprint(other), "--key", str(key),
                                      "--label", "Office"])
    assert result.exit_code == 1
    assert "does not match" in result.output
