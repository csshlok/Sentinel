"""Per-adapter runtime profiles (D-01, D-02) and the AppContainer environment template.

Platform-independent: nothing here touches Win32.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.execution.agent_profiles import (
    BUILTIN_PROFILES,
    PROTECTED_ENV_KEYS,
    BoundaryKind,
    RuntimeProfile,
    appcontainer_environment,
    resolve_profile,
    validate_extra_profiles,
)

BASE_ENV = {
    "SystemRoot": r"C:\Windows",
    "windir": r"C:\Windows",
    "COMSPEC": r"C:\Windows\System32\cmd.exe",
    "PATH": r"C:\Windows\System32",
    "LOCALAPPDATA": r"C:\Users\someone\AppData\Local",
    "TEMP": r"C:\ac\Temp",
    "TMP": r"C:\ac\Temp",
}

CUSTOM = RuntimeProfile("fake-node", BoundaryKind.APPCONTAINER, staged_home=True)


# -- invariants (assumption-delta decision: the launch boundary is a first-class,
# -- per-adapter property of RuntimeProfile, resolved once per launch) -----------


def test_every_builtin_profile_declares_exactly_one_boundary_kind():
    """PROMOTE decision: each built-in adapter resolves to exactly one declared boundary."""

    assert set(BUILTIN_PROFILES) == {"generic", "claude", "codex", "boxed"}
    for name, profile in BUILTIN_PROFILES.items():
        assert profile.adapter == name
        assert isinstance(profile.boundary, BoundaryKind)
        assert [kind for kind in BoundaryKind if kind is profile.boundary] == [profile.boundary]


@pytest.mark.parametrize("extra", [None, {}, {"fake-node": CUSTOM}])
def test_claude_always_resolves_to_appcontainer(extra):
    """PROMOTE decision: claude can never resolve to the restricted-token path (D-01)."""

    profile = resolve_profile("claude", extra)
    assert profile.boundary is BoundaryKind.APPCONTAINER
    assert profile is BUILTIN_PROFILES["claude"]


@pytest.mark.parametrize("name", ["claude", "generic", "codex", "boxed"])
def test_builtin_profiles_cannot_be_overridden(name):
    """PROMOTE decision: a caller cannot redefine a built-in adapter's boundary."""

    with pytest.raises(ValueError, match="cannot be overridden"):
        validate_extra_profiles({name: RuntimeProfile(name, BoundaryKind.RESTRICTED_TOKEN)})


def test_claude_resolves_to_appcontainer_even_if_extra_names_it():
    # validate_extra_profiles refuses this mapping; resolve_profile still ignores it.
    sneaky = {"claude": RuntimeProfile("claude", BoundaryKind.RESTRICTED_TOKEN)}
    assert resolve_profile("claude", sneaky).boundary is BoundaryKind.APPCONTAINER


# -- built-in contents ------------------------------------------------------------


def test_builtin_profile_contents():
    assert BUILTIN_PROFILES["generic"].boundary is BoundaryKind.RESTRICTED_TOKEN
    claude = BUILTIN_PROFILES["claude"]
    assert claude.capabilities == ("internetClient",)
    assert claude.tool_snapshot and claude.staged_home
    assert claude.credential_kind == "claude-oauth-file"
    assert claude.requires_native_executable and not claude.git_bash_env
    assert claude.powershell_tool and claude.workspace_drive
    assert dict(claude.static_env) == {
        "DISABLE_AUTOUPDATER": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "CLAUDE_CODE_USE_POWERSHELL_TOOL": "1",
    }
    codex = BUILTIN_PROFILES["codex"]
    assert codex.boundary is BoundaryKind.APPCONTAINER
    assert codex.capabilities == ("internetClient",)
    assert codex.tool_snapshot and codex.staged_home and codex.requires_native_executable
    assert codex.credential_kind == "codex-auth-file"
    assert dict(codex.home_env) == {"CODEX_HOME": ".codex"}
    assert codex.powershell_tool and codex.workspace_drive
    boxed = BUILTIN_PROFILES["boxed"]
    assert boxed.boundary is BoundaryKind.APPCONTAINER
    assert boxed.capabilities == ("internetClient",)
    assert boxed.tool_snapshot and boxed.staged_home and boxed.requires_native_executable
    assert boxed.credential_kind is None and boxed.home_env == ()


