"""Toolchain -> confined runtime mapping and the checks.unconfined opt-in (05-03 task 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.contracts.models import ChangeContract, ChangeView, ReviewState, RiskLevel
from backend.app.core.change_repository import ChangeRepository, StoredChange
from backend.app.core.database import Database
from backend.app.core.errors import AppError
from backend.app.execution import check_toolchains as toolchains
from backend.app.execution.check_runtime import PythonRuntime, RuntimeSnapshot
from backend.app.execution.check_toolchains import (
    ALLOWED_EXECUTABLES,
    CHECKS_UNCONFINED_SCOPE,
    CONFINED_TOOLCHAINS,
    UNCONFINED_TOOLCHAINS,
    RuntimeBuilders,
    is_unconfined_toolchain,
    resolve_check_runtime,
)
from backend.app.identity.models import Delegation
from backend.app.identity.repository import DelegationRepository
from backend.app.policy.models import PolicyOperation
from backend.app.policy.service import DelegationPolicyEngine
from backend.app.verification import validation
from backend.app.execution import runner as bounded_runner


def _snapshot(path: Path) -> RuntimeSnapshot:
    path.mkdir(parents=True, exist_ok=True)
    return RuntimeSnapshot(path, path.name.ljust(64, "0")[:64], 0)


class Builders:
    """Fake snapshot builders that record what they were asked for."""

    def __init__(self, tmp_path: Path, *, npm: bool = True, modules: bool = True,
                 node: bool = True) -> None:
        self.tmp = tmp_path
        self.calls: list[tuple[str, object]] = []
        self.npm = npm
        self.modules = modules
        self.node_found = node

    def python(self, interpreter: Path) -> PythonRuntime:
        self.calls.append(("python", interpreter))
        return PythonRuntime(_snapshot(self.tmp / "cache" / "python" / "a"),
                             _snapshot(self.tmp / "cache" / "python-deps" / "b"), ())

    def node(self, host: Path) -> RuntimeSnapshot:
        self.calls.append(("node", host))
        snapshot = _snapshot(self.tmp / "cache" / "node" / "c")
        (snapshot.path / "node.exe").write_bytes(b"")
        if self.npm:
            entry = snapshot.path / "node_modules" / "npm" / "bin"
            entry.mkdir(parents=True, exist_ok=True)
            (entry / "npm-cli.js").write_text("", encoding="utf-8")
        return snapshot

    def node_modules(self, repo: Path) -> RuntimeSnapshot | None:
        self.calls.append(("node_modules", repo))
        if not self.modules:
            return None
        snapshot = _snapshot(self.tmp / "cache" / "node-modules" / "d")
        for parts in (("pnpm", "bin", "pnpm.cjs"), ("yarn", "bin", "yarn.js")):
            target = snapshot.path.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        return snapshot

    def find_node(self, repo: Path | None) -> Path | None:
        return Path("C:\\Program Files\\nodejs\\node.exe") if self.node_found else None

    def builders(self) -> RuntimeBuilders:
        return RuntimeBuilders(python=self.python, node=self.node,
                               node_modules=self.node_modules, find_node=self.find_node)


# ---------------------------------------------------------------------- mapping


def test_allowlist_is_single_sourced() -> None:
    assert validation.ALLOWED_EXECUTABLES is ALLOWED_EXECUTABLES
    assert bounded_runner.ALLOWED_EXECUTABLES is ALLOWED_EXECUTABLES
    assert ALLOWED_EXECUTABLES == {
        "python", "python3", "pytest", "uv", "node", "npm", "npm.cmd",
        "pnpm", "pnpm.cmd", "yarn", "yarn.cmd", "cargo", "go", "dotnet",
    }
    # Every allowlisted name maps to a confined runtime or to a refusal, never both.
    assert set(CONFINED_TOOLCHAINS) | UNCONFINED_TOOLCHAINS == ALLOWED_EXECUTABLES
    assert not set(CONFINED_TOOLCHAINS) & UNCONFINED_TOOLCHAINS


@pytest.mark.parametrize("name", ["python", "python3"])
def test_python_runs_the_snapshot_of_the_requested_interpreter(tmp_path, name) -> None:
    fake = Builders(tmp_path)
    requested = tmp_path / "py" / "python.exe"
    resolved = resolve_check_runtime(name, interpreter=requested, builders=fake.builders())
    assert fake.calls == [("python", requested)]
    assert resolved.toolchain == "python"
    snapshot_python = tmp_path / "cache" / "python" / "a" / "python.exe"
    assert resolved.argv_prefix == (str(snapshot_python),)
    assert resolved.runtime.executable == snapshot_python
    assert resolved.runtime.env["PYTHONPATH"] == str(tmp_path / "cache" / "python-deps" / "b")
    assert [s.path for s in resolved.runtime.snapshots] == [
        tmp_path / "cache" / "python" / "a", tmp_path / "cache" / "python-deps" / "b"]


def test_pytest_is_the_snapshot_python_module(tmp_path) -> None:
    resolved = resolve_check_runtime("pytest", builders=Builders(tmp_path).builders())
    assert resolved.argv_prefix[1:] == ("-m", "pytest")
    assert resolved.argv_prefix[0].endswith("python.exe")


def test_python_defaults_to_this_interpreter(tmp_path) -> None:
    import sys

    fake = Builders(tmp_path)
    resolve_check_runtime("python", builders=fake.builders())
    assert fake.calls == [("python", Path(sys.executable))]


def test_node_runs_the_node_snapshot_with_the_project_modules(tmp_path) -> None:
    fake = Builders(tmp_path)
    repo = tmp_path / "repo"
    resolved = resolve_check_runtime("node", source_root=repo, builders=fake.builders())
    node_exe = tmp_path / "cache" / "node" / "c" / "node.exe"
    modules = tmp_path / "cache" / "node-modules" / "d"
    assert resolved.argv_prefix == (str(node_exe),)
    assert resolved.runtime.env == {"NODE_PATH": str(modules)}
    assert [s.path for s in resolved.runtime.snapshots] == [node_exe.parent, modules]
    assert resolved.runtime.path_entries == (node_exe.parent, modules / ".bin")
    assert ("node_modules", repo) in fake.calls


@pytest.mark.parametrize("name", ["npm", "npm.cmd"])
def test_npm_is_node_plus_the_snapshot_cli_never_the_cmd_shim(tmp_path, name) -> None:
    resolved = resolve_check_runtime(name, source_root=tmp_path / "repo",
                                     builders=Builders(tmp_path).builders())
    node = tmp_path / "cache" / "node" / "c"
    assert resolved.argv_prefix == (
        str(node / "node.exe"), str(node / "node_modules" / "npm" / "bin" / "npm-cli.js"))
    assert not any(part.lower().endswith(".cmd") for part in resolved.argv_prefix)


@pytest.mark.parametrize(("name", "entry"), [
    ("pnpm", ("pnpm", "bin", "pnpm.cjs")), ("pnpm.cmd", ("pnpm", "bin", "pnpm.cjs")),
    ("yarn", ("yarn", "bin", "yarn.js")), ("yarn.cmd", ("yarn", "bin", "yarn.js")),
])
def test_pnpm_and_yarn_run_their_entry_in_the_modules_snapshot(tmp_path, name, entry) -> None:
    resolved = resolve_check_runtime(name, source_root=tmp_path / "repo",
                                     builders=Builders(tmp_path).builders())
    modules = tmp_path / "cache" / "node-modules" / "d"
    assert resolved.argv_prefix[1] == str(modules.joinpath(*entry))


def test_missing_npm_entry_is_unavailable_never_the_host(tmp_path) -> None:
    with pytest.raises(AppError) as error:
        resolve_check_runtime("npm", source_root=tmp_path, builders=Builders(
            tmp_path, npm=False).builders())
    assert error.value.code == "CHECK_RUNTIME_UNAVAILABLE"


@pytest.mark.parametrize("name", ["pnpm", "yarn"])
def test_package_manager_without_modules_is_unavailable(tmp_path, name) -> None:
    with pytest.raises(AppError) as error:
        resolve_check_runtime(name, source_root=tmp_path, builders=Builders(
            tmp_path, modules=False).builders())
    assert error.value.code == "CHECK_RUNTIME_UNAVAILABLE"


def test_missing_host_node_is_unavailable(tmp_path) -> None:
    with pytest.raises(AppError) as error:
        resolve_check_runtime("node", source_root=tmp_path, builders=Builders(
            tmp_path, node=False).builders())
    assert error.value.code == "CHECK_RUNTIME_UNAVAILABLE"


@pytest.mark.parametrize("name", ["uv", "cargo", "go", "dotnet", "powershell", "make"])
def test_unmapped_toolchains_are_refused(tmp_path, name) -> None:
    fake = Builders(tmp_path)
    with pytest.raises(AppError) as error:
        resolve_check_runtime(name, builders=fake.builders())
    assert error.value.code == "CHECK_TOOLCHAIN_UNCONFINED"
    assert error.value.status_code == 409
    assert error.value.details["required_scope"] == CHECKS_UNCONFINED_SCOPE
    assert fake.calls == []  # refused before any snapshot is built
    assert is_unconfined_toolchain(name) is (name in UNCONFINED_TOOLCHAINS)


# ---------------------------------------------------------------------- opt-in

REPO_PATH = "C:\\work\\repo"


def _policy(tmp_path: Path, now: datetime):
    database = Database(tmp_path / "policy.sqlite3")
    database.initialize()
    repository = DelegationRepository(database)
    return DelegationPolicyEngine(repository, clock=lambda: now), repository, database


def _change(database: Database, **contract) -> ChangeView:
    now = datetime.now(UTC)
    view = ChangeView(id=uuid4(), title="t", intent="i", repository_path=REPO_PATH,
                      created_at=now, updated_at=now, review_state=ReviewState.NO_CHANGES,
                      contract=ChangeContract(**contract))
    ChangeRepository(database).create(StoredChange(
        id=view.id, title=view.title, intent=view.intent, repository_path=REPO_PATH,
        created_at=now, updated_at=now, last_refreshed_at=None, git_summary=None,
        verification=None, contract=view.contract))
    return view


def _delegate(repository, *, actor_id, change_id, now, scopes) -> None:
    repository.create(Delegation(
        id=uuid4(), grantor_id=uuid4(), grantee_id=actor_id, change_id=change_id,
        repository_path=REPO_PATH, scopes=scopes, issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1)))


def test_checks_unconfined_is_an_additive_policy_operation() -> None:
    assert PolicyOperation.CHECKS_UNCONFINED.value == "CHECKS_UNCONFINED"
    assert PolicyOperation.ASSURANCE_RUN.value == "ASSURANCE_RUN"


def test_unconfined_without_delegation_is_refused(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, _, database = _policy(tmp_path, now)
    change = _change(database, max_risk=RiskLevel.HIGH)
    decision = engine.evaluate(uuid4(), change, CHECKS_UNCONFINED_SCOPE, {})
    assert decision.allowed is False
    assert decision.reason_code.startswith("AUTHORITY_")


def test_unconfined_with_another_scope_is_refused(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _policy(tmp_path, now)
    change = _change(database, max_risk=RiskLevel.HIGH)
    actor = uuid4()
    _delegate(repository, actor_id=actor, change_id=change.id, now=now,
              scopes=["change.legacy_verify", "assurance.run"])
    assert engine.evaluate(actor, change, CHECKS_UNCONFINED_SCOPE, {}).allowed is False


def test_unconfined_is_high_risk_and_refused_under_the_default_ceiling(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _policy(tmp_path, now)
    change = _change(database)  # default max_risk MEDIUM
    actor = uuid4()
    _delegate(repository, actor_id=actor, change_id=change.id, now=now,
              scopes=[CHECKS_UNCONFINED_SCOPE])
    decision = engine.evaluate(actor, change, CHECKS_UNCONFINED_SCOPE, {})
    assert decision.allowed is False
    assert decision.reason_code == "RISK_TOO_HIGH"
    assert decision.risk_level == RiskLevel.HIGH


def test_unconfined_delegated_on_a_high_risk_change_is_allowed(tmp_path) -> None:
    now = datetime.now(UTC)
    engine, repository, database = _policy(tmp_path, now)
    change = _change(database, max_risk=RiskLevel.HIGH)
    actor = uuid4()
    _delegate(repository, actor_id=actor, change_id=change.id, now=now,
              scopes=[CHECKS_UNCONFINED_SCOPE])
    decision = engine.evaluate(actor, change, CHECKS_UNCONFINED_SCOPE, {})
    assert decision.allowed is True
    assert decision.risk_level == RiskLevel.HIGH
    # Bound to its Change: the same actor has no unconfined authority elsewhere.
    other = _change(database, max_risk=RiskLevel.HIGH)
    assert engine.evaluate(actor, other, CHECKS_UNCONFINED_SCOPE, {}).allowed is False


def test_module_constants() -> None:
    assert toolchains.BOUNDARY_APPCONTAINER == "APPCONTAINER"
    assert toolchains.BOUNDARY_UNCONFINED == "UNCONFINED"
