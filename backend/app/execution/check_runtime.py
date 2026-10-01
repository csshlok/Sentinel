"""Content-addressed runtime snapshots that confined checks read from.

A ``check`` AppContainer cannot load the host interpreter in place (spike 006
A), and Sentinel can only add an ACE where the user holds WRITE_DAC, so a
confined check gets copies: a stdlib-only interpreter snapshot plus a snapshot
of the requested interpreter's ``site-packages`` (or ``node.exe`` plus npm,
plus the project's ``node_modules``). Each snapshot lives under
``%LOCALAPPDATA%\\Sentinel\\check-runtimes\\<kind>\\<digest>``, where the digest
covers a sorted file manifest (POSIX relative path, size, SHA-256).

An entry is never mutated. Reuse re-verifies every file of the existing entry
against the freshly computed source manifest; a mismatch is
``CHECK_RUNTIME_TAMPERED`` and the entry is left in place for inspection.
Source drift simply yields a new digest and therefore a new entry. Sources
containing a symlink, junction or other reparse point are refused, never
followed. Interpreter facts come from running the requested interpreter with
``-I -S`` from a fresh temporary directory outside any repository, so no
project code runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import time
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from backend.app.core.errors import AppError
from backend.app.execution._process import capture, minimal_environment
from backend.app.execution.acl import restrict_to_current_user
from backend.app.execution.agent_staging import _is_reparse
from backend.app.execution.appcontainer import local_appdata_known_folder, remove_tree_no_follow

LOGGER = logging.getLogger(__name__)

STORE_DIRECTORY_NAME = "Sentinel"
RUNTIME_DIRECTORY_NAME = "check-runtimes"
DEFAULT_SIZE_LIMIT_BYTES = 2 * 1024**3
# WR-08 cache sweep (startup): crash-orphaned partial copies and entries unused
# for this long are removed; an entry a non-CLEANED check run names never is.
PARTIAL_MAX_AGE_SECONDS = 3600
UNUSED_ENTRY_MAX_AGE_SECONDS = 14 * 24 * 3600
LAST_USE_SUFFIX = ".last-use"
PROBE_TIMEOUT_SECONDS = 30
PROBE_OUTPUT_LIMIT = 64 * 1024
_CHUNK = 1 << 20
_KIND_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")

PYTHON_BASE_IGNORE = frozenset({
    "site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter",
    "turtledemo", "doc", "tools", "include", "libs", "tcl",
})
PYTHON_DEPS_IGNORE = frozenset({"__pycache__"})

# WR-05: PYTHONPATH entries are not site directories, so ``.pth`` files in the
# dependency snapshot would never be processed (relative path entries such as
# pywin32's ``win32``, ``import`` lines such as ``distutils-precedence.pth``).
# The interpreter snapshot therefore carries this ``sitecustomize`` (imported by
# ``site`` at startup), which makes the dependency snapshot a real site
# directory exactly as the venv's site-packages is. It runs inside the box only.
SITE_PACKAGES_ENV = "SENTINEL_CHECK_SITE_PACKAGES"
SITECUSTOMIZE_RELPATH = "Lib/sitecustomize.py"
SITECUSTOMIZE_SOURCE = (
    '"""Sentinel check box: process the dependency snapshot as a site directory."""\n'
    "import os as _os\n"
    "import site as _site\n"
    "\n"
    f"_deps = _os.environ.get({SITE_PACKAGES_ENV!r})\n"
    "if _deps:\n"
    "    _site.addsitedir(_deps)\n"
    "del _os, _site, _deps\n"
).encode("utf-8")

_PROBE_SOURCE = (
    "import json, sys, sysconfig; "
    "print(json.dumps({'base_prefix': sys.base_prefix, 'prefix': sys.prefix, "
    "'purelib': sysconfig.get_paths()['purelib']}))"
)


# ---------------------------------------------------------------------- errors


def check_runtime_tampered(kind: str, digest: str) -> AppError:
    return AppError(
        "CHECK_RUNTIME_TAMPERED",
        "A cached check runtime no longer matches the manifest it was stored under; "
        "Sentinel refuses to use or modify it.",
        status_code=409,
        details={"kind": kind, "manifest_digest": digest},
    )


def check_runtime_too_large(kind: str, limit: int) -> AppError:
    return AppError(
        "CHECK_RUNTIME_TOO_LARGE",
        "The check runtime source exceeds the configured snapshot size limit.",
        status_code=409,
        details={"kind": kind, "limit_bytes": limit},
    )


def check_runtime_unsafe_source(kind: str, reason: str) -> AppError:
    return AppError(
        "CHECK_RUNTIME_UNSAFE_SOURCE",
        "The check runtime source contains an entry Sentinel will not copy.",
        status_code=409,
        details={"kind": kind, "reason": reason},
    )


def check_runtime_failed(kind: str, reason: str) -> AppError:
    return AppError(
        "CHECK_RUNTIME_FAILED",
        "The check runtime snapshot could not be prepared.",
        status_code=409,
        details={"kind": kind, "reason": reason},
    )


# ---------------------------------------------------------------------- model


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    relpath: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """One verified cache entry: ``path`` holds exactly the files its manifest names."""

    path: Path
    manifest_digest: str
    bytes: int


class PythonRuntime(NamedTuple):
    interpreter: RuntimeSnapshot
    dependencies: RuntimeSnapshot
    limitations: tuple[str, ...]


# ---------------------------------------------------------------------- root


def check_runtime_root(
    environ: Mapping[str, str] | None = None, *, create: bool = True,
) -> Path:
    """``%LOCALAPPDATA%\\Sentinel\\check-runtimes`` (the evidence store's base).

    With ``create`` the directory is created and restricted to the current
    user (plus SYSTEM); a failed restriction is logged, never claimed.
    """

    source = os.environ if environ is None else environ
    local_app_data = source.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    root = base / STORE_DIRECTORY_NAME / RUNTIME_DIRECTORY_NAME
    if create:
        _prepare_root(root)
    return root


def _prepare_root(root: Path) -> None:
    for candidate in (root.parent, root):
        if os.path.lexists(candidate) and _is_reparse(candidate):
            raise check_runtime_unsafe_source("root", "the cache root is a link or reparse point")
    existed = os.path.lexists(root)
    root.mkdir(parents=True, exist_ok=True)
    if _is_reparse(root) or not stat.S_ISDIR(os.lstat(root).st_mode):
        raise check_runtime_unsafe_source("root", "the cache root is not a real directory")
    if not existed and not restrict_to_current_user(root, directory=True):
        LOGGER.warning(
            "Could not restrict the check runtime cache %s to the current user and SYSTEM.",
            root,
        )


def _real_directory(path: Path, kind: str, what: str) -> None:
    if _is_reparse(path):
        raise check_runtime_unsafe_source(kind, f"the {what} is a link or reparse point")
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        raise check_runtime_unsafe_source(kind, f"the {what} is not a directory")


# ---------------------------------------------------------------------- manifest


_EXTENDED_PREFIX = "\\\\?\\"


def _long(path: Path) -> Path:
    """The extended-length form on Windows, so deep trees beyond MAX_PATH still copy."""

    if os.name != "nt":
        return path
    text = os.path.abspath(path)
    if text.startswith(_EXTENDED_PREFIX):
        return Path(text)
    if text.startswith("\\\\"):
        return Path(_EXTENDED_PREFIX + "UNC\\" + text[2:])
    return Path(_EXTENDED_PREFIX + text)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _walk(
    source: Path, prefix: str, *, kind: str, ignore: frozenset[str],
) -> Iterable[tuple[str, Path]]:
    """(posix relpath, absolute path) of every regular file under ``source``.

    Refuses reparse points and special files; never follows a link.
    """

    stack: list[tuple[Path, str]] = [(source, prefix)]
    while stack:
        directory, relative = stack.pop()
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            path = Path(entry.path)
            name = f"{relative}/{entry.name}" if relative else entry.name
            if _is_reparse(path):
                raise check_runtime_unsafe_source(kind, f"{name} is a link or reparse point")
            mode = os.lstat(path).st_mode
            if stat.S_ISDIR(mode):
                if entry.name.casefold() in ignore:
                    continue
                stack.append((path, name))
            elif stat.S_ISREG(mode):
                yield name, path
            else:
                raise check_runtime_unsafe_source(kind, f"{name} is not a regular file")


def _source_files(
    sources: Iterable[tuple[str, Path]], *, kind: str, ignore: frozenset[str],
) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for prefix, source in sources:
        source = _long(Path(source))
        if not os.path.lexists(source):
            raise check_runtime_failed(kind, f"the source {prefix or '.'} does not exist")
        if _is_reparse(source):
            raise check_runtime_unsafe_source(kind, f"the source {prefix or '.'} is a link or reparse point")
        mode = os.lstat(source).st_mode
        if stat.S_ISDIR(mode):
            files.extend(_walk(source, prefix, kind=kind, ignore=ignore))
        elif stat.S_ISREG(mode) and prefix:
            files.append((prefix, source))
        else:
            raise check_runtime_unsafe_source(kind, f"the source {prefix or '.'} is not a regular file")
    files.sort(key=lambda item: item[0])
    seen: set[str] = set()
    for relpath, _ in files:
        folded = relpath.casefold()
        if folded in seen:
            raise check_runtime_unsafe_source(kind, f"{relpath} appears twice")
        seen.add(folded)
    return files


def _manifest(
    files: list[tuple[str, Path]], *, kind: str, size_limit: int,
) -> list[ManifestEntry]:
    total = 0
    for _, path in files:
        total += os.lstat(path).st_size
        if total > size_limit:
            raise check_runtime_too_large(kind, size_limit)
    entries: list[ManifestEntry] = []
    total = 0
    for relpath, path in files:
        size, digest = _hash_file(path)
        total += size
        if total > size_limit:
            raise check_runtime_too_large(kind, size_limit)
        entries.append(ManifestEntry(relpath, size, digest))
    return entries


def manifest_digest(entries: Iterable[ManifestEntry]) -> str:
    """SHA-256 over ``relpath NUL size NUL sha256 LF`` lines, in manifest order."""

    digest = hashlib.sha256()
    for entry in entries:
        digest.update(f"{entry.relpath}\0{entry.size}\0{entry.sha256}\n".encode("utf-8"))
    return digest.hexdigest()


def _entry_manifest(path: Path, *, kind: str, size_limit: int) -> list[ManifestEntry]:
    files = _source_files([("", path)], kind=kind, ignore=frozenset())
    return _manifest(files, kind=kind, size_limit=size_limit)


# ---------------------------------------------------------------------- snapshots


def _snapshot(
    sources: Iterable[tuple[str, Path]], *, kind: str, root: Path | None,
    ignore: frozenset[str], size_limit: int,
) -> RuntimeSnapshot:
    if not _KIND_PATTERN.fullmatch(kind):
        raise ValueError(f"invalid runtime kind {kind!r}")
    try:
        cache = check_runtime_root() if root is None else Path(root)
        if root is not None:
            _prepare_root(cache)
        files = _source_files(sources, kind=kind, ignore=ignore)
        entries = _manifest(files, kind=kind, size_limit=size_limit)
        digest = manifest_digest(entries)
        total = sum(entry.size for entry in entries)
        kind_directory = cache / kind
        if os.path.lexists(kind_directory):
            _real_directory(kind_directory, kind, "runtime kind folder")
        else:
            kind_directory.mkdir()
        target = kind_directory / digest
        if os.path.lexists(target):
            return _mark_used(_verified_existing(target, entries, kind=kind, digest=digest,
                                                 total=total, size_limit=size_limit))
        partial = kind_directory / f".{digest}.{uuid4().hex}.partial"
        try:
            partial.mkdir()
            _copy_into(partial, files, entries, kind=kind)
            try:
                os.rename(partial, target)
            except OSError:
                if not os.path.lexists(target):
                    raise
                # Another builder published the same digest first; verify theirs.
                return _mark_used(_verified_existing(target, entries, kind=kind, digest=digest,
                                                     total=total, size_limit=size_limit))
        finally:
            if os.path.lexists(partial):
                remove_tree_no_follow(partial)
        return _mark_used(RuntimeSnapshot(target, digest, total))
    except AppError:
        raise
    except OSError as exc:
        raise check_runtime_failed(kind, type(exc).__name__) from exc


def _last_use_path(entry: Path) -> Path:
    return entry.parent / f".{entry.name}{LAST_USE_SUFFIX}"


def _mark_used(snapshot: RuntimeSnapshot) -> RuntimeSnapshot:
    """Record the entry's last use in a sibling marker (the entry itself is never mutated)."""

    marker = _last_use_path(snapshot.path)
    try:
        if os.path.lexists(marker) and _is_reparse(marker):
            return snapshot  # never write through a link; the sweep then uses the entry's mtime
        with open(marker, "w", encoding="ascii") as handle:
            handle.write(str(int(time.time())))
    except OSError:
        LOGGER.warning("Could not record the last use of check runtime %s", snapshot.path)
    return snapshot


@dataclass(frozen=True, slots=True)
class RuntimeCacheSweepReport:
    removed_partials: tuple[str, ...] = ()
    evicted: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


def _age(path: Path, now: float) -> float:
    return now - os.lstat(path).st_mtime


def sweep_runtime_cache(
    root: str | Path | None = None, *, in_use: Collection[str | Path] = (),
    now: float | None = None, partial_max_age: float = PARTIAL_MAX_AGE_SECONDS,
    unused_max_age: float = UNUSED_ENTRY_MAX_AGE_SECONDS,
) -> RuntimeCacheSweepReport:
    """Remove crash-orphaned ``.partial`` copies and long-unused entries (WR-08).

    Run at startup, before any box opens. ``in_use`` names entries a non-CLEANED
    check run still references (and may still be granted to): those are never
    removed. An entry is evicted once its last use (the sibling ``.last-use``
    marker, else the entry folder's own mtime) is older than ``unused_max_age``.
    Only real directories directly under ``<root>/<kind>`` are touched; links
    are never followed or removed. Failures are collected, never raised.
    """

    cache = check_runtime_root(create=False) if root is None else Path(root)
    current = time.time() if now is None else now
    if (not os.path.lexists(cache) or _is_reparse(cache)
            or not stat.S_ISDIR(os.lstat(cache).st_mode)):
        return RuntimeCacheSweepReport()
    keep = {os.path.normcase(os.path.abspath(path)) for path in in_use}
    removed: list[str] = []
    evicted: list[str] = []
    failed: list[str] = []
    with os.scandir(cache) as kinds:
        kind_names = sorted(entry.name for entry in kinds)
    for kind in kind_names:
        kind_directory = cache / kind
        if (not _KIND_PATTERN.fullmatch(kind) or _is_reparse(kind_directory)
                or not stat.S_ISDIR(os.lstat(kind_directory).st_mode)):
            continue
        with os.scandir(kind_directory) as children:
            names = sorted(child.name for child in children)
        for name in names:
            path = kind_directory / name
            label = f"{kind}/{name}"
            try:
                if _is_reparse(path) or not stat.S_ISDIR(os.lstat(path).st_mode):
                    continue
                if name.startswith(".") and name.endswith(".partial"):
                    if _age(path, current) > partial_max_age:
                        remove_tree_no_follow(path)
                        removed.append(label)
                    continue
                if not _DIGEST_PATTERN.fullmatch(name):
                    continue
                if os.path.normcase(os.path.abspath(path)) in keep:
                    continue
                marker = _last_use_path(path)
                last_use = (marker if os.path.lexists(marker) and not _is_reparse(marker)
                            else path)
                if _age(last_use, current) <= unused_max_age:
                    continue
                remove_tree_no_follow(path)
                for sibling in (marker, path.parent / f".{name}.acl-lock"):
                    if os.path.lexists(sibling) and not _is_reparse(sibling):
                        os.unlink(sibling)
                evicted.append(label)
            except OSError as exc:
                LOGGER.warning("check runtime cache sweep could not remove %s (%s)", label,
                               type(exc).__name__)
                failed.append(label)
    return RuntimeCacheSweepReport(tuple(removed), tuple(evicted), tuple(failed))


def _verified_existing(
    target: Path, entries: list[ManifestEntry], *, kind: str, digest: str, total: int,
    size_limit: int,
) -> RuntimeSnapshot:
    try:
        _real_directory(target, kind, "cache entry")
        existing = _entry_manifest(target, kind=kind, size_limit=size_limit)
    except AppError as exc:
        raise check_runtime_tampered(kind, digest) from exc
    if existing != entries:
        raise check_runtime_tampered(kind, digest)
    return RuntimeSnapshot(target, digest, total)


def _copy_into(
    destination: Path, files: list[tuple[str, Path]], entries: list[ManifestEntry], *,
    kind: str,
) -> None:
    destination = _long(destination)
    for (relpath, source), expected in zip(files, entries, strict=True):
        target = destination.joinpath(*relpath.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        copied = hashlib.sha256()
        size = 0
        with open(source, "rb") as reader, open(target, "xb") as writer:
            for chunk in iter(lambda: reader.read(_CHUNK), b""):
                size += len(chunk)
                copied.update(chunk)
                writer.write(chunk)
        # A swap of the source between hashing and copying is caught here.
        if size != expected.size or copied.hexdigest() != expected.sha256:
            raise check_runtime_failed(kind, f"{relpath} changed while it was copied")


def snapshot_tree(
    source: str | Path, *, kind: str, root: str | Path | None = None,
    ignore: Iterable[str] = (), size_limit: int = DEFAULT_SIZE_LIMIT_BYTES,
) -> RuntimeSnapshot:
    """Snapshot the directory ``source`` into ``<root>/<kind>/<manifest digest>``.

    ``ignore`` names directories (case-insensitively, at any depth) to leave out.
    """

    return _snapshot(
        [("", Path(source))], kind=kind, root=None if root is None else Path(root),
        ignore=frozenset(name.casefold() for name in ignore), size_limit=size_limit,
    )


# ---------------------------------------------------------------------- python


def _interpreter_facts(interpreter: Path) -> tuple[Path, Path]:
    probe_directory = Path(tempfile.mkdtemp(prefix="sentinel-pyfacts-"))
    try:
        result = capture(
            [str(interpreter), "-I", "-S", "-c", _PROBE_SOURCE],
            cwd=probe_directory, env=minimal_environment(),
            timeout=PROBE_TIMEOUT_SECONDS, limit=PROBE_OUTPUT_LIMIT,
        )
    finally:
        remove_tree_no_follow(probe_directory)
    if result.returncode != 0 or result.timed_out or result.truncated:
        raise check_runtime_failed("python", "the interpreter facts probe failed")
    try:
        facts = json.loads(result.stdout.decode("utf-8"))
        base_prefix = Path(facts["base_prefix"])
        prefix = Path(facts["prefix"])
        purelib = Path(facts["purelib"])
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise check_runtime_failed("python", "the interpreter facts were unreadable") from exc
    for path in (base_prefix, prefix, purelib):
        if not path.is_absolute():
            raise check_runtime_failed("python", "the interpreter reported a relative path")
    _validate_interpreter_facts(interpreter, base_prefix, prefix, purelib)
    return base_prefix, purelib


def _regular_file(path: Path) -> bool:
    try:
        return not _is_reparse(path) and stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _validate_interpreter_facts(
    interpreter: Path, base_prefix: Path, prefix: Path, purelib: Path,
) -> None:
    """WR-09: the probe is the interpreter's own word, so its answer is checked, not trusted.

    Its output decides what gets copied into the cache and granted to the box.
    ``base_prefix`` must be a real Python install (``python.exe`` and
    ``Lib/os.py``), ``purelib`` a ``site-packages`` folder under ``sys.prefix``
    or ``base_prefix``, and the interpreter must live under ``sys.prefix``. A
    lying interpreter (or an edited ``pyvenv.cfg``) cannot point the snapshot
    at, say, the user profile.
    """

    if not (_regular_file(base_prefix / "python.exe")
            and _regular_file(base_prefix / "Lib" / "os.py")):
        raise check_runtime_failed("python", "the reported base prefix is not a Python install")
    if purelib.name.casefold() != "site-packages" or not (
            _inside(purelib, prefix) or _inside(purelib, base_prefix)):
        raise check_runtime_failed(
            "python", "the reported site-packages is not under the interpreter's prefix")
    if not _inside(interpreter, prefix):
        raise check_runtime_failed("python", "the interpreter is not inside its reported prefix")


def _refused_interpreter_location(interpreter: Path) -> str | None:
    """Sentinel-owned, agent-writable places a requested interpreter may never come from.

    Every AppContainer profile folder (agent workspace clones, check-box trees and
    scratch) lives under ``<LocalAppData>/Packages``; the Sentinel store (with
    this cache) under ``%LOCALAPPDATA%/Sentinel``. The interpreter facts probe runs
    the interpreter at user authority, so it is refused there before it runs.
    """

    resolved = Path(os.path.abspath(interpreter))
    try:
        packages = local_appdata_known_folder() / "Packages"
    except (OSError, AppError):
        packages = None
    if packages is not None and _inside(resolved, packages):
        return "the interpreter is inside an AppContainer profile folder"
    if _inside(resolved, check_runtime_root(create=False).parent):
        return "the interpreter is inside the Sentinel store"
    return None


def _inside(path: Path, directory: Path) -> bool:
    child = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(directory))
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)


