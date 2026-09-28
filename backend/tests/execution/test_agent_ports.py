"""Credential fingerprints and the digest-only credential-material detector."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

from backend.app.execution.agent_ports import (
    CredentialFingerprint,
    CredentialRevocation,
    CredentialStager,
    StagedCredential,
    WorkspaceLease,
    WorkspaceProvider,
    contains_credential_material,
    credential_token_values,
    git_blob_id,
)

ACCESS = "sk-ant-oat01-DUMMYaccessTOKEN0123456789abcdefXYZ"
REFRESH = "sk-ant-ort01-DUMMYrefreshTOKEN9876543210zyxwvuQRS"
DUMMY = json.dumps({
    "claudeAiOauth": {
        "accessToken": ACCESS,
        "refreshToken": REFRESH,
        "expiresAt": 1893456000000,
        "scopes": ["user:inference", "user:profile"],
        "subscriptionType": "max",
    }
}, indent=2).replace("\n", "\r\n").encode("utf-8")


def _fingerprint() -> CredentialFingerprint:
    return CredentialFingerprint.from_bytes("claude-oauth-file", DUMMY)


def test_git_blob_id_matches_git():
    # `printf 'hello\n' | git hash-object --stdin`
    assert git_blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_fingerprint_contains_blob_ids_of_the_file_and_its_line_ending_variants():
    fingerprint = _fingerprint()
    lf = DUMMY.replace(b"\r\n", b"\n")
    assert git_blob_id(DUMMY) in fingerprint.blob_ids
    assert git_blob_id(lf) in fingerprint.blob_ids
    assert contains_credential_material(fingerprint, blob_ids=[git_blob_id(DUMMY)])
    assert contains_credential_material(fingerprint, blob_ids=[git_blob_id(lf).upper()])
    assert not contains_credential_material(fingerprint, blob_ids=[git_blob_id(b"other\n")])


def test_only_long_json_strings_are_token_values():
    assert set(credential_token_values(DUMMY)) == {ACCESS, REFRESH}
    assert credential_token_values(b"not json at all") == ()


def test_detects_the_token_verbatim_inside_other_text():
    fingerprint = _fingerprint()
    text = f'const leaked = "{ACCESS}";\nprint(1)\n'.encode()
    assert contains_credential_material(fingerprint, text=text)
    # An assignment without quotes glues the name to the token in one run.
    assert contains_credential_material(fingerprint, text=f"TOKEN={REFRESH}\n".encode())


def test_detects_base64_urlsafe_and_hex_encodings():
    fingerprint = _fingerprint()
    raw = ACCESS.encode()
    for encoded in (base64.b64encode(raw), base64.urlsafe_b64encode(raw), raw.hex().encode()):
        assert contains_credential_material(fingerprint, text=b"x = '" + encoded + b"'\n")


def test_unrelated_text_and_a_near_miss_are_not_detected():
    fingerprint = _fingerprint()
    assert not contains_credential_material(fingerprint, text=b"def add(a, b):\n    return a+b\n")
    near = ACCESS[:-1] + ("A" if ACCESS[-1] != "A" else "B")
    assert len(near) == len(ACCESS)
    assert not contains_credential_material(fingerprint, text=f'"{near}"'.encode())
    assert not contains_credential_material(fingerprint)


def test_long_runs_are_checked_at_the_edges():
    fingerprint = _fingerprint()
    padding = b"A" * 5000
    assert contains_credential_material(fingerprint, text=ACCESS.encode() + padding)
    assert contains_credential_material(fingerprint, text=padding + ACCESS.encode())


def test_payload_round_trips_and_holds_no_token():
    fingerprint = _fingerprint()
    payload = fingerprint.to_payload()
    serialized = json.dumps(payload)
    for secret in (ACCESS, REFRESH):
        assert secret not in serialized
        assert base64.b64encode(secret.encode()).decode() not in serialized
        assert secret.encode().hex() not in serialized
    assert CredentialFingerprint.from_payload(payload) == fingerprint


def test_staged_credential_repr_hides_redaction_values():
    staged = StagedCredential("claude-oauth-file", Path("x"), _fingerprint(), "0" * 64,
                              redaction_values=(ACCESS,))
    assert ACCESS not in repr(staged)
    assert CredentialRevocation(deleted=True, changed_during_run=False).deleted


def test_protocols_are_structural():
    class Lease:
        id = uuid4()
        profile_name = "p"
        package_sid = "S-1-15-2-1"
        container_path = Path("c")
        workspace_path = Path("w")

    class Provider:
        def ensure(self, change_id, source_repository, *, run_id): ...
        def finish_run(self, workspace_id, run_id, *, facts, status, limitations=()): ...
        def record_credential(self, workspace_id, fingerprint): ...

    class Stager:
        def stage_agent_credential(self, change_id, kind, home): ...
        def revoke_staged_credential(self, staged): ...
        def purge_staged_credentials(self, home): ...

    assert isinstance(Lease(), WorkspaceLease)
    assert isinstance(Provider(), WorkspaceProvider)
    assert isinstance(Stager(), CredentialStager)
    assert not isinstance(object(), WorkspaceProvider)
