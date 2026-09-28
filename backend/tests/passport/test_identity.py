"""A selected signing identity cannot be minted from selector text."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.passport.cng import CngKey, fingerprint
import backend.app.passport.identity as identity


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_selector_cannot_create_an_unseen_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "signing_identity.json"
    monkeypatch.setattr(identity, "identity_path", lambda: path)
    monkeypatch.setattr(identity, "_protected", lambda _path: None)
    name = f"Sentinel disposable test {uuid4()}"
    path.write_text(json.dumps({"schema_version": 1, "key_name": name,
                                "fingerprint": "BOGUS"}), encoding="utf-8")
    with pytest.raises(OSError, match="does not exist"):
        with identity.open_signing_key():
            pass
    with pytest.raises(OSError, match="does not exist"):
        CngKey.open_existing(name=name)


@pytest.mark.skipif(os.name != "nt", reason="Windows CNG required")
def test_selector_pins_existing_public_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "signing_identity.json"
    monkeypatch.setattr(identity, "identity_path", lambda: path)
    monkeypatch.setattr(identity, "_protected", lambda _path: None)
    name = f"Sentinel disposable test {uuid4()}"
    with CngKey.open(name=name) as created:
        try:
            expected = fingerprint(created.public_spki())
            identity.activate_key_name(name)
            with identity.open_signing_key() as opened:
                assert fingerprint(opened.public_spki()) == expected
            data = json.loads(path.read_text(encoding="utf-8"))
            data["fingerprint"] = "BOGUS"
            path.write_text(json.dumps(data), encoding="utf-8")
            with pytest.raises(ValueError, match="fingerprint changed"):
                with identity.open_signing_key():
                    pass
        finally:
            created.delete_for_test()