def test_builtin_table_is_read_only():
    with pytest.raises(TypeError):
        BUILTIN_PROFILES["claude"] = RuntimeProfile("claude", BoundaryKind.RESTRICTED_TOKEN)  # type: ignore[index]


def test_unknown_adapter_resolves_to_restricted_token_and_custom_name_to_its_profile():
    assert resolve_profile("secretive").boundary is BoundaryKind.RESTRICTED_TOKEN
    assert resolve_profile("secretive").adapter == "secretive"
    extra = validate_extra_profiles({"fake-node": CUSTOM})
    assert resolve_profile("fake-node", extra) is CUSTOM


# -- validation -------------------------------------------------------------------


@pytest.mark.parametrize("key", ["PATH", "LOCALAPPDATA", "SystemRoot", "windir", "TEMP", "TMP",
                                 "USERPROFILE", "HOME", "APPDATA", "path", "Home"])
def test_static_env_may_not_override_protected_keys(key):
    profile = RuntimeProfile("fake-node", BoundaryKind.APPCONTAINER, static_env=((key, "x"),))
    with pytest.raises(ValueError, match="protected key"):
        validate_extra_profiles({"fake-node": profile})


def test_validation_rejects_mismatched_names_bad_types_and_unexplained_unavailability():
    with pytest.raises(ValueError, match="another adapter"):
        validate_extra_profiles({"x": CUSTOM})
    with pytest.raises(ValueError, match="not a RuntimeProfile"):
        validate_extra_profiles({"x": object()})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="needs a reason"):
        validate_extra_profiles({"x": RuntimeProfile("x", BoundaryKind.UNAVAILABLE)})
    with pytest.raises(ValueError, match="no valid boundary"):
        validate_extra_profiles({"x": RuntimeProfile("x", "appcontainer")})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid environment key"):
        validate_extra_profiles({"x": RuntimeProfile(
            "x", BoundaryKind.APPCONTAINER, static_env=(("BAD KEY", "1"),))})


def test_validated_mapping_is_read_only():
    extra = validate_extra_profiles({"fake-node": CUSTOM})
    with pytest.raises(TypeError):
        extra["other"] = CUSTOM  # type: ignore[index]


# -- environment ------------------------------------------------------------------


def test_claude_environment_has_exactly_the_validated_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "not-the-real-one"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-appear")
    home = Path(r"C:\ac\home")
    env = appcontainer_environment(
        BUILTIN_PROFILES["claude"], base_env=BASE_ENV, home=home,
        tools_dir=Path(r"C:\ac\tools"), git_cmd_dir=Path(r"C:\Program Files\Git\cmd"),
        node_dir=Path(r"C:\Program Files\nodejs"),
        git_bash=Path(r"C:\Program Files\Git\bin\bash.exe"),
    )
    assert set(env) == {
        "SystemRoot", "windir", "COMSPEC", "LOCALAPPDATA", "TEMP", "TMP", "PATH",
        "USERPROFILE", "HOME", "APPDATA", "HOMEDRIVE", "HOMEPATH",
        "DISABLE_AUTOUPDATER", "GIT_CONFIG_NOSYSTEM", "GIT_TERMINAL_PROMPT",
        "CLAUDE_CODE_USE_POWERSHELL_TOOL", "PSModulePath",
    }
    assert env["LOCALAPPDATA"] == BASE_ENV["LOCALAPPDATA"]  # never os.environ (Pitfall 2)
    assert env["PATH"].split(";") == [
        r"C:\ac\tools", r"C:\Program Files\Git\cmd", r"C:\Program Files\nodejs",
        r"C:\Windows\System32",
    ]
    assert env["USERPROFILE"] == env["HOME"] == str(home)
    assert env["APPDATA"] == str(home / "AppData" / "Roaming")
    assert env["HOMEDRIVE"] == "C:" and env["HOMEPATH"] == r"\ac\home"
    # Spike 007: Git Bash cannot run in the box; the agent's shell is PowerShell.
    assert "CLAUDE_CODE_GIT_BASH_PATH" not in env
    assert env["CLAUDE_CODE_USE_POWERSHELL_TOOL"] == "1"
    assert env["PSModulePath"] == r"C:\Windows\System32\WindowsPowerShell\v1.0\Modules"
    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
    for key in ("SystemRoot", "windir", "COMSPEC", "TEMP", "TMP"):
        assert env[key] == BASE_ENV[key]