def _path_limitations(purelib: Path, *, site_hook: bool = True) -> tuple[str, ...]:
    """``.pth``/``.egg-link`` entries whose import path the box cannot read.

    Without the snapshot's ``sitecustomize`` hook (the interpreter ships its own
    ``sitecustomize.py``), no ``.pth`` file is processed in the box at all, and
    every one is reported.
    """

    limitations: list[str] = []
    try:
        names = sorted(os.listdir(purelib))
    except OSError:
        return ()
    for name in names:
        lowered = name.casefold()
        path = purelib / name
        if lowered.endswith(".egg-link"):
            limitations.append(f"{name}: egg-link to a source tree outside the dependency snapshot")
            continue
        if not lowered.endswith(".pth"):
            continue
        if lowered.startswith("__editable__"):
            limitations.append(f"{name}: editable install whose source is outside the dependency snapshot")
            continue
        if not site_hook:
            limitations.append(f"{name}: .pth file not processed in the box (the interpreter "
                               "ships its own sitecustomize.py)")
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            entry = line.strip()
            if not entry or entry.startswith("#") or entry.startswith(("import ", "import\t")):
                continue
            target = Path(entry)
            if not target.is_absolute():
                target = purelib / target
            if not _inside(target, purelib):
                limitations.append(f"{name}: path entry outside the dependency snapshot")
                break
    return tuple(limitations)


