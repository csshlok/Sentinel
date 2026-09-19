"""Top-level Agent Launcher (``AgentLauncherPort``).

Scope, deliberately narrow:

* ``launch`` starts one process, observes only that direct child, and returns an
  aggregate result. No event journal, process supervisor, filesystem tracker or
  tool registry exists behind it, so descendant control, attribution and cleanup
  are never claimed.
* ``attach`` records caller-declared metadata. Nothing is observed.
* ``stop`` terminates the direct child of a run started by this instance.

Caller authority is enforced upstream (``PolicyPort``); the port carries no
actor, so this class cannot and does not authorize a caller. Run records live in
memory only; persisting them is a shared-core integration responsibility.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    AgentAttachRequest, AgentLaunchRequest, AgentRun, AgentRunStatus, utc_now,
)
from backend.app.core.errors import AppError
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.resolve import resolve_argv, safe_path_entries

MAX_OUTPUT_BYTES = 1_048_576
MAX_TIMEOUT_SECONDS = 86_400
STOP_WAIT_SECONDS = 10.0
REDACTION = "[REDACTED]"

DESCENDANT_LIMITATION = (
    "Only the top-level invocation was launched and observed; descendant "
    "processes are not controlled, attributed or cleaned up."
)
EXIT_LIMITATION = (
    "The status describes the direct child only and does not describe files, "
    "network or descendant activity."
)

_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SENSITIVE = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE|SESSION|COOKIE)",
    re.IGNORECASE,
)
_DENIED_PREFIXES = ("GIT_", "LD_", "DYLD_", "CHANGE_ASSURANCE_", "PYTHON", "NODE_")
_DENIED_KEYS = frozenset({"PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "WINDIR", "HOME",
                          "USERPROFILE", "IFS", "BASH_ENV", "ENV"})


@dataclass(frozen=True)
class AgentAdapter:
    """Adapter metadata: which executables it may start and which of the
    agent's own credential variables may be forwarded when explicitly requested."""

    name: str
    executables: frozenset[str]
    credential_keys: frozenset[str] = frozenset()


GENERIC_EXECUTABLES = frozenset({
    "python", "python3", "node", "npm", "npx", "pytest", "uv", "cargo", "go", "dotnet",
})
CODEX_ADAPTER = AgentAdapter("codex", frozenset({"codex"}),
                             frozenset({"OPENAI_API_KEY", "CODEX_API_KEY"}))
CLAUDE_ADAPTER = AgentAdapter("claude", frozenset({"claude"}),
                              frozenset({"ANTHROPIC_API_KEY"}))


def _normalize(executable: str) -> str:
    lowered = executable.lower()
    return lowered.removesuffix(".exe")


@dataclass
class _State:
    record: AgentRun
    cancel: threading.Event
    done: threading.Event
    attached: bool = False


