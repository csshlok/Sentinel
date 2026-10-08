"""SC1 at the launcher level: the boundary comes from the adapter's profile and never falls back.

Fakes stand in for the workspace provider, the credential stager and the
AppContainer spawn; the restricted-token spawn is replaced by a sentinel that
fails the test if anything ever calls it. The real end-to-end launch is in
backend/tests/workspace/test_launch_real.py.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from backend.app.contracts.models import AgentLaunchRequest, AgentRunStatus
from backend.app.core.errors import AppError
from backend.app.execution import launcher as module
from backend.app.execution import process_supervisor
from backend.app.execution.agent_ports import (
    CredentialFingerprint,
    CredentialRevocation,
    StagedCredential,
)
from backend.app.execution.agent_profiles import BoundaryKind, RuntimeProfile
from backend.app.execution.appcontainer import AppContainerFacts, verification_failed
from backend.app.execution.agent_staging import tool_snapshot_tampered
from backend.app.execution.launcher import (
    APPCONTAINER_AUTHORITY,
    CREDENTIAL_NOT_STAGED_LIMITATION,
    RESTRICTED_AUTHORITY,
    AgentLauncher,
    appcontainer_authority,
)
from backend.app.execution.process_supervisor import IS_WINDOWS

pytestmark = pytest.mark.skipif(not IS_WINDOWS, reason="the AppContainer path is Windows-only")

CHANGE = uuid4()
TOKEN = "sk-ant-oat01-FAKEtokenForLauncherTests0123456789"


@dataclass
class FakeLease:
    id: UUID
    profile_name: str
    package_sid: str
    container_path: Path
    workspace_path: Path


@dataclass
class FakeProvider:
    lease: FakeLease
    error: AppError | None = None
    ensured: list[UUID] = field(default_factory=list)
    finished: list[dict] = field(default_factory=list)
    credentials: list[CredentialFingerprint] = field(default_factory=list)

    def ensure(self, change_id, source_repository, *, run_id):
        if self.error is not None:
            raise self.error
        self.ensured.append(run_id)
        return self.lease

    def finish_run(self, workspace_id, run_id, *, facts, status, limitations=()):
        self.finished.append({"workspace_id": workspace_id, "run_id": run_id, "facts": facts,
                              "status": status, "limitations": list(limitations)})

    def record_credential(self, workspace_id, fingerprint):
        self.credentials.append(fingerprint)


@dataclass
class FakeStager:
    stage: bool = True
    staged: list[StagedCredential] = field(default_factory=list)
    revoked: list[StagedCredential] = field(default_factory=list)

    def stage_agent_credential(self, change_id, kind, home):
        if not self.stage:
            return None
        path = Path(home) / ".claude" / ".credentials.json"
        data = ('{"claudeAiOauth": {"accessToken": "%s"}}' % TOKEN).encode()
        path.write_bytes(data)
        credential = StagedCredential(kind, path, CredentialFingerprint.from_bytes(kind, data),
                                      "0" * 64, redaction_values=(TOKEN,))
        self.staged.append(credential)
        return credential

    def revoke_staged_credential(self, staged):
        self.revoked.append(staged)
        staged.path.unlink(missing_ok=True)
        return CredentialRevocation(deleted=True, changed_during_run=False)

    def purge_staged_credentials(self, home):
        return True


@pytest.fixture
def box(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    container = tmp_path / "AC"
    (container / "ws").mkdir(parents=True)
    exe = tmp_path / "host-bin" / "claude.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ fake claude")
    monkeypatch.setattr(module, "resolve_argv", lambda name, env, root: [str(exe)])

    restricted_calls: list[object] = []

    def restricted_sentinel(*args, **kwargs):
        restricted_calls.append(args)
        raise AssertionError("the restricted-token launcher must never run for claude")

    monkeypatch.setattr(module, "spawn_restricted_supervised", restricted_sentinel)
    monkeypatch.setattr(process_supervisor, "spawn_restricted_supervised", restricted_sentinel)

    spawn_calls: list[dict] = []

    def failing_spawn(argv, **kwargs):
        spawn_calls.append({"argv": list(argv), **kwargs})
        raise verification_failed("integrity")

    monkeypatch.setattr(module, "spawn_appcontainer_supervised", failing_spawn)

    drives = {"mapped": [], "unmapped": [], "map_error": None, "unmap_result": True}

    def fake_map(target):
        if drives["map_error"] is not None:
            raise drives["map_error"]
        drives["mapped"].append(Path(target))
        return "Z:"

    def fake_unmap(letter, target):
        drives["unmapped"].append((letter, Path(target)))
        return drives["unmap_result"]

    monkeypatch.setattr(module, "map_drive", fake_map)
    monkeypatch.setattr(module, "unmap_drive", fake_unmap)
    lease = FakeLease(uuid4(), "sentinel.test.fake", "S-1-15-2-1-2-3-4-5-6-7",
                      container, container / "ws")
    provider = FakeProvider(lease)
    stager = FakeStager()
    launcher = AgentLauncher(workspaces=provider, credentials=stager)
    seen: list = []
    launcher.on_update = seen.append
    return {"repo": repo, "container": container, "exe": exe, "launcher": launcher,
            "provider": provider, "stager": stager, "spawn_calls": spawn_calls,
            "restricted_calls": restricted_calls, "seen": seen, "drives": drives}


def claude(**kw) -> AgentLaunchRequest:
    kw.setdefault("timeout_seconds", 10)
    return AgentLaunchRequest(adapter="claude", executable="claude", **kw)


def test_verification_failure_is_an_error_run_that_never_falls_back(box):
    run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert run.status is AgentRunStatus.ERROR
    assert run.restricted_token_applied is False
    assert run.authority_reduction is None
    assert any("APPCONTAINER_VERIFICATION_FAILED" in text for text in run.limitations)
    assert RESTRICTED_AUTHORITY not in run.limitations
    assert box["restricted_calls"] == []
    # The AppContainer spawn was attempted with the snapshot, the workspace and a built env.
    (call,) = box["spawn_calls"]
    snapshot = box["container"] / "tools" / "claude.exe"
    assert call["argv"] == [str(snapshot)] and snapshot.read_bytes() == box["exe"].read_bytes()
    # Spike 007: the run's cwd is the workspace on a per-run drive mapped to the AC folder.
    assert Path(call["cwd"]) == Path("Z:\\") / "ws"
    assert box["drives"]["mapped"] == [box["container"]]
    assert box["drives"]["unmapped"] == [("Z:", box["container"])]
    assert call["profile_name"] == "sentinel.test.fake"
    assert call["expected_package_sid"] == "S-1-15-2-1-2-3-4-5-6-7"
    assert tuple(call["capabilities"]) == ("internetClient",)
    env = call["env"]
    assert env["USERPROFILE"] == str(box["container"] / "home")
    assert env["PATH"].split(";")[0] == str(box["container"] / "tools")
    assert env["DISABLE_AUTOUPDATER"] == "1" and "LOCALAPPDATA" in env
    assert env["CLAUDE_CODE_USE_POWERSHELL_TOOL"] == "1"
    assert "CLAUDE_CODE_GIT_BASH_PATH" not in env
    # The credential was staged, fingerprinted on the workspace, and revoked exactly once.
    assert len(box["stager"].staged) == 1 and len(box["stager"].revoked) == 1
    assert box["provider"].credentials == [box["stager"].staged[0].fingerprint]
    assert not box["stager"].staged[0].path.exists()
    (finished,) = box["provider"].finished
    assert finished["status"] == "ERROR" and finished["facts"] is None
    assert finished["run_id"] == run.id == box["provider"].ensured[0]


def test_staged_token_is_added_to_redaction(box):
    box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    redact = box["spawn_calls"][0]["redact"]
    assert redact(f"leak {TOKEN} end") == "leak [REDACTED] end"


def test_tampered_snapshot_is_an_error_run_and_never_spawns(box):
    box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    (box["container"] / "tools" / "claude.exe").write_bytes(b"MZ planted by the agent")
    box["spawn_calls"].clear()
    box["stager"].staged.clear()
    box["stager"].revoked.clear()
    run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert run.status is AgentRunStatus.ERROR
    assert any("AGENT_TOOL_SNAPSHOT_TAMPERED" in text for text in run.limitations)
    assert box["spawn_calls"] == [] and box["restricted_calls"] == []
    assert box["stager"].staged == [] and box["stager"].revoked == []
    assert [item["status"] for item in box["provider"].finished] == ["ERROR", "ERROR"]


def test_snapshot_error_from_the_staging_module_is_an_error_run(box, monkeypatch):
    def tampered(*args, **kwargs):
        raise tool_snapshot_tampered()

    monkeypatch.setattr(module, "ensure_tool_snapshot", tampered)
    run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert run.status is AgentRunStatus.ERROR
    assert "The agent did not start (AGENT_TOOL_SNAPSHOT_TAMPERED)" in " ".join(run.limitations)
    assert box["spawn_calls"] == [] and box["stager"].revoked == []
    assert len(box["provider"].finished) == 1


def test_missing_credential_is_disclosed(box):
    box["stager"].stage = False
    run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert CREDENTIAL_NOT_STAGED_LIMITATION in run.limitations
    assert box["stager"].revoked == []


def test_codex_fails_closed_before_any_run(box, monkeypatch):
    monkeypatch.setattr(module, "capture", lambda *a, **k: pytest.fail("nothing may start"))
    with pytest.raises(AppError) as caught:
        box["launcher"].launch(CHANGE, str(box["repo"]), AgentLaunchRequest(
            adapter="codex", executable="codex", timeout_seconds=10), 10_000)
    assert caught.value.code == "AGENT_RUNTIME_PROFILE_UNAVAILABLE"
    assert caught.value.status_code == 409
    assert box["seen"] == [] and box["provider"].ensured == []


def test_claude_without_a_workspace_provider_is_refused(tmp_path, monkeypatch):
    launcher = AgentLauncher()
    seen: list = []
    launcher.on_update = seen.append
    monkeypatch.setattr(module, "spawn_restricted_supervised",
                        lambda *a, **k: pytest.fail("restricted fallback"))
    with pytest.raises(AppError) as caught:
        launcher.launch(CHANGE, str(tmp_path), claude(), 10_000)
    assert caught.value.code == "AGENT_WORKSPACE_UNAVAILABLE"
    assert caught.value.status_code == 503
    assert seen == []


def test_claude_off_windows_is_unsupported(box, monkeypatch):
    monkeypatch.setattr(module, "IS_WINDOWS", False)
    with pytest.raises(AppError) as caught:
        box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert caught.value.code == "APPCONTAINER_UNSUPPORTED"
    assert caught.value.status_code == 501
    assert box["seen"] == [] and box["provider"].ensured == []


def test_builtin_profile_override_is_refused():
    with pytest.raises(ValueError):
        AgentLauncher(profiles={"claude": RuntimeProfile("claude", BoundaryKind.RESTRICTED_TOKEN)})


def test_workspace_precondition_errors_propagate(box):
    box["provider"].error = AppError("WORKSPACE_SOURCE_DIRTY", "dirty", status_code=409)
    with pytest.raises(AppError) as caught:
        box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert caught.value.code == "WORKSPACE_SOURCE_DIRTY"
    assert box["seen"] == [] and box["provider"].finished == []
    assert box["stager"].staged == []


@pytest.mark.parametrize("argv", [
    ["C:\\node\\node.exe", "C:\\node\\cli.js"],
    ["C:\\shim\\claude.cmd"],
    ["claude.exe"],
])
def test_claude_requires_a_native_executable(box, monkeypatch, argv):
    monkeypatch.setattr(module, "resolve_argv", lambda name, env, root: list(argv))
    with pytest.raises(AppError) as caught:
        box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert caught.value.code == "AGENT_RUNTIME_PROFILE_UNAVAILABLE"
    assert "native executable required" in caught.value.message
    assert box["provider"].ensured == []


@pytest.mark.parametrize("key", ["LOCALAPPDATA", "APPDATA", "CLAUDE_CODE_GIT_BASH_PATH",
                                 "DISABLE_AUTOUPDATER", "TEMP"])
def test_boundary_environment_keys_cannot_be_forwarded(box, key):
    with pytest.raises(AppError) as caught:
        box["launcher"].launch(CHANGE, str(box["repo"]), claude(environment_keys=[key]), 10_000)
    assert caught.value.code == "AGENT_ENVIRONMENT_KEY_DENIED"
    assert box["provider"].ensured == []


def test_appcontainer_branch_has_no_restricted_fallback():
    for function in (AgentLauncher._launch_appcontainer, AgentLauncher._prepare_appcontainer):
        assert "spawn_restricted_supervised" not in inspect.getsource(function)
        assert "RESTRICTED_AUTHORITY" not in inspect.getsource(function)


def test_authority_text_is_built_from_verified_facts():
    facts = AppContainerFacts(
        profile_name="p", package_sid="S-1-15-2-9", is_appcontainer=True,
        integrity_rid=0x1000, capability_sids=("S-1-15-3-1",), job_verified=True,
        verified_at=datetime.now(UTC),
    )
    text = appcontainer_authority(facts)
    assert text is not None and len(text) <= 1024
    assert "S-1-15-2-9" in text and "internetClient S-1-15-3-1" in text and "0x1000" in text
    assert "sandbox" not in text.lower() and "isolat" not in text.lower()
    assert text != RESTRICTED_AUTHORITY and APPCONTAINER_AUTHORITY.startswith("AppContainer")
    assert appcontainer_authority(None) is None
    unverified = AppContainerFacts("p", "S", True, 0x1000, (), False, datetime.now(UTC))
    assert appcontainer_authority(unverified) is None


def test_a_drive_mapping_failure_is_an_error_run_that_never_spawns(box):
    box["drives"]["map_error"] = OSError("No free drive letter is available for the workspace")
    run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert run.status is AgentRunStatus.ERROR
    assert any("AGENT_WORKSPACE_DRIVE_UNAVAILABLE" in text for text in run.limitations)
    assert box["spawn_calls"] == [] and box["restricted_calls"] == []
    assert box["drives"]["unmapped"] == []
    assert len(box["stager"].revoked) == len(box["stager"].staged)
    (finished,) = box["provider"].finished
    assert finished["status"] == "ERROR"


def test_the_drive_is_named_in_the_run_and_a_failed_removal_is_reported(box):
    box["drives"]["unmap_result"] = False
    run = box["launcher"].launch(CHANGE, str(box["repo"]), claude(), 10_000)
    assert any("exposed to the agent as drive Z:" in text for text in run.limitations)
    assert any("drive Z: could not be confirmed removed" in text for text in run.limitations)
    # Removal is attempted exactly once, even though both `after` and the finally run.
    assert box["drives"]["unmapped"] == [("Z:", box["container"])]