def python_runtime(
    interpreter: str | Path, *, root: str | Path | None = None,
    size_limit: int = DEFAULT_SIZE_LIMIT_BYTES,
) -> PythonRuntime:
    """Interpreter (stdlib only) and dependency snapshots for ``interpreter``.

    The caller must already have accepted ``interpreter`` as trusted.
    """

    interpreter_path = Path(interpreter)
    if not interpreter_path.is_absolute() or not interpreter_path.is_file():
        raise check_runtime_failed("python", "the interpreter must be an absolute file path")
    refused = _refused_interpreter_location(interpreter_path)
    if refused is not None:
        raise check_runtime_failed("python", refused)
    base_prefix, purelib = _interpreter_facts(interpreter_path)
    cache = None if root is None else Path(root)
    site_hook = not os.path.lexists(base_prefix / Path(SITECUSTOMIZE_RELPATH))
    hook_directory = Path(tempfile.mkdtemp(prefix="sentinel-sitehook-"))
    try:
        sources: list[tuple[str, Path]] = [("", base_prefix)]
        if site_hook:
            hook = hook_directory / "sitecustomize.py"
            hook.write_bytes(SITECUSTOMIZE_SOURCE)
            sources.append((SITECUSTOMIZE_RELPATH, hook))
        base = _snapshot(sources, kind="python", root=cache,
                         ignore=PYTHON_BASE_IGNORE, size_limit=size_limit)
    finally:
        remove_tree_no_follow(hook_directory)
    deps = _snapshot([("", purelib)], kind="python-deps", root=cache,
                     ignore=PYTHON_DEPS_IGNORE, size_limit=size_limit)
    return PythonRuntime(base, deps, _path_limitations(purelib, site_hook=site_hook))