class AgentLauncher:
    """Concrete ``AgentLauncherPort`` for the generic, Codex and Claude adapters."""

    def __init__(
        self,
        generic_executables: frozenset[str] = GENERIC_EXECUTABLES,
        adapters: dict[str, AgentAdapter] | None = None,
    ) -> None:
        table = {
            "generic": AgentAdapter("generic", frozenset(generic_executables)),
            "codex": CODEX_ADAPTER,
            "claude": CLAUDE_ADAPTER,
        }
        table.update(adapters or {})
        self._adapters = table
        self._runs: dict[UUID, _State] = {}
        self._lock = threading.Lock()

    # -- port ---------------------------------------------------------------

    def launch(
        self, change_id: UUID, repository_path: str, request: AgentLaunchRequest,
        output_limit_bytes: int,
    ) -> AgentRun:
        # Revalidate in case a model was built with model_construct.
        request = AgentLaunchRequest.model_validate(request.model_dump())
        adapter = self._adapter(request.adapter)
        if _normalize(request.executable) not in adapter.executables:
            raise AppError("AGENT_EXECUTABLE_NOT_ALLOWED",
                           "The executable is not permitted for this adapter.")
        if any("\0" in item for item in (request.executable, *request.args)):
            raise AppError("INVALID_EXECUTION_ARGUMENT", "Command arguments contain a NUL byte.")
        if (type(output_limit_bytes) is not int
                or not 0 <= output_limit_bytes <= MAX_OUTPUT_BYTES):
            raise AppError("INVALID_OUTPUT_LIMIT", "Output limit must be between zero and one MiB.")
        root = self._root(repository_path)
        env, secrets = self._environment(request, adapter, root)

        run_id = uuid4()
        started_at = utc_now()
        running = AgentRun(
            id=run_id, change_id=change_id, adapter=adapter.name,
            status=AgentRunStatus.RUNNING, started_at=started_at,
            limitations=[DESCENDANT_LIMITATION],
        )
        state = _State(running, threading.Event(), threading.Event())
        with self._lock:
            self._runs[run_id] = state

        def on_start(pid: int) -> None:
            with self._lock:
                state.record = state.record.model_copy(update={"top_level_pid": pid})

        clock = time.monotonic()
        limitations = [DESCENDANT_LIMITATION, EXIT_LIMITATION]
        status = AgentRunStatus.ERROR
        exit_code: int | None = None
        stdout = stderr = ""
        truncated = False
        pid: int | None = None
        try:
            argv = resolve_argv(request.executable, env, root)
            result = capture(
                [*argv, *request.args], cwd=root, env=env,
                timeout=request.timeout_seconds, limit=output_limit_bytes,
                max_timeout=MAX_TIMEOUT_SECONDS, cancel=state.cancel, on_start=on_start,
            )
        except AppError as exc:
            limitations.append(f"The agent did not start: {exc.message}")
        except (OSError, ValueError):
            limitations.append("The agent did not start: the operating system refused it.")
        else:
            pid = result.pid
            stdout = self._text(result.stdout, secrets)
            stderr = self._text(result.stderr, secrets)
            truncated = (result.truncated or result.incomplete
                         or self._lossy(result.stdout) or self._lossy(result.stderr))
            if result.cancelled:
                status = AgentRunStatus.CANCELLED
                limitations.append(
                    "Cancellation terminated the direct child only; descendants may still be running."
                )
            elif result.timed_out:
                status = AgentRunStatus.TIMED_OUT
                limitations.append(
                    "Timeout terminated the direct child only; descendants may still be running."
                )
            else:
                exit_code = result.returncode
                status = AgentRunStatus.PASSED if exit_code == 0 else AgentRunStatus.FAILED
        final = AgentRun(
            id=run_id, change_id=change_id, adapter=adapter.name, status=status,
            top_level_pid=pid, exit_code=exit_code, started_at=started_at,
            completed_at=utc_now(), duration_ms=int((time.monotonic() - clock) * 1000),
            stdout=stdout, stderr=stderr, output_truncated=truncated,
            limitations=limitations,
        )
        with self._lock:
            state.record = final
        state.done.set()
        return final

    def attach(self, change_id: UUID, request: AgentAttachRequest) -> AgentRun:
        adapter = self._adapter(request.adapter)
        run = AgentRun(
            id=uuid4(), change_id=change_id, adapter=adapter.name,
            status=AgentRunStatus.ATTACHED, external_run_id=request.external_run_id,
            started_at=request.declared_started_at or utc_now(),
            limitations=[
                "Attach records caller-declared metadata only; no process was observed.",
                "The declared invocation cannot be stopped or attributed by this runtime.",
                DESCENDANT_LIMITATION,
            ],
        )
        state = _State(run, threading.Event(), threading.Event(), attached=True)
        state.done.set()
        with self._lock:
            self._runs[run.id] = state
        return run

    def stop(self, run_id: UUID) -> AgentRun:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "The agent run does not exist.",
                           status_code=404)
        if state.attached:
            return self._with_limitation(
                state, "Attached invocations cannot be stopped: they are metadata only."
            )
        if state.done.is_set():
            return state.record
        state.cancel.set()
        if state.done.wait(STOP_WAIT_SECONDS):
            return state.record
        return self._with_limitation(
            state, "Cancellation was requested but has not completed yet."
        )

    # -- helpers ------------------------------------------------------------

    def get(self, run_id: UUID) -> AgentRun:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "The agent run does not exist.",
                           status_code=404)
        return state.record

    def _with_limitation(self, state: _State, text: str) -> AgentRun:
        record = state.record
        if text in record.limitations:
            return record
        return record.model_copy(update={"limitations": [*record.limitations, text]})

    def _adapter(self, name: str) -> AgentAdapter:
        adapter = self._adapters.get(name)
        if adapter is None:
            raise AppError("AGENT_ADAPTER_UNSUPPORTED", "The agent adapter is not supported.")
        return adapter

    @staticmethod
    def _root(repository_path: str) -> Path:
        try:
            if "\0" in repository_path:
                raise ValueError
            root = Path(repository_path).expanduser().resolve(strict=True)
            if not root.is_dir():
                raise ValueError
        except (OSError, ValueError, RuntimeError) as exc:
            raise AppError("INVALID_EXECUTION_DIRECTORY",
                           "The execution directory is invalid.") from exc
        return root

    @staticmethod
    def _environment(
        request: AgentLaunchRequest, adapter: AgentAdapter, root: Path
    ) -> tuple[dict[str, str], list[str]]:
        env = minimal_environment()
        env["PATH"] = os.pathsep.join(str(p) for p in safe_path_entries(env, root))
        forwarded_secrets: list[str] = []
        for key in request.environment_keys:
            upper = key.upper()
            if (not _KEY_PATTERN.fullmatch(key) or upper in _DENIED_KEYS
                    or upper.startswith(_DENIED_PREFIXES)):
                raise AppError("AGENT_ENVIRONMENT_KEY_DENIED",
                               "An environment key is not permitted for a launched agent.")
            if _SENSITIVE.search(key) and upper not in adapter.credential_keys:
                raise AppError("AGENT_ENVIRONMENT_KEY_DENIED",
                               "An environment key is not permitted for a launched agent.")
            value = os.environ.get(key)
            if value is None:
                continue
            env[upper] = value
            if _SENSITIVE.search(key):
                forwarded_secrets.append(value)
        # Redact every sensitive parent variable too: a child must not be able to
        # surface a secret it was never given but a sibling process exposes.
        parent = [v for k, v in os.environ.items() if _SENSITIVE.search(k)]
        secrets = sorted({v for v in [*forwarded_secrets, *parent] if len(v) >= 8},
                         key=len, reverse=True)
        return env, secrets

    @staticmethod
    def _lossy(data: bytes) -> bool:
        return data.decode("utf-8", errors="ignore").encode("utf-8") != data

    @staticmethod
    def _text(data: bytes, secrets: list[str]) -> str:
        text = data.decode("utf-8", errors="ignore")
        for secret in secrets:
            text = text.replace(secret, REDACTION)
        return text
