"""Research Pitfall 8 / threat T-01-38: a diff carrying the staged model credential never lands.

Real Windows AppContainer and WorkspaceManager; the agent is node under the
``fake_node_launcher`` profile, which stages a dummy credential (never the
user's ``~/.claude``). Each leak variant must end with no approval token, the
leaking path flagged ``credential`` and the user's repository untouched; the
same flow without a leak must apply.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import AgentRunStatus, WorkspaceState
from backend.app.core.errors import AppError
from backend.app.execution.agent_ports import CredentialFingerprint
from backend.app.execution.process_supervisor import IS_WINDOWS
from backend.app.workspace.manager import (
    CREDENTIAL_DETECTION_LIMITATION,
    CREDENTIAL_IN_DIFF_LIMITATION,
    DIFF_TOO_LARGE_TO_SCAN_LIMITATION,
    WorkspaceManager,
    _digest,
    _header_path,
    _patch_additions,
)
from backend.app.workspace.models import CREDENTIAL_FLAG, SECRET_SCAN_LIMIT, ApplyRefusal
from backend.tests.support_kb import git
from backend.tests.workspace.conftest import (
    DUMMY_CREDENTIAL_KIND,
    FakeNodeLauncher,
    dummy_credential_bytes,
    repo_fingerprint,
)

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="AppContainers are Windows-only")

READ_TOKEN = "\n".join([
    "const fs = require('fs');",
    "const path = require('path');",
    "const staged = path.join(process.env.USERPROFILE, '.claude', '.credentials.json');",
    "const token = JSON.parse(fs.readFileSync(staged, 'utf8')).claudeAiOauth.accessToken;",
])
CLEAN_EDIT = (
    "fs.appendFileSync('calc.py', "
    + json.dumps("\ndef sub(a, b):\n    return a - b\n") + ");"
)

LEAKS = {
    "copied-file": "fs.copyFileSync(staged, 'leak.json');",
    "embedded": "fs.writeFileSync('config.py', 'API_KEY = \"' + token + '\"\\n');",
    "base64": "fs.writeFileSync('blob.txt', Buffer.from(token).toString('base64') + '\\n');",
    "hex": "fs.writeFileSync('blob.txt', Buffer.from(token).toString('hex') + '\\n');",
}
LEAK_PATHS = {"copied-file": "leak.json", "embedded": "config.py",
              "base64": "blob.txt", "hex": "blob.txt"}


def _script(*lines: str) -> str:
    return "\n".join((READ_TOKEN, *lines, "process.stdout.write('done');"))


def _flags(preview, path: str) -> tuple[str, ...]:
    return next(flags for _status, name, _old, _new, flags in preview.changed_paths
                if name == path)


def _run(fake: FakeNodeLauncher, change_id, repo: Path, script: str):
    run = fake.launch(change_id, repo, script)
    assert run.status is AgentRunStatus.PASSED, (run.stderr, run.limitations)
    assert "done" in run.stdout
    return run


def _assert_refused_apply(manager: WorkspaceManager, change_id, token: str | None,
                          repo: Path, before: dict[str, str]) -> None:
    with pytest.raises(AppError) as caught:
        manager.apply(change_id, token or "no-token-was-issued")
    assert caught.value.code in ("WORKSPACE_APPROVAL_INVALID", "WORKSPACE_APPLY_REFUSED")
    assert repo_fingerprint(repo) == before


@pytest.mark.parametrize("variant", sorted(LEAKS))
def test_a_leaked_credential_is_refused_with_no_approval_token(
    variant: str, workspace_manager: WorkspaceManager, user_repo: Path,
    fake_node_launcher: FakeNodeLauncher,
) -> None:
    change_id = uuid4()
    before = repo_fingerprint(user_repo)
    head = git(user_repo, "rev-parse", "HEAD").strip()

    # A first, clean run earns an approval token ...
    _run(fake_node_launcher, change_id, user_repo, _script(CLEAN_EDIT))
    earlier = workspace_manager.preview(change_id)
    assert earlier.approval_token and earlier.refusal_reason is None
    # ... which the leaking run voids; its own preview issues none.
    _run(fake_node_launcher, change_id, user_repo, _script(LEAKS[variant]))
    preview = workspace_manager.preview(change_id)

    assert preview.refusal_reason == ApplyRefusal.CREDENTIAL_IN_DIFF.value
    assert preview.approval_token is None
    assert preview.fast_forward_possible is False
    leaked = LEAK_PATHS[variant]
    assert CREDENTIAL_FLAG in _flags(preview, leaked)
    assert CREDENTIAL_FLAG not in _flags(preview, "calc.py")
    assert CREDENTIAL_IN_DIFF_LIMITATION in preview.limitations
    assert CREDENTIAL_DETECTION_LIMITATION in preview.limitations
    record = workspace_manager.live_for_change(change_id)
    assert record.refusal_reason == ApplyRefusal.CREDENTIAL_IN_DIFF.value
    assert record.approval_digest is None
    assert fake_node_launcher.access_token not in record.to_json()
    assert repo_fingerprint(user_repo) == before

    _assert_refused_apply(workspace_manager, change_id, earlier.approval_token,
                          user_repo, before)
    _assert_refused_apply(workspace_manager, change_id, None, user_repo, before)
    assert git(user_repo, "rev-parse", "HEAD").strip() == head
    assert not (user_repo / leaked).exists() or leaked == "calc.py"


def test_apply_refuses_a_record_with_a_refusal_even_with_a_matching_token(
    workspace_manager: WorkspaceManager, user_repo: Path,
    fake_node_launcher: FakeNodeLauncher,
) -> None:
    """Defense in depth: a digest planted on a refused record still does not apply."""

    change_id = uuid4()
    before = repo_fingerprint(user_repo)
    _run(fake_node_launcher, change_id, user_repo, _script(LEAKS["copied-file"]))
    preview = workspace_manager.preview(change_id)
    assert preview.approval_token is None
    record = workspace_manager.live_for_change(change_id)
    planted = "planted-token"
    workspace_manager._save(
        record, record.state, approval_digest=_digest(planted),
        approved_base_sha=record.base_sha, approved_sealed_sha=record.sealed_sha,
    )
    with pytest.raises(AppError) as caught:
        workspace_manager.apply(change_id, planted)
    assert caught.value.code == "WORKSPACE_APPROVAL_INVALID"
    assert repo_fingerprint(user_repo) == before


def test_positive_control_clean_edits_get_a_token_and_apply(
    workspace_manager: WorkspaceManager, user_repo: Path,
    fake_node_launcher: FakeNodeLauncher,
) -> None:
    change_id = uuid4()
    # The agent reads the staged credential but writes only ordinary edits.
    _run(fake_node_launcher, change_id, user_repo, _script(
        CLEAN_EDIT, "fs.writeFileSync('notes.txt', 'token length ' + token.length + '\\n');"))
    record = workspace_manager.live_for_change(change_id)
    assert len(record.credential_fingerprints) == 1  # a credential WAS staged

    preview = workspace_manager.preview(change_id)
    assert preview.refusal_reason is None
    assert preview.approval_token
    assert all(CREDENTIAL_FLAG not in flags for *_rest, flags in preview.changed_paths)
    assert CREDENTIAL_DETECTION_LIMITATION in preview.limitations
    assert CREDENTIAL_IN_DIFF_LIMITATION not in preview.limitations

    applied = workspace_manager.apply(change_id, preview.approval_token)
    assert applied.state == WorkspaceState.CLEANED
    assert git(user_repo, "rev-parse", "HEAD").strip() == preview.sealed_sha
    calc = (user_repo / "calc.py").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert calc.endswith("def sub(a, b):\n    return a - b\n")
    notes = (user_repo / "notes.txt").read_bytes().decode("utf-8").strip()
    assert notes == f"token length {len(fake_node_launcher.access_token)}"


def _plant_large_diff(manager: WorkspaceManager, change_id, repo: Path) -> None:
    record = manager.create(change_id, repo)
    line = b"x" * 99 + b"\n"
    size = SECRET_SCAN_LIMIT + 1_048_576
    (record.workspace_path / "large.txt").write_bytes(line * (size // len(line)))


def test_an_oversize_diff_is_refused_when_a_credential_was_staged(
    workspace_manager: WorkspaceManager, user_repo: Path,
) -> None:
    change_id = uuid4()
    before = repo_fingerprint(user_repo)
    _plant_large_diff(workspace_manager, change_id, user_repo)
    record = workspace_manager.live_for_change(change_id)
    workspace_manager.record_credential(record.id, CredentialFingerprint.from_bytes(
        DUMMY_CREDENTIAL_KIND, dummy_credential_bytes()))

    preview = workspace_manager.preview(change_id)
    assert preview.refusal_reason == ApplyRefusal.DIFF_TOO_LARGE_TO_SCAN.value
    assert preview.approval_token is None
    assert DIFF_TOO_LARGE_TO_SCAN_LIMITATION in preview.limitations
    assert CREDENTIAL_DETECTION_LIMITATION in preview.limitations
    _assert_refused_apply(workspace_manager, change_id, None, user_repo, before)


def test_an_oversize_diff_without_a_staged_credential_is_not_refused_for_scanning(
    workspace_manager: WorkspaceManager, user_repo: Path,
) -> None:
    change_id = uuid4()
    _plant_large_diff(workspace_manager, change_id, user_repo)

    preview = workspace_manager.preview(change_id)
    assert preview.refusal_reason is None
    assert preview.approval_token
    assert CREDENTIAL_DETECTION_LIMITATION not in preview.limitations
    assert DIFF_TOO_LARGE_TO_SCAN_LIMITATION not in preview.limitations
    workspace_manager.discard(change_id)


# ---------------------------------------------------------------- patch parsing (pure)

def test_header_paths_plain_and_quoted() -> None:
    assert _header_path(b"diff --git a/src/x y.py b/src/x y.py") == "src/x y.py"
    assert _header_path(b'diff --git "a/q\\"t.txt" "b/q\\"t.txt"') == 'q"t.txt'
    assert _header_path(b'diff --git "a/tab\\there" "b/tab\\there"') == "tab\there"
    assert _header_path(b'diff --git "a/\\303\\251.txt" "b/\\303\\251.txt"') == "é.txt"
    assert _header_path(b"diff --git a/one b/two") is None


def test_patch_additions_skip_removed_and_context_lines() -> None:
    token = base64.b64encode(b"secret-material-0123456789").decode()
    patch = "\n".join([
        "diff --git a/a.txt b/a.txt",
        "index 1..2 100644",
        "--- a/a.txt",
        "+++ b/a.txt",
        "@@ -1,2 +1,2 @@",
        f"-removed {token}",
        f" context {token}",
        "+added line",
        "diff --git a/b.txt b/b.txt",
        "@@ -0,0 +1 @@",
        f"+{token}",
    ]).encode()
    sections = dict(_patch_additions(patch))
    assert token.encode() not in sections["a.txt"]
    assert b"added line" in sections["a.txt"]
    assert token.encode() in sections["b.txt"]
