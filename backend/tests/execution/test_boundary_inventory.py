"""Plan 02-01 (SC1): every capability and ACE Sentinel gives an AppContainer is listed here.

Adding a capability or a new grant site fails these tests until the inventory
(and the need test in ``backend/tests/workspace/test_capability_need_real.py``)
is updated with a demonstrated reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

from backend.app.execution.agent_profiles import BUILTIN_PROFILES
from backend.app.execution.appcontainer import CAPABILITY_SIDS
from backend.app.execution.check_box import NETWORK_CAPABILITIES

APP = Path(__file__).resolve().parents[2] / "app"

# capability -> (who gets it, the test that demonstrates the need)
CAPABILITY_INVENTORY = {
    "internetClient": ("claude, codex and boxed agents (model API); check boxes only with network=True, "
                       "which no caller passes",
                       "test_capability_need_real.py::test_internet_client_is_needed_and_sufficient"),
}
# file -> package-SID grant functions it may call (defined only in execution/acl.py)
GRANT_SITES = {
    "execution/check_box.py": {"grant_package_read", "revoke_package_read"},
}


def _sources():
    for path in APP.rglob("*.py"):
        yield path, path.read_text(encoding="utf-8")


def test_known_capabilities_are_exactly_the_inventory() -> None:
    assert set(CAPABILITY_SIDS) == set(CAPABILITY_INVENTORY)
    assert dict(CAPABILITY_SIDS) == {"internetClient": "S-1-15-3-1"}


def test_builtin_profiles_request_only_inventoried_capabilities() -> None:
    granted = {name: profile.capabilities for name, profile in BUILTIN_PROFILES.items()}
    assert granted == {"generic": (), "claude": ("internetClient",), "codex": ("internetClient",),
                       "boxed": ("internetClient",)}
    assert NETWORK_CAPABILITIES == ("internetClient",)


def test_no_caller_opens_a_check_box_with_network() -> None:
    offenders = []
    for path, source in _sources():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if (keyword.arg == "network" and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True):
                        offenders.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert offenders == []


def test_no_blanket_application_package_sid_appears_in_the_backend() -> None:
    blanket = ("S-1-15-2-1\"", "S-1-15-2-1'", "S-1-15-2-2", "ALL APPLICATION PACKAGES",
               "ALL RESTRICTED APPLICATION PACKAGES", "*S-1-15-2-1:")
    hits = [f"{path.relative_to(APP)}: {needle}" for path, source in _sources()
            for needle in blanket if needle in source]
    assert hits == []


def test_package_sid_grants_happen_only_at_the_inventoried_sites() -> None:
    found: dict[str, set[str]] = {}
    for path, source in _sources():
        relative = path.relative_to(APP).as_posix()
        for node in ast.walk(ast.parse(source)):
            name = (node.id if isinstance(node, ast.Name)
                    else node.attr if isinstance(node, ast.Attribute) else None)
            if name in {"grant_package_read", "revoke_package_read", "_run_icacls_change"}:
                found.setdefault(relative, set()).add(name)
    found.get("execution/acl.py", set()).discard("_run_icacls_change")
    assert {path: names for path, names in found.items() if names} == GRANT_SITES
    definitions = {path.relative_to(APP).as_posix() for path, source in _sources()
                   for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.FunctionDef)
                   and node.name in {"grant_package_read", "revoke_package_read"}}
    assert definitions == {"execution/acl.py"}


def test_the_grant_names_only_the_package_sid_with_read_execute() -> None:
    source = (APP / "execution" / "acl.py").read_text(encoding="utf-8")
    assert '["/grant", f"*{package_sid}:(OI)(CI)(RX)"]' in source
    assert '["/remove:g", f"*{package_sid}"]' in source


def test_the_workspace_package_gets_no_grant() -> None:
    """The workspace is the box's own AC folder (and its per-run drive maps that folder)."""

    for path in (APP / "workspace").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "grant_package_read" not in source and "icacls" not in source, path
    drive = (APP / "execution" / "dos_drive.py").read_text(encoding="utf-8")
    assert "icacls" not in drive and "SetNamedSecurityInfo" not in drive
