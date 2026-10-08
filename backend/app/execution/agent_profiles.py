"""Per-adapter runtime profiles: which launch boundary each agent adapter gets.

The boundary is a declared property of each adapter's :class:`RuntimeProfile`
(user decision D-01), resolved once per launch by :func:`resolve_profile`. It is
never chosen by platform detection or by exception handling: an adapter whose
profile says ``APPCONTAINER`` either launches inside a verified AppContainer or
does not launch at all, and an adapter whose profile says ``UNAVAILABLE``
(``codex``, D-02) always fails closed.

Built-in profiles cannot be overridden by callers. Pure module: no Win32, no
process starts and no file I/O.
"""

from __future__ import annotations

import ntpath
import os
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class BoundaryKind(StrEnum):
    RESTRICTED_TOKEN = "restricted_token"
    APPCONTAINER = "appcontainer"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    """How one adapter is launched.

    ``static_env`` holds fixed ``(key, value)`` pairs added to an AppContainer
    environment; it can never replace a key the boundary itself controls
    (see :data:`PROTECTED_ENV_KEYS`).
    """

    adapter: str
    boundary: BoundaryKind
    capabilities: tuple[str, ...] = ()
    tool_snapshot: bool = False
    staged_home: bool = False
    credential_kind: str | None = None
    static_env: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    requires_native_executable: bool = False
    git_bash_env: bool = False
    powershell_tool: bool = False
    workspace_drive: bool = False
    unavailable_reason: str | None = None


# Keys an AppContainer environment derives from the boundary itself (container
# folder, staged home, known folders). A profile can never override them.
PROTECTED_ENV_KEYS = frozenset({
    "PATH", "LOCALAPPDATA", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME",
    "APPDATA", "HOMEDRIVE", "HOMEPATH", "COMSPEC", "PSMODULEPATH",
})
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BASE_KEYS = ("SystemRoot", "windir", "COMSPEC", "LOCALAPPDATA", "TEMP", "TMP")

CODEX_UNAVAILABLE_REASON = (
    "The codex adapter has no tested AppContainer runtime profile yet, so Sentinel refuses "
    "to launch it rather than run it without a verified boundary."
)

BUILTIN_PROFILES: Mapping[str, RuntimeProfile] = types.MappingProxyType({
    "generic": RuntimeProfile("generic", BoundaryKind.RESTRICTED_TOKEN),
    "claude": RuntimeProfile(
        "claude", BoundaryKind.APPCONTAINER,
        capabilities=("internetClient",),
        tool_snapshot=True,
        staged_home=True,
        credential_kind="claude-oauth-file",
        # Validated in spike 004: no self-update inside the box, no system Git
        # config, no interactive Git credential prompt. Spike 007: Git Bash
        # (MSYS2) cannot initialise in the box, so the agent's shell is its
        # PowerShell tool, run from the workspace on a per-run drive.
        static_env=(
            ("DISABLE_AUTOUPDATER", "1"),
            ("GIT_CONFIG_NOSYSTEM", "1"),
            ("GIT_TERMINAL_PROMPT", "0"),
            ("CLAUDE_CODE_USE_POWERSHELL_TOOL", "1"),
        ),
        requires_native_executable=True,
        powershell_tool=True,
        workspace_drive=True,
    ),
    "codex": RuntimeProfile(
        "codex", BoundaryKind.UNAVAILABLE, unavailable_reason=CODEX_UNAVAILABLE_REASON,
    ),
})


