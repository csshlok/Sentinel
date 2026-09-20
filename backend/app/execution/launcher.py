"""Agent Launcher with Windows process-tree supervision.

Scope, deliberately narrow:

* On Windows, ``launch`` uses a kill-on-close Job Object, records descendants,
  and starts the top-level process with maximum privileges removed from a
  restricted token (the caller integrity level is retained for repository writes).
  Reduced privilege is not a sandbox or isolation boundary.
* ``attach`` records caller-declared metadata. Nothing is observed.
* ``stop`` terminates the owned Job Object tree when supervision is available.

Caller authority is enforced upstream (``PolicyPort``); the port carries no
actor, so this class cannot and does not authorize a caller. Run records live in
memory only; persisting them is a shared-core integration responsibility.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
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
from backend.app.execution import container_supervisor
from backend.app.execution.process_supervisor import (
    IS_WINDOWS, SupervisedProcess, is_process_running, list_pids, spawn_restricted_supervised,
)
from backend.app.execution.resolve import find_executable, resolve_argv, safe_path_entries
from backend.app.execution.signal_control import resume_process, suspend_process

MAX_OUTPUT_BYTES = 1_048_576
MAX_TIMEOUT_SECONDS = 86_400
MAX_RETAINED_RUNS = 512
STOP_WAIT_SECONDS = 10.0
REDACTION = "[REDACTED]"
# Part C: how often an in-flight run's partial stdout/stderr is persisted via
# on_update while it is still running. A chatty process must not flood the
# journal/store with an update per byte -- this is a simple monotonic-clock
# gate, not a new scheduler.
CHUNK_NOTIFY_INTERVAL_SECONDS = 0.5

DESCENDANT_LIMITATION = (
    "Only the top-level invocation was launched and observed; descendant "
    "processes are not controlled, attributed or cleaned up."
)
SUPERVISED_LIMITATION = (
    "The launched process tree was supervised by a Windows Job Object; pause/resume "
    "acts on every process the runtime has observed in that tree, not the top-level "
    "PID alone. A descendant that starts and exits between two supervision polls, or "
    "one spawned by an already-suspended process, is not covered."
)
RESTRICTED_AUTHORITY = (
    "Reduced privilege via a restricted Windows token with maximum privileges "
    "disabled; the caller integrity level is retained so the selected repository "
    "remains writable. This is not a sandbox and provides no filesystem or network isolation."
)
RESTRICTED_UNAVAILABLE = (
    "Restricted-token authority reduction is unavailable on this platform; the process "
    "was launched with the existing account authority."
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
    paused: threading.Event
    attached: bool = False
    process: object | None = None


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
        if request.isolation == "container":
            # A wholly separate path from here down: container isolation
            # trades Windows process-tree attribution and restricted-token
            # privilege reduction for real filesystem/network isolation (see
            # execution/container_supervisor.py's own docstring). It does
            # not share the restricted-token machinery below at all, so it
            # cannot regress it.
            return self._launch_containerized(change_id, root, request, adapter, output_limit_bytes)
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
        initial_limitations = (
            [] if IS_WINDOWS else [DESCENDANT_LIMITATION, RESTRICTED_UNAVAILABLE]
        )
        running = AgentRun(
            id=run_id, change_id=change_id, adapter=adapter.name,
            status=AgentRunStatus.RUNNING, started_at=started_at,
            limitations=initial_limitations,
        )
        state = _State(running, threading.Event(), threading.Event(), threading.Event())
        with self._lock:
            self._runs[run_id] = state
        self._notify(running)

        spawned: list[SupervisedProcess | None] = [None]

        def on_start(pid: int) -> None:
            process = spawned[0]
            supervised = bool(process and process.session is not None)
            restricted = bool(process and process.restricted_token_applied)
            with self._lock:
                state.process = process
                state.record = state.record.model_copy(update={
                    "top_level_pid": pid,
                    "descendant_control_available": supervised,
                    "restricted_token_applied": restricted,
                    "authority_reduction": RESTRICTED_AUTHORITY if restricted else None,
                    "limitations": (
                        [SUPERVISED_LIMITATION, RESTRICTED_AUTHORITY]
                        if supervised else [DESCENDANT_LIMITATION, RESTRICTED_AUTHORITY]
                        if restricted else state.record.limitations
                    ),
                })
                started = state.record
            self._notify(started)

        def process_factory(arguments, process_cwd, process_env):
            process = spawn_restricted_supervised(
                arguments, cwd=process_cwd, env=process_env,
                redact=lambda value: self._text(value.encode("utf-8"), secrets),
            )
            spawned[0] = process
            return process

        def on_poll(process: object) -> None:
            if not isinstance(process, SupervisedProcess) or process.session is None:
                return
            descendants = process.session.observe()
            with self._lock:
                if descendants == state.record.descendant_processes:
                    return
                state.record = state.record.model_copy(
                    update={"descendant_processes": descendants}
                )
                updated = state.record
            self._notify(updated)

        clock = time.monotonic()
        limitations = [EXIT_LIMITATION]
        if not IS_WINDOWS:
            limitations.extend([DESCENDANT_LIMITATION, RESTRICTED_UNAVAILABLE])
        status = AgentRunStatus.ERROR
        exit_code: int | None = None
        stdout = stderr = ""
        truncated = False
        pid: int | None = None
        last_notify = [0.0]
        raw_stdout = bytearray()
        raw_stderr = bytearray()

        def on_chunk(stdout_delta: bytes, stderr_delta: bytes) -> None:
            # Part C: surface partial output while the run is still in
            # flight, through the same redaction pass the final result
            # already goes through -- this is not a new redaction path.
            #
            # Redaction runs on the *full accumulated raw buffer* every call,
            # not just the new delta: a secret can be split across two reads
            # by OS/pipe timing (e.g. a slow or flushed write mid-string),
            # and redacting each delta in isolation would never recognize
            # either half as the secret, leaking it into stored evidence.
            # Raw accumulators are capped at output_limit_bytes so this
            # cannot grow unboundedly even for a very chatty process.
            if not stdout_delta and not stderr_delta:
                return
            with self._lock:
                if stdout_delta and len(raw_stdout) < output_limit_bytes:
                    raw_stdout.extend(stdout_delta[: output_limit_bytes - len(raw_stdout)])
                if stderr_delta and len(raw_stderr) < output_limit_bytes:
                    raw_stderr.extend(stderr_delta[: output_limit_bytes - len(raw_stderr)])
                current = state.record
                new_stdout = self._text(bytes(raw_stdout), secrets)
                new_stderr = self._text(bytes(raw_stderr), secrets)
                if new_stdout == current.stdout and new_stderr == current.stderr:
                    return
                state.record = current.model_copy(
                    update={"stdout": new_stdout, "stderr": new_stderr})
                updated = state.record
            now = time.monotonic()
            if now - last_notify[0] >= CHUNK_NOTIFY_INTERVAL_SECONDS:
                last_notify[0] = now
                self._notify(updated)

        try:
            if resolve_error is not None:
                raise resolve_error
            result = capture(
                [*argv, *request.args], cwd=root, env=env,
                timeout=request.timeout_seconds, limit=output_limit_bytes,
                max_timeout=MAX_TIMEOUT_SECONDS, cancel=state.cancel, paused=state.paused,
                on_start=on_start, on_chunk=on_chunk,
                process_factory=process_factory if IS_WINDOWS else None,
                on_poll=on_poll if IS_WINDOWS else None,
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
                    "Cancellation terminated the supervised process tree."
                    if state.record.descendant_control_available else
                    "Cancellation terminated the direct child only; descendants may still be running."
                )
            elif result.timed_out:
                status = AgentRunStatus.TIMED_OUT
                limitations.append(
                    "Timeout terminated the supervised process tree."
                    if state.record.descendant_control_available else
                    "Timeout terminated the direct child only; descendants may still be running."
                )
            else:
                exit_code = result.returncode
                status = AgentRunStatus.PASSED if exit_code == 0 else AgentRunStatus.FAILED
        supervised_process = spawned[0]
        descendants = (
            supervised_process.session.records
            if supervised_process is not None and supervised_process.session is not None
            else state.record.descendant_processes
        )
        if state.record.descendant_control_available:
            limitations.extend([SUPERVISED_LIMITATION, RESTRICTED_AUTHORITY])
        final = AgentRun(
            id=run_id, change_id=change_id, adapter=adapter.name, status=status,
            top_level_pid=pid, exit_code=exit_code, started_at=started_at,
            completed_at=utc_now(), duration_ms=int((time.monotonic() - clock) * 1000),
            stdout=stdout, stderr=stderr, output_truncated=truncated,
            descendant_control_available=state.record.descendant_control_available,
            descendant_processes=descendants,
            restricted_token_applied=state.record.restricted_token_applied,
            authority_reduction=state.record.authority_reduction,
            limitations=list(dict.fromkeys(limitations)),
        )
        with self._lock:
            state.record = final
            self._evict()
        self._notify(final)
        if self._tool_registry is not None and tool_manifest is not None:
            self._record_tool_observation(tool_manifest.id, change_id, run_id, "launch")
        state.done.set()
        return final

    def _launch_containerized(
        self, change_id: UUID, root: Path, request: AgentLaunchRequest,
        adapter: AgentAdapter, output_limit_bytes: int,
    ) -> AgentRun:
        """Blocking container-isolated launch (see container_supervisor.py).

        Deliberately does not share `launch()`'s incremental on_poll/capture
        machinery: that machinery is built around a Windows process handle
        and pipe-based stdout/stderr, neither of which a Docker container
        provides the same way. This is a real, current limitation, stated
        here rather than faked with a partial imitation: no live output
        during the run, and no pause/resume/stop support (the run only
        reaches a terminal state once the container itself exits or its
        timeout elapses).
        """

        run_id = uuid4()
        started_at = utc_now()
        running = AgentRun(
            id=run_id, change_id=change_id, adapter=adapter.name,
            status=AgentRunStatus.RUNNING, started_at=started_at,
            isolation_mode="container",
            limitations=[
                "Container isolation: no live output during the run, and no "
                "pause/resume/stop support -- the run only reaches a "
                "terminal state once the container exits or times out.",
                "No Windows process-tree attribution in this mode; only the "
                "container's own process list is visible, in its own PID "
                "namespace, not cross-referenced with host evidence.",
            ],
        )
        state = _State(running, threading.Event(), threading.Event(), threading.Event())
        with self._lock:
            self._runs[run_id] = state
        self._notify(running)

        try:
            argv = [request.executable, *request.args]
            process = container_supervisor.run_containerized(argv, cwd=root, network_isolated=True)
        except AppError as exc:
            failed = running.model_copy(update={
                "status": AgentRunStatus.ERROR, "completed_at": utc_now(),
                "limitations": [*running.limitations, f"The agent did not start: {exc.message}"],
            })
            with self._lock:
                state.record = failed
            self._notify(failed)
            state.done.set()
            return failed

        with self._lock:
            state.record = state.record.model_copy(update={
                "container_id": process.container_id,
                "container_image": process.image,
                "network_isolated": True,
            })
        self._notify(state.record)

        try:
            exit_code = process.wait(timeout=request.timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = None
            timed_out = True
        raw_stdout, raw_stderr = process.logs()
        process.remove()

        completed_at = utc_now()
        stdout = self._text(raw_stdout[:output_limit_bytes], [])
        stderr = self._text(raw_stderr[:output_limit_bytes], [])
        status = (
            AgentRunStatus.TIMED_OUT if timed_out
            else AgentRunStatus.PASSED if exit_code == 0
            else AgentRunStatus.FAILED
        )
        with self._lock:
            state.record = state.record.model_copy(update={
                "status": status, "exit_code": exit_code, "completed_at": completed_at,
                "duration_ms": int((completed_at - started_at).total_seconds() * 1000),
                "stdout": stdout, "stderr": stderr,
                "output_truncated": len(raw_stdout) > output_limit_bytes or len(raw_stderr) > output_limit_bytes,
            })
            final = state.record
        self._notify(final)
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
        state = _State(run, threading.Event(), threading.Event(), threading.Event(), attached=True)
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

    @staticmethod
    def _tree_pids(state: _State, top_level_pid: int) -> list[int]:
        """Every live PID pause/resume should act on together.

        A single top-level PID is not always the process actually doing the
        work: a Windows Python venv's own ``python.exe`` is a launcher stub
        that spawns the real interpreter as a child and waits on it (this is
        standard CPython venv behaviour, not specific to any one install),
        and other wrapped executables can behave the same way. Suspending
        only the stub leaves the real child running -- pause silently does
        nothing, and the run finishes as if pause had never been called.

        When the run has a supervised Job Object (restricted-token launch
        available), this returns the top-level PID plus every PID Windows
        currently reports as a member of that job -- a live query, not the
        historical `descendant_processes` evidence list, so it also catches
        a child that has not yet been individually attributed. Without a
        supervised Job Object (an attached run, or supervision unavailable),
        this falls back to the original top-level-PID-only scope, since
        there is no reliable way to discover descendants otherwise.
        """

        session = getattr(state.process, "session", None)
        job = getattr(session, "job", None) if session is not None else None
        if not job:
            return [top_level_pid]
        try:
            pids = list_pids(job)
        except AppError:
            return [top_level_pid]
        if top_level_pid not in pids:
            pids = [top_level_pid, *pids]
        return [p for p in pids if is_process_running(p)]

    def pause(self, run_id: UUID) -> AgentRun:
        """Suspend the run's process tree (see ``_tree_pids``).

        Requires the run to be ``RUNNING`` with an observed PID; a run that
        is attached, already paused, or already terminal is rejected with a
        stable ``AGENT_RUN_NOT_PAUSABLE`` error rather than silently
        accepted -- pausing something that cannot be paused is a caller bug.
        """

        state = self._runnable_state(run_id)
        if state.attached or state.record.status is not AgentRunStatus.RUNNING:
            raise AppError("AGENT_RUN_NOT_PAUSABLE",
                           "Only a running agent run can be paused.", status_code=409)
        pid = state.record.top_level_pid
        if pid is None:
            raise AppError("AGENT_RUN_NOT_PAUSABLE",
                           "The agent run has no observed process yet.", status_code=409)
        suspended: list[int] = []
        try:
            for target in self._tree_pids(state, pid):
                suspend_process(target)
                suspended.append(target)
        except AppError:
            # Don't leave part of the tree suspended while reporting the
            # pause itself as failed -- best-effort undo, then re-raise.
            for target in suspended:
                try:
                    resume_process(target)
                except AppError:
                    pass
            raise
        with self._lock:
            state.record = state.record.model_copy(
                update={"status": AgentRunStatus.PAUSED, "paused_at": utc_now()})
            paused = state.record
        # capture()'s read loop must not treat a suspended process as timed
        # out or dead: while set, its deadline check is skipped and the
        # paused duration is added back once cleared (see _process.capture).
        state.paused.set()
        self._notify(paused)
        return paused

    def resume(self, run_id: UUID) -> AgentRun:
        """Resume a previously suspended process tree (see ``_tree_pids``)."""

        state = self._runnable_state(run_id)
        if state.attached or state.record.status is not AgentRunStatus.PAUSED:
            raise AppError("AGENT_RUN_NOT_RESUMABLE",
                           "Only a paused agent run can be resumed.", status_code=409)
        pid = state.record.top_level_pid
        if pid is None:
            raise AppError("AGENT_RUN_NOT_RESUMABLE",
                           "The agent run has no observed process.", status_code=409)
        # Resume every member even if one fails, rather than abandoning the
        # rest of the tree suspended because one PID (e.g. one that exited
        # mid-call) couldn't be resumed; the first failure is still raised.
        first_error: AppError | None = None
        for target in self._tree_pids(state, pid):
            try:
                resume_process(target)
            except AppError as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
        with self._lock:
            state.record = state.record.model_copy(
                update={"status": AgentRunStatus.RUNNING, "resumed_at": utc_now()})
            resumed = state.record
        state.paused.clear()
        self._notify(resumed)
        return resumed

    def _runnable_state(self, run_id: UUID) -> _State:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "The agent run does not exist.",
                           status_code=404)
        return state

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
                "descendant_control_available": IS_WINDOWS,
                "restricted_token_available": IS_WINDOWS,
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

    def terminate_change(self, change_id: UUID) -> int:
        """Terminate live supervised process trees belonging to one Change.

        Job handles are intentionally process-instance-local. Persisted runs
        restored after a daemon restart cannot be terminated by this method.
        """

        with self._lock:
            states = [
                state for state in self._runs.values()
                if state.record.change_id == change_id and not state.done.is_set()
            ]
        terminated = 0
        for state in states:
            process = state.process
            if isinstance(process, SupervisedProcess) and process.session is not None:
                terminated += process.session.terminate()
                state.cancel.set()
        return terminated

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
