"""Protected local selector for the currently active Passport signing key."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from backend.app.core.evidence_store import prepare_store_directory
from backend.app.passport.cng import DEFAULT_KEY_NAME


def identity_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OSError("LOCALAPPDATA is required for the signing identity")
    return Path(local) / "Sentinel" / "signing_identity.json"


def _protected(path: Path) -> None:
    if path.is_symlink() or not prepare_store_directory(path.parent):
        raise OSError("Signing identity store is not protected")


def active_key_name() -> str:
    path = identity_path()
    _protected(path)
    if not path.exists():
        return DEFAULT_KEY_NAME
    if path.stat().st_size > 2048:
        raise ValueError("Signing identity selector is oversized")
    data = json.loads(path.read_text(encoding="utf-8"))
    name = data.get("key_name") if isinstance(data, dict) else None
    if (not isinstance(name, str) or not name or len(name) > 200
            or any(char in name for char in "\\/\0\r\n")
            or data.get("schema_version") != 1):
        raise ValueError("Signing identity selector is malformed")
    return name


def activate_key_name(name: str) -> None:
    if not name or len(name) > 200 or any(char in name for char in "\\/\0\r\n"):
        raise ValueError("Invalid signing key name")
    path = identity_path()
    _protected(path)
    content = json.dumps({"schema_version": 1, "key_name": name},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    handle, temporary = tempfile.mkstemp(prefix=".signer-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
