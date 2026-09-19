"""Environment Passport capture and comparison (``EnvironmentPort``).

A passport is bounded, deterministic and redacted. It records what could be
observed at capture time: operating system, interpreter, tool versions, a small
allowlist of configuration variables and repository configuration. Raw secrets
never enter it: sensitive facts carry only a keyed fingerprint. Comparison
reports differences between two snapshots and never claims what caused them.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import platform
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    EnvironmentDrift, EnvironmentFact, EnvironmentPassport, EvidenceStatus, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.resolve import resolve_argv, safe_path_entries

DEFAULT_FINGERPRINT_KEY = b"change-assurance/environment-passport/v1"
MAX_VALUE = 512
TOOL_TIMEOUT_SECONDS = 10
TOOL_OUTPUT_LIMIT = 4096
REDACTION = "[REDACTED]"

DEFAULT_TOOLS: dict[str, list[str]] = {
    "node": ["--version"], "npm": ["--version"], "git": ["--version"],
    "pnpm": ["--version"], "yarn": ["--version"], "uv": ["--version"],
    "cargo": ["--version"], "go": ["version"], "dotnet": ["--version"],
    "gcc": ["--version"], "clang": ["--version"],
}
DEFAULT_CONFIG_KEYS = ("CI", "NODE_ENV", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "TZ", "LANG")
MANIFEST_NAMES = (
    "package.json", "package-lock.json", "pyproject.toml", "requirements.txt",
    "poetry.lock", "yarn.lock", "pnpm-lock.yaml", "Cargo.toml", "go.mod",
)
_SENSITIVE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE|SESSION|COOKIE)",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\x00-\x08\x0b-\x1f\x7f]")


@dataclass
class CollectionContext:
    change_id: UUID
    repository_path: Path
    tracker: EnvironmentTracker
    limitations: list[str] = field(default_factory=list)


Collector = Callable[[CollectionContext], list[EnvironmentFact]]
CommandRunner = Callable[[list[str], Path], tuple[int | None, str]]


def _default_runner(argv: list[str], cwd: Path) -> tuple[int | None, str]:
    env = minimal_environment()
    env["PATH"] = os.pathsep.join(str(p) for p in safe_path_entries(env, cwd))
    result = capture(argv, cwd=cwd, env=env, timeout=TOOL_TIMEOUT_SECONDS,
                     limit=TOOL_OUTPUT_LIMIT)
    if result.timed_out or result.incomplete:
        return None, ""
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


class EnvironmentTracker:
    """Concrete ``EnvironmentPort``."""

    def __init__(
        self,
        *,
        fingerprint_key: bytes = DEFAULT_FINGERPRINT_KEY,
        tools: Mapping[str, list[str]] | None = None,
        config_keys: tuple[str, ...] = DEFAULT_CONFIG_KEYS,
        sensitive_keys: tuple[str, ...] = (),
        runner: CommandRunner | None = None,
        environ: Mapping[str, str] | None = None,
        collectors: list[Collector] | None = None,
    ) -> None:
        if not isinstance(fingerprint_key, bytes) or len(fingerprint_key) < 16:
            raise ValueError("The fingerprint key must be at least 16 bytes.")
        self._key = fingerprint_key
        self._tools = dict(DEFAULT_TOOLS if tools is None else tools)
        self._config_keys = config_keys
        self._sensitive_keys = {k.upper() for k in sensitive_keys}
        self._runner = runner or _default_runner
        self._environ = os.environ if environ is None else environ
        self._collectors = collectors if collectors is not None else [
            self._collect_os, self._collect_python, self._collect_tools,
            self._collect_config, self._collect_repository,
        ]

    # -- port ---------------------------------------------------------------

    def capture(self, change_id: UUID, repository_path: str) -> EnvironmentPassport:
        root = self._root(repository_path)
        context = CollectionContext(change_id, root, self)
        facts: dict[str, EnvironmentFact] = {}
        for collector in self._collectors:
            name = getattr(collector, "__name__", "collector").removeprefix("_collect_")
            try:
                produced = collector(context)
            except Exception:  # a failed collector must never abort capture
                context.limitations.append(f"Collector '{name}' failed; its facts are missing.")
                continue
            for fact in produced:
                if fact.key in facts:
                    context.limitations.append(f"Duplicate fact '{fact.key}' was ignored.")
                    continue
                facts[fact.key] = self._scrub(fact)
        ordered = [facts[key] for key in sorted(facts)]
        limitations = sorted(set(context.limitations))
        complete = not limitations and all(f.status is EvidenceStatus.CURRENT for f in ordered)
        return EnvironmentPassport(
            id=uuid4(), change_id=change_id, facts=ordered, captured_at=utc_now(),
            status=EvidenceStatus.CURRENT if complete else EvidenceStatus.PARTIAL,
            limitations=limitations[:64],
        )

    def compare(
        self, baseline: EnvironmentPassport, current: EnvironmentPassport
    ) -> EnvironmentDrift:
        before = {f.key: f for f in baseline.facts}
        after = {f.key: f for f in current.facts}
        added, removed, changed, unknown = [], [], [], []
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key), after.get(key)
            if old is None:
                (added if new.status is EvidenceStatus.CURRENT else unknown).append(new)
            elif new is None:
                (removed if old.status is EvidenceStatus.CURRENT else unknown).append(old)
            elif old.status is not EvidenceStatus.CURRENT or new.status is not EvidenceStatus.CURRENT:
                unknown.append(new)
            elif (old.value, old.fingerprint) != (new.value, new.fingerprint):
                changed.append(new)
        return EnvironmentDrift(
            baseline_id=baseline.id, current_id=current.id, added=added,
            removed=removed, changed=changed, unknown=unknown,
        )

    # -- fact construction --------------------------------------------------

    def fingerprint(self, key: str, value: str) -> str:
        return hmac.new(self._key, f"{key}\0{value}".encode(), hashlib.sha256).hexdigest()

    def plain(self, key: str, value: str) -> EnvironmentFact:
        return EnvironmentFact(key=key, value=self._clean(value))

    def secret(self, key: str, value: str) -> EnvironmentFact:
        return EnvironmentFact(key=key, fingerprint=self.fingerprint(key, value), sensitive=True)

    def _clean(self, value: str) -> str:
        cleaned = " ".join(_CONTROL.sub("", value).split())
        return cleaned[:MAX_VALUE]

    def _secrets(self) -> list[str]:
        values = {v for k, v in self._environ.items()
                  if (_SENSITIVE.search(k) or k.upper() in self._sensitive_keys) and len(v) >= 6}
        return sorted(values, key=len, reverse=True)

    def _scrub(self, fact: EnvironmentFact) -> EnvironmentFact:
        """Last line of defence: no known secret value survives in a plain fact."""

        if fact.value is None:
            return fact
        value = fact.value
        for secret in self._secrets():
            value = value.replace(secret, REDACTION)
        return fact if value == fact.value else fact.model_copy(update={"value": value})

    # -- collectors ---------------------------------------------------------

    def _collect_os(self, context: CollectionContext) -> list[EnvironmentFact]:
        facts = [
            self.plain("os.system", platform.system()),
            self.plain("os.release", platform.release()),
            self.plain("os.version", platform.version()),
            self.plain("os.machine", platform.machine()),
        ]
        return [f for f in facts if f.value]

    def _collect_python(self, context: CollectionContext) -> list[EnvironmentFact]:
        return [
            self.plain("python.version", platform.python_version()),
            self.plain("python.implementation", platform.python_implementation()),
            self.secret("python.executable", str(Path(sys.executable).resolve())),
        ]

    def _collect_tools(self, context: CollectionContext) -> list[EnvironmentFact]:
        facts: list[EnvironmentFact] = []
        env = {"PATH": os.pathsep.join(
            str(p) for p in safe_path_entries(minimal_environment(self._environ), context.repository_path))}
        for name in sorted(self._tools):
            key = f"tool.{name}.version"
            try:
                argv = resolve_argv(name, env, context.repository_path)
            except AppError as exc:
                if exc.code == "EXECUTABLE_NOT_FOUND":
                    continue  # not installed: absence is visible as removed/added drift
                facts.append(EnvironmentFact(key=key, status=EvidenceStatus.UNSUPPORTED))
                context.limitations.append(
                    f"Tool '{name}' is installed behind a batch wrapper that is never executed.")
                continue
            try:
                code, output = self._runner([*argv, *self._tools[name]], context.repository_path)
            except OSError:
                code, output = None, ""
            line = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
            if code != 0 or not self._clean(line):
                facts.append(EnvironmentFact(key=key, status=EvidenceStatus.PARTIAL))
                context.limitations.append(f"Tool '{name}' did not report a usable version.")
                continue
            facts.append(self.plain(key, line))
            facts.append(self.secret(f"tool.{name}.path", argv[0]))
        return facts

    def _collect_config(self, context: CollectionContext) -> list[EnvironmentFact]:
        facts: list[EnvironmentFact] = []
        for key in sorted(set(self._config_keys) | self._sensitive_keys):
            value = self._environ.get(key)
            if value is None:
                continue
            fact_key = f"env.{key.upper()}"
            if _SENSITIVE.search(key) or key.upper() in self._sensitive_keys:
                facts.append(self.secret(fact_key, value))
            else:
                facts.append(self.plain(fact_key, value) if self._clean(value)
                             else self.plain(fact_key, "(empty)"))
        path = self._environ.get("PATH")
        if path is not None:
            facts.append(self.secret("env.PATH", path))
        return facts

    def _collect_repository(self, context: CollectionContext) -> list[EnvironmentFact]:
        root = context.repository_path
        facts = [self.plain("repo.manifests", ",".join(
            name for name in MANIFEST_NAMES if (root / name).is_file()) or "(none)")]
        try:
            argv = resolve_argv("git", {"PATH": os.pathsep.join(
                str(p) for p in safe_path_entries(minimal_environment(self._environ), root))}, root)
        except AppError:
            context.limitations.append("Git is unavailable; repository configuration is missing.")
            return facts
        for key, fact_key in (("core.autocrlf", "git.core.autocrlf"),
                              ("remote.origin.url", "git.remote.origin")):
            code, output = self._runner([*argv, "-C", str(root), "config", "--get", key], root)
            value = output.strip()
            if code != 0 or not value:
                continue
            if key == "remote.origin.url":
                facts.append(self.secret(fact_key, value))
                host = self._host(value)
                if host:
                    facts.append(self.plain("git.remote.origin.host", host))
            else:
                facts.append(self.plain(fact_key, value))
        return facts

    @staticmethod
    def _host(url: str) -> str | None:
        if "://" in url:
            return urlsplit(url).hostname
        match = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):.+", url)  # scp-like syntax
        return match.group(1) if match else None

    @staticmethod
    def _root(repository_path: str) -> Path:
        try:
            if "\0" in repository_path:
                raise ValueError
            root = Path(repository_path).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise ValueError
        except (OSError, ValueError, RuntimeError) as exc:
            raise AppError("INVALID_REPOSITORY_PATH",
                           "The repository path does not exist or is not a directory.") from exc
        return root