def validate_extra_profiles(
    extra: Mapping[str, RuntimeProfile] | None,
) -> Mapping[str, RuntimeProfile]:
    """A read-only copy of caller-supplied profiles, or ``ValueError``.

    Built-in adapter names cannot be redefined (so ``claude`` can never be
    moved onto the restricted-token path), every profile must name its own
    adapter and declare exactly one :class:`BoundaryKind`, and ``static_env``
    may not override a protected key.
    """

    validated: dict[str, RuntimeProfile] = {}
    for name, profile in (extra or {}).items():
        if name in BUILTIN_PROFILES:
            raise ValueError(f"The built-in runtime profile '{name}' cannot be overridden.")
        if not isinstance(profile, RuntimeProfile):
            raise ValueError(f"The runtime profile for '{name}' is not a RuntimeProfile.")
        if profile.adapter != name:
            raise ValueError(f"The runtime profile for '{name}' names another adapter.")
        if not isinstance(profile.boundary, BoundaryKind):
            raise ValueError(f"The runtime profile for '{name}' has no valid boundary.")
        if profile.boundary is BoundaryKind.UNAVAILABLE and not profile.unavailable_reason:
            raise ValueError(f"The unavailable runtime profile '{name}' needs a reason.")
        for key, value in profile.static_env:
            if not _ENV_KEY.fullmatch(key) or not isinstance(value, str) or "\0" in value:
                raise ValueError(f"The runtime profile '{name}' has an invalid environment key.")
            if key.upper() in PROTECTED_ENV_KEYS:
                raise ValueError(
                    f"The runtime profile '{name}' may not override the protected key {key}.")
        validated[name] = profile
    return types.MappingProxyType(validated)


def resolve_profile(
    adapter: str, extra: Mapping[str, RuntimeProfile] | None = None,
) -> RuntimeProfile:
    """The profile for ``adapter``: built-in first, then ``extra``, else restricted token."""

    builtin = BUILTIN_PROFILES.get(adapter)
    if builtin is not None:
        return builtin
    if extra is not None and adapter in extra:
        return extra[adapter]
    return RuntimeProfile(adapter, BoundaryKind.RESTRICTED_TOKEN)


def appcontainer_environment(
    profile: RuntimeProfile, *, base_env: Mapping[str, str], home: Path | None,
    tools_dir: Path | None, git_cmd_dir: Path | None, node_dir: Path | None,
    git_bash: Path | None,
) -> dict[str, str]:
    """The complete environment block for an AppContainer agent; nothing else is added.

    ``base_env`` is ``appcontainer.base_environment(...)``: its ``LOCALAPPDATA``
    comes from the known-folder API (never ``os.environ``, research Pitfall 2),
    and it is copied as is. ``PATH`` is ``tools_dir`` → Git ``cmd`` → Node →
    the base ``PATH``. The home keys are set only when the profile stages a
    home; ``CLAUDE_CODE_GIT_BASH_PATH`` only when the profile asks for it and
    Git Bash exists; ``PSModulePath`` (Windows PowerShell's system modules only)
    when the profile uses a PowerShell tool.
    """

    if profile.boundary is not BoundaryKind.APPCONTAINER:
        raise ValueError("appcontainer_environment needs an AppContainer runtime profile.")
    missing = [key for key in (*_BASE_KEYS, "PATH") if not base_env.get(key)]
    if missing:
        raise ValueError(f"The AppContainer base environment lacks {', '.join(missing)}.")
    env = {key: base_env[key] for key in _BASE_KEYS}
    entries = [str(entry) for entry in (tools_dir, git_cmd_dir, node_dir) if entry is not None]
    entries.extend(item for item in base_env["PATH"].split(os.pathsep) if item)
    env["PATH"] = os.pathsep.join(dict.fromkeys(entries))
    if profile.staged_home:
        if home is None:
            raise ValueError("This runtime profile needs a staged home.")
        text = str(home)
        drive, rest = ntpath.splitdrive(text)
        env.update({
            "USERPROFILE": text,
            "HOME": text,
            "APPDATA": str(home / "AppData" / "Roaming"),
            "HOMEDRIVE": drive,
            "HOMEPATH": rest or "\\",
        })
    if profile.git_bash_env and git_bash is not None:
        env["CLAUDE_CODE_GIT_BASH_PATH"] = str(git_bash)
    if profile.powershell_tool:
        env["PSModulePath"] = ntpath.join(
            base_env["SystemRoot"], "System32", "WindowsPowerShell", "v1.0", "Modules")
    for key, value in profile.static_env:
        if key.upper() in PROTECTED_ENV_KEYS:
            raise ValueError(f"The runtime profile may not override the protected key {key}.")
        env[key] = value
    return env
