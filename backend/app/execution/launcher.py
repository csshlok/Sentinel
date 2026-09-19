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

import base64
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from backend.app.contracts.models import (
    AgentAttachRequest, AgentLaunchRequest, AgentRun, AgentRunStatus, ToolManifest, utc_now,
)
from backend.app.contracts.ports import ToolRegistryPort
from backend.app.core.errors import AppError, policy_denied
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.resolve import find_executable, resolve_argv, safe_path_entries

MAX_OUTPUT_BYTES = 1_048_576
MAX_TIMEOUT_SECONDS = 86_400
MAX_RETAINED_RUNS = 512
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
        *,
        tool_registry: ToolRegistryPort | None = None,
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
        # Optional observer, called with every state change of a run (started, pid
        # known, finished) so a caller can persist in-flight runs and stop them from
        # another request. Failures in the observer never affect the run.
        self.on_update: Callable[[AgentRun], None] | None = None
        # Optional Tool Registry (Part B, bounded scope: governs only the
        # top-level executable this class itself resolves -- see B.6). When
        # unset, launch/attach behave exactly as before this feature existed.
        self._tool_registry = tool_registry

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
        # Resolve the executable path exactly once and reuse it for both the
        # trust-check hash and the actual spawn below. Re-resolving the same
        # name a second time (the previous shape: once here, once inside the
        # try block further down) leaves a window where a file swapped in
        # between the two resolutions is hashed as one thing and executed as
        # another -- resolving once cannot widen that window and removes the
        # redundant second lookup that could observe a different file.
        try:
            argv = resolve_argv(request.executable, env, root)
            resolve_error: AppError | None = None
        except AppError as exc:
            argv = None
            resolve_error = exc
        tool_manifest = self._check_tool_trust(change_id, argv)

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
        self._notify(running)

        def on_start(pid: int) -> None:
            with self._lock:
                state.record = state.record.model_copy(update={"top_level_pid": pid})
                started = state.record
            self._notify(started)

        clock = time.monotonic()
        limitations = [DESCENDANT_LIMITATION, EXIT_LIMITATION]
        status = AgentRunStatus.ERROR
        exit_code: int | None = None
        stdout = stderr = ""
        truncated = False
        pid: int | None = None
        try:
            if resolve_error is not None:
                raise resolve_error
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
            self._evict()
        self._notify(final)
        if self._tool_registry is not None and tool_manifest is not None:
            self._record_tool_observation(tool_manifest.id, change_id, run_id, "launch")
        state.done.set()
        return final

    def attach(self, change_id: UUID, request: AgentAttachRequest) -> AgentRun:
        # No Tool Registry check here: attach records caller-declared
        # metadata only (adapter name, external_run_id) -- there is no
        # executable path to resolve an artifact_digest from, so no
        # ToolManifest can be honestly identified. Inventing one from an
        # adapter name alone would be exactly the kind of fabricated
        # attribution this project's "no safety theater" invariant forbids.
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
            self._evict()
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

    def adapters(self, repository_path: str | None = None) -> list[dict[str, object]]:
        """Adapter metadata with explicit executable discovery.

        Reports which permitted executables are installed outside the repository
        (a bare name is resolved exactly as ``launch`` would resolve it). Nothing
        is executed and no path is disclosed: availability is a boolean per name.
        """

        root = self._root(repository_path) if repository_path else Path.cwd().resolve()
        env = minimal_environment()
        env["PATH"] = os.pathsep.join(str(p) for p in safe_path_entries(env, root))
        listing: list[dict[str, object]] = []
        for name in sorted(self._adapters):
            adapter = self._adapters[name]
            listing.append({
                "adapter": name,
                "executables": {exe: find_executable(exe, env, root) is not None
                                for exe in sorted(adapter.executables)},
                "credential_keys": sorted(adapter.credential_keys),
                "descendant_control_available": False,
            })
        return listing

    # -- Tool Registry integration (Part B.6) --------------------------------

    def _check_tool_trust(
        self, change_id: UUID, argv: list[str] | None,
    ) -> ToolManifest | None:
        """Resolve-or-register the top-level executable and refuse a DENIED
        tool before anything starts. Governs only this one launch surface
        (B.6's "deliberately the only enforcement point"): it says nothing
        about what a running agent does afterward.

        Takes the executable path `launch` already resolved, rather than
        resolving it again here, so the bytes hashed for trust are the same
        bytes that get executed (see the call site's comment).

        `argv` is `None` when `launch`'s own resolution failed (executable
        not found): deliberately swallowed, not raised, here. `launch`
        re-raises the original error at execution time, so behavior for an
        unresolvable executable is unchanged.
        """

        if self._tool_registry is None or argv is None:
            return None
        manifest = self._tool_registry.resolve_or_register(argv[0], source="launcher_executable")
        if manifest.trust_state == "DENIED":
            raise policy_denied(
                "TOOL_TRUST_DENIED", "This tool is explicitly denied and may not be launched."
            )
        try:
            # Capability-drift detection (B.5): only meaningful once a prior
            # APPROVED decision exists; a no-op otherwise. Trouble here must
            # never block a launch that was otherwise permitted.
            self._tool_registry.check_drift(manifest.id, change_id=change_id)  # type: ignore[call-arg]
        except Exception:
            pass
        return manifest

    def _record_tool_observation(
        self, tool_id: UUID, change_id: UUID, run_id: UUID, context: str,
    ) -> None:
        try:
            # Capabilities actually used (via resolved CredentialGrant
            # scopes) are deliberately not cross-referenced here: doing so
            # honestly needs a read across this Change's journal, which is a
            # composition-layer concern this pure launcher class does not
            # have access to. Recorded as an empty, honest set rather than a
            # fabricated one; a future composition-layer pass can widen it.
            self._tool_registry.record_observation(tool_id, change_id, run_id, [], context)
        except Exception:  # persistence trouble must not change what the agent did
            pass

    # -- helpers ------------------------------------------------------------

    def get(self, run_id: UUID) -> AgentRun:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "The agent run does not exist.",
                           status_code=404)
        return state.record

    def _notify(self, run: AgentRun) -> None:
        observer = self.on_update
        if observer is None:
            return
        try:
            observer(run)
        except Exception:  # persistence trouble must not change what the agent does
            pass

    def _evict(self) -> None:
        """Bound memory: drop the oldest finished records (caller holds the lock)."""

        excess = len(self._runs) - MAX_RETAINED_RUNS
        for run_id in list(self._runs):
            if excess <= 0:
                break
            if self._runs[run_id].done.is_set():
                del self._runs[run_id]
                excess -= 1

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
        """Best-effort redaction of captured output.

        Matches each secret verbatim and in its common reversible encodings
        (base64, hex), since those are the cheapest ways a script would
        transform a value before printing it. This is a mitigation, not a
        guarantee: arbitrary transformation (splitting across lines, a
        custom encoding, compression) by a compromised agent can still
        defeat it. Callers must not treat captured output as safe to
        display or store merely because it passed through here.
        """

        text = data.decode("utf-8", errors="ignore")
        for secret in secrets:
            text = text.replace(secret, REDACTION)
            raw = secret.encode("utf-8")
            for variant in (
                base64.b64encode(raw).decode("ascii"),
                base64.urlsafe_b64encode(raw).decode("ascii"),
                raw.hex(),
            ):
                text = text.replace(variant, REDACTION)
        return text
