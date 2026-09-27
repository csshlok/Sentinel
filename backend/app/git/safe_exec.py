"""The single hardened harness through which Sentinel starts every Git process.

Purpose: a repository under Sentinel's supervision is agent-writable. Its
``.git/config``, ``.git/hooks``, ``.gitattributes`` and include files can name
commands that a plain ``git`` invocation would execute at the user's full
authority. Every Git call Sentinel makes is therefore built here, with these
neutralizations applied to every invocation:

* a trusted ``git`` executable resolved from absolute PATH entries outside the
  repository (never a ``.cmd``/``.bat`` wrapper, never a repository directory);
* ``minimal_environment()`` plus ``GIT_CONFIG_NOSYSTEM=1``,
  ``GIT_TERMINAL_PROMPT=0``, ``GIT_OPTIONAL_LOCKS=0``,
  ``GIT_NO_REPLACE_OBJECTS=1``, ``GIT_NO_LAZY_FETCH=1`` and
  ``GIT_ATTR_NOSYSTEM=1``; PATH is rewritten to absolute directories outside
  the repository (and any worktree) Git is pointed at;
* ``-c core.hooksPath=<a verified-empty Sentinel-owned directory>`` so no hook
  from ``.git/hooks`` or a repository-configured hooks directory can run;
* the static execution-bearing overrides in ``STATIC_CONFIG_OVERRIDES``
  (fsmonitor, untracked cache, ssh command, pager, editors, askpass,
  credential helper, gpg programs and signing, external diff, ``ext::``
  transport, submodule recursion, automatic gc/maintenance);
* every configured ``filter.<name>.{clean,smudge,process}`` emptied and
  ``filter.<name>.required=false``, every ``diff.<name>.{command,textconv}``
  and ``merge.<name>.driver`` emptied (discovered from the config Git would
  actually read for that ``-C`` target, once per target per logical
  operation -- see ``SafeGitSession``);
* Git for Windows' system-scope content semantics (``core.autocrlf`` and the
  other keys in ``CARRIED_SYSTEM_KEYS``) carried forward explicitly, because
  ``GIT_CONFIG_NOSYSTEM`` would otherwise change how files are compared;
* an explicit committer identity when a caller commits;
* bounded capture (``execution._process.capture``) with timeouts, never a
  shell, and a Sentinel-owned runtime directory as the child's working
  directory so the repository is never the process cwd.

This is a hardening harness, not a sandbox: Git still runs with the user's
token and can read and write whatever the user can. It removes the ways a
repository can make Git execute *repository-chosen* programs; it does not
confine Git itself.

Caller rule: driver discovery is per ``-C`` context (conditional includes such
as ``includeIf "gitdir:**/worktrees/**"`` resolve differently in a linked
worktree), so any command that reads or writes file content must be run with
``-C`` pointing at the worktree it operates on. Create worktrees with
``--no-checkout`` and populate them with a harnessed ``reset --hard`` run
against the new worktree.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.app.execution._process import CapturedProcess, capture, minimal_environment
from backend.app.execution.resolve import safe_path_entries
from backend.app.git.errors import GitCommandError, GitExecutableNotFoundError

GIT_TIMEOUT_SECONDS = 30
METADATA_LIMIT = 8 * 1_048_576
STDERR_LIMIT = 4096

GLOBAL_FLAGS: tuple[str, ...] = ("--no-pager", "--no-optional-locks")

STATIC_CONFIG_OVERRIDES: tuple[str, ...] = (
    "core.fsmonitor=false",
    "core.untrackedCache=false",
    "core.sshCommand=",
    "core.pager=",
    "core.editor=:",
    "sequence.editor=:",
    "core.askPass=",
    "credential.helper=",
    "gpg.program=",
    "gpg.ssh.program=",
    "gpg.x509.program=",
    "commit.gpgSign=false",
    "tag.gpgSign=false",
    "diff.external=",
    "protocol.ext.allow=never",
    "submodule.recurse=false",
    "diff.submodule=short",
    "color.ui=false",
    "gc.auto=0",
    "maintenance.auto=false",
)

EXECUTION_KEY_PATTERN = re.compile(
    r"(?:filter\..+\.(?:clean|smudge|process|required)"
    r"|diff\..+\.(?:command|textconv)"
    r"|merge\..+\.driver)",
    re.DOTALL,
)

_BOOLEAN_VALUES = frozenset({"true", "false", "yes", "no", "on", "off", "1", "0"})

CARRIED_SYSTEM_KEYS: Mapping[str, frozenset[str]] = {
    "core.autocrlf": frozenset({"true", "false", "input"}),
    "core.eol": frozenset({"lf", "crlf", "native"}),
    "core.safecrlf": frozenset({"true", "false", "warn"}),
    "core.symlinks": _BOOLEAN_VALUES,
    "core.longpaths": _BOOLEAN_VALUES,
    "core.fscache": _BOOLEAN_VALUES,
}

# POSIX ERE handed to `git config --get-regexp`; Git lower-cases the section and
# variable parts of both the pattern and the key before matching.
_DISCOVERY_PATTERN = (
    r"^(filter\..+\.(clean|smudge|process|required)"
    r"|diff\..+\.(command|textconv)"
    r"|merge\..+\.driver"
    r"|core\.(autocrlf|eol|safecrlf|symlinks|longpaths|fscache))$"
)

_IDENTITY_FORBIDDEN = ("\n", "\r", "\0", "<", ">")


@dataclass(frozen=True, slots=True)
class GitIdentity:
    """An explicit author/committer identity passed to Git via ``-c``."""

    name: str
    email: str

    def __post_init__(self) -> None:
        for value in (self.name, self.email):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("A Git identity requires a non-empty name and email.")
            if any(token in value for token in _IDENTITY_FORBIDDEN):
                raise ValueError("A Git identity must not contain newlines, NUL, '<' or '>'.")

    def config_arguments(self) -> tuple[str, ...]:
        # author.* / committer.* outrank user.* in Git, so a repository could
        # otherwise override the identity through its own config.
        arguments: list[str] = []
        for role in ("user", "author", "committer"):
            arguments.extend(["-c", f"{role}.name={self.name}", "-c", f"{role}.email={self.email}"])
        return tuple(arguments)


RECOVERY_IDENTITY = GitIdentity(name="Sentinel Recovery", email="recovery@sentinel.invalid")


def resolve_trusted_git(repository: str | Path, *, extra_roots: Sequence[str | Path] = ()) -> str:
    """Absolute ``git`` executable outside every given root; never a batch wrapper."""

    roots = [Path(root).resolve() for root in (repository, *extra_roots)]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(entry)
        if not entry or not directory.is_absolute():
            continue
        directory = directory.resolve()
        if any(directory == root or root in directory.parents for root in roots):
            continue
        # A fully qualified candidate also avoids Windows cwd search precedence.
        found = shutil.which(str(directory / "git"))
        if not found:
            continue
        resolved = Path(found).resolve()
        if (any(resolved == root or root in resolved.parents for root in roots)
                or resolved.suffix.lower() in {".cmd", ".bat"}):
            continue
        return str(resolved)
    raise GitExecutableNotFoundError()


_HOOKS_LOCK = threading.Lock()
_hooks_directory: Path | None = None


def _is_empty_directory(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.is_dir():
            return False
        with os.scandir(path) as entries:
            return next(entries, None) is None
    except OSError:
        return False


def empty_hooks_directory() -> Path:
    """A Sentinel-owned, verified-empty hooks directory (fresh if tampered with)."""

    global _hooks_directory
    with _HOOKS_LOCK:
        current = _hooks_directory
        if current is not None and _is_empty_directory(current):
            return current
        # Never reuse or delete a directory someone planted files into.
        runtime = Path(tempfile.mkdtemp(prefix="sentinel-git-"))
        hooks = runtime / "hooks"
        hooks.mkdir()
        _hooks_directory = hooks
        return hooks


def hardened_environment(roots: Sequence[Path]) -> dict[str, str]:
    """Minimal environment for Git; PATH excludes every root Git is pointed at."""

    env = minimal_environment()
    env.update({
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_ATTR_NOSYSTEM": "1",
    })
    # Global config (autocrlf etc.) stays visible; every execution-bearing key is
    # overridden on the command line, which outranks every config file.
    for key in ("HOME", "USERPROFILE"):
        if key in os.environ:
            env[key] = os.environ[key]
    resolved_roots = [Path(root).resolve() for root in roots]
    if resolved_roots:
        allowed = [set(safe_path_entries(env, root)) for root in resolved_roots]
        entries = [entry for entry in safe_path_entries(env, resolved_roots[0])
                   if all(entry in group for group in allowed)]
    else:
        entries = [Path(value) for value in env.get("PATH", "").split(os.pathsep)
                   if value and Path(value).is_absolute()]
    env["PATH"] = os.pathsep.join(dict.fromkeys(str(entry) for entry in entries))
    return env


def _parse_config_records(stdout: bytes) -> list[tuple[str, str, str | None]]:
    """Parse ``git config --null --show-scope --get-regexp`` output."""

    if not stdout:
        return []
    try:
        text = stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitCommandError("Git configuration could not be inspected.") from exc
    fields = text.split("\0")
    if fields[-1] != "" or (len(fields) - 1) % 2:
        raise GitCommandError("Git configuration could not be inspected.")
    records: list[tuple[str, str, str | None]] = []
    for index in range(0, len(fields) - 1, 2):
        scope, entry = fields[index], fields[index + 1]
        if not scope or not entry:
            raise GitCommandError("Git configuration could not be inspected.")
        key, separator, value = entry.partition("\n")
        if not key:
            raise GitCommandError("Git configuration could not be inspected.")
        records.append((scope, key, value if separator else None))
    return records


def _overrides_for(records: Sequence[tuple[str, str, str | None]]) -> list[str]:
    overrides: list[str] = []
    emitted: set[str] = set()
    for _scope, key, _value in records:
        if not EXECUTION_KEY_PATTERN.fullmatch(key) or key in emitted:
            continue
        if any(token in key for token in ("=", "\n", "\r", "\0")):
            # Git splits `-c` on the first "=", so such a name cannot be overridden.
            raise GitCommandError("Git configuration uses an unsupported driver name.")
        emitted.add(key)
        overrides.extend(["-c", key + ("=false" if key.endswith(".required") else "=")])
    for carried, allowed in CARRIED_SYSTEM_KEYS.items():
        matching = [(scope, value) for scope, key, value in records if key.lower() == carried]
        if not matching or any(scope != "system" for scope, _ in matching):
            continue
        value = matching[-1][1]
        normalized = (value if value is not None else "true").strip().lower()
        if normalized in allowed:
            overrides.extend(["-c", f"{carried}={normalized}"])
    return overrides


def _static_arguments() -> list[str]:
    arguments: list[str] = []
    for override in STATIC_CONFIG_OVERRIDES:
        arguments.extend(["-c", override])
    return arguments


def _start_failure(exc: BaseException) -> GitCommandError | GitExecutableNotFoundError:
    if isinstance(exc, FileNotFoundError):
        return GitExecutableNotFoundError()
    return GitCommandError("Git could not start.")


@dataclass(frozen=True, slots=True, eq=False)
class HardenedGit:
    """One discovered, hardened Git configuration for a single ``-C`` target.

    ``prefix`` holds every ``-c`` override after the per-call hooks directory:
    static overrides, discovered driver overrides, carried system keys and the
    optional identity. ``run`` re-verifies the hooks directory before each call.
    """

    executable: str
    repository: str
    env: Mapping[str, str]
    prefix: tuple[str, ...]

    @classmethod
    def open(
        cls,
        repository: str | Path,
        *,
        identity: GitIdentity | None = None,
        extra_roots: Sequence[str | Path] = (),
    ) -> HardenedGit:
        target = os.path.abspath(os.fspath(repository))
        executable = resolve_trusted_git(target, extra_roots=extra_roots)
        env = hardened_environment([Path(target), *(Path(root) for root in extra_roots)])
        discovery_env = {key: value for key, value in env.items() if key != "GIT_CONFIG_NOSYSTEM"}
        hooks = empty_hooks_directory()
        static = _static_arguments()
        try:
            # Reading configuration executes nothing; the system scope must be
            # visible here so its content semantics can be carried forward.
            discovered = capture(
                [executable, *GLOBAL_FLAGS, "-c", f"core.hooksPath={hooks}", *static,
                 "-C", target, "config", "--null", "--show-scope", "--get-regexp",
                 _DISCOVERY_PATTERN],
                cwd=hooks.parent, env=discovery_env, timeout=GIT_TIMEOUT_SECONDS,
                limit=METADATA_LIMIT, stderr_limit=STDERR_LIMIT,
            )
        except (OSError, ValueError, UnicodeError) as exc:
            raise _start_failure(exc) from exc
        if discovered.timed_out or discovered.incomplete or discovered.truncated:
            raise GitCommandError("Git configuration could not be inspected.")
        if discovered.returncode not in {0, 1}:
            raise GitCommandError(details={"exit_code": discovered.returncode})
        records = _parse_config_records(discovered.stdout)
        prefix = (*static, *_overrides_for(records),
                  *(identity.config_arguments() if identity is not None else ()))
        return cls(executable=executable, repository=target, env=env, prefix=tuple(prefix))

    def run(
        self,
        args: Sequence[str],
        *,
        limit: int = METADATA_LIMIT,
        timeout: float = GIT_TIMEOUT_SECONDS,
        stderr_limit: int = STDERR_LIMIT,
    ) -> CapturedProcess:
        hooks = empty_hooks_directory()
        argv = [self.executable, *GLOBAL_FLAGS, "-c", f"core.hooksPath={hooks}",
                *self.prefix, "-C", self.repository, *args]
        try:
            return capture(argv, cwd=hooks.parent, env=self.env, timeout=timeout,
                           limit=limit, stderr_limit=stderr_limit)
        except (OSError, ValueError, UnicodeError) as exc:
            raise _start_failure(exc) from exc


class SafeGitSession:
    """Config discovery shared by the Git calls of ONE logical operation.

    ``HardenedGit.open`` runs one discovery Git process. A single inspection
    makes about a dozen Git calls against the same ``-C`` target, so the
    inspector opens one ``SafeGitSession`` per ``inspect()``/capture and reuses
    the discovered overrides for every call inside it.

    Scope rules (security):

    * A session is created by the caller for one operation and discarded when
      that operation returns. It is never stored on a long-lived object or
      module global, so configuration changed between operations (the agent
      can edit ``.git/config`` at any time) is always rediscovered.
    * Discovery is keyed by the exact absolute ``-C`` target. Another
      repository, a subdirectory, or a linked worktree gets its own discovery,
      so conditional includes such as ``includeIf "gitdir:**/worktrees/**"``
      are still resolved in the context Git will actually use.
    * The hooks directory and child cwd are still re-verified on every
      ``run()`` (``HardenedGit.run``).

    Residual window (accepted): driver keys *added* to the configuration while
    one operation is in progress are not neutralized for the remainder of that
    operation. Per-call discovery had the same window between discovery and
    the command; the session widens it from one call to one operation.
    Inspection keeps its independent layers for that window: every
    ``status``/``diff`` call refuses files carrying a filter attribute,
    ``--no-ext-diff``/``--no-textconv`` disable diff drivers, and the
    inspection re-reads status and diff and fails if the repository moved.
    """

    __slots__ = ("_extra_roots", "_identity", "_sessions", "discoveries")

    def __init__(
        self,
        *,
        identity: GitIdentity | None = None,
        extra_roots: Sequence[str | Path] = (),
    ) -> None:
        self._identity = identity
        self._extra_roots = tuple(extra_roots)
        self._sessions: dict[str, HardenedGit] = {}
        self.discoveries = 0

    def git(self, repository: str | Path) -> HardenedGit:
        """The hardened configuration for ``repository``, discovered on first use."""

        target = os.path.abspath(os.fspath(repository))
        session = self._sessions.get(target)
        if session is None:
            session = HardenedGit.open(target, identity=self._identity,
                                       extra_roots=self._extra_roots)
            self._sessions[target] = session
            self.discoveries += 1
        return session

    def run(
        self,
        repository: str | Path,
        args: Sequence[str],
        *,
        limit: int = METADATA_LIMIT,
        timeout: float = GIT_TIMEOUT_SECONDS,
        stderr_limit: int = STDERR_LIMIT,
    ) -> CapturedProcess:
        return self.git(repository).run(args, limit=limit, timeout=timeout,
                                        stderr_limit=stderr_limit)


def run_git(
    repository: str | Path,
    args: Sequence[str],
    *,
    limit: int = METADATA_LIMIT,
    timeout: float = GIT_TIMEOUT_SECONDS,
    stderr_limit: int = STDERR_LIMIT,
    identity: GitIdentity | None = None,
    extra_roots: Sequence[str | Path] = (),
) -> CapturedProcess:
    """Run one hardened Git command with fresh discovery for its ``-C`` target."""

    session = HardenedGit.open(repository, identity=identity, extra_roots=extra_roots)
    return session.run(args, limit=limit, timeout=timeout, stderr_limit=stderr_limit)