def test_environment_without_git_bash_or_optional_dirs():
    env = appcontainer_environment(
        BUILTIN_PROFILES["claude"], base_env=BASE_ENV, home=Path(r"C:\ac\home"),
        tools_dir=Path(r"C:\ac\tools"), git_cmd_dir=None, node_dir=None, git_bash=None,
    )
    assert "CLAUDE_CODE_GIT_BASH_PATH" not in env
    assert env["PATH"].split(";") == [r"C:\ac\tools", r"C:\Windows\System32"]


def test_environment_without_staged_home_has_no_home_keys():
    profile = RuntimeProfile("bare", BoundaryKind.APPCONTAINER)
    env = appcontainer_environment(profile, base_env=BASE_ENV, home=None, tools_dir=None,
                                   git_cmd_dir=None, node_dir=None, git_bash=None)
    assert set(env) == {"SystemRoot", "windir", "COMSPEC", "LOCALAPPDATA", "TEMP", "TMP", "PATH"}


def test_environment_refuses_a_non_appcontainer_profile_and_an_incomplete_base():
    with pytest.raises(ValueError):
        appcontainer_environment(BUILTIN_PROFILES["generic"], base_env=BASE_ENV, home=None,
                                 tools_dir=None, git_cmd_dir=None, node_dir=None, git_bash=None)
    incomplete = {k: v for k, v in BASE_ENV.items() if k != "LOCALAPPDATA"}
    with pytest.raises(ValueError, match="LOCALAPPDATA"):
        appcontainer_environment(BUILTIN_PROFILES["claude"], base_env=incomplete,
                                 home=Path(r"C:\h"), tools_dir=None, git_cmd_dir=None,
                                 node_dir=None, git_bash=None)


def test_protected_keys_cover_the_plan_list():
    assert {"PATH", "LOCALAPPDATA", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
            "HOME", "APPDATA"} <= PROTECTED_ENV_KEYS


def test_git_bash_path_is_set_only_for_a_profile_that_asks_for_it():
    profile = RuntimeProfile("bash", BoundaryKind.APPCONTAINER, git_bash_env=True)
    env = appcontainer_environment(
        profile, base_env=BASE_ENV, home=None, tools_dir=None, git_cmd_dir=None,
        node_dir=None, git_bash=Path(r"C:\Program Files\Git\bin\bash.exe"))
    assert env["CLAUDE_CODE_GIT_BASH_PATH"] == r"C:\Program Files\Git\bin\bash.exe"
    assert "PSModulePath" not in env


def test_claude_profile_uses_the_powershell_tool_on_a_workspace_drive():
    profile = BUILTIN_PROFILES["claude"]
    assert profile.powershell_tool and profile.workspace_drive
    assert not profile.git_bash_env


def test_a_profile_cannot_override_psmodulepath():
    bad = RuntimeProfile("bad", BoundaryKind.APPCONTAINER,
                         static_env=(("PSModulePath", r"C:\evil"),))
    with pytest.raises(ValueError):
        validate_extra_profiles({"bad": bad})


@pytest.mark.parametrize("relative", ["..", "../x", "a/../../b", "C:/x", "/abs", r"\\server\x", ""])
def test_home_variables_must_stay_inside_the_staged_home(relative):
    profile = RuntimeProfile("homey", BoundaryKind.APPCONTAINER, staged_home=True,
                             home_env=(("TOOL_HOME", relative),))
    with pytest.raises(ValueError, match="home"):
        validate_extra_profiles({"homey": profile})


def test_home_variables_need_a_staged_home_and_an_unprotected_key():
    with pytest.raises(ValueError, match="home variable"):
        validate_extra_profiles({"a": RuntimeProfile("a", BoundaryKind.APPCONTAINER,
                                                     home_env=(("TOOL_HOME", ".tool"),))})
    with pytest.raises(ValueError, match="home variable"):
        validate_extra_profiles({"b": RuntimeProfile("b", BoundaryKind.APPCONTAINER,
                                                     staged_home=True,
                                                     home_env=(("APPDATA", ".tool"),))})


def test_codex_home_points_inside_the_staged_home(tmp_path):
    from backend.app.execution.appcontainer import base_environment

    home = tmp_path / "home"
    env = appcontainer_environment(
        BUILTIN_PROFILES["codex"], base_env=base_environment(tmp_path), home=home,
        tools_dir=None, git_cmd_dir=None, node_dir=None, git_bash=None)
    assert env["CODEX_HOME"] == str(home / ".codex")
    assert env["USERPROFILE"] == str(home)