# ---------------------------------------------------------------------- node


def node_runtime(
    node_exe: str | Path, *, root: str | Path | None = None,
    size_limit: int = DEFAULT_SIZE_LIMIT_BYTES,
) -> RuntimeSnapshot:
    """``node.exe`` plus the bundled ``node_modules/npm`` package (when present)."""

    node = Path(node_exe)
    if not node.is_absolute() or not node.is_file():
        raise check_runtime_failed("node", "node must be an absolute file path")
    sources: list[tuple[str, Path]] = [(node.name, node)]
    npm = node.parent / "node_modules" / "npm"
    if os.path.lexists(npm):
        sources.append(("node_modules/npm", npm))
    return _snapshot(sources, kind="node", root=None if root is None else Path(root),
                     ignore=frozenset(), size_limit=size_limit)


def node_modules_snapshot(
    repo_root: str | Path, *, root: str | Path | None = None,
    size_limit: int = DEFAULT_SIZE_LIMIT_BYTES,
) -> RuntimeSnapshot | None:
    """Snapshot ``<repo>/node_modules``; None when it is missing or empty."""

    modules = Path(repo_root) / "node_modules"
    if not os.path.lexists(modules):
        return None
    if _is_reparse(modules):
        raise check_runtime_unsafe_source("node-modules", "node_modules is a link or reparse point")
    if not stat.S_ISDIR(os.lstat(modules).st_mode):
        raise check_runtime_unsafe_source("node-modules", "node_modules is not a directory")
    with os.scandir(modules) as entries:
        if next(entries, None) is None:
            return None
    return _snapshot([("", modules)], kind="node-modules",
                     root=None if root is None else Path(root),
                     ignore=frozenset(), size_limit=size_limit)
