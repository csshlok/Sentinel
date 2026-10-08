"""Runtime caller evidence for changed test modules in a coverage run.

This file is copied into the check box's scratch directory and launched by the
trusted interpreter. Keep its runtime imports in the standard library: the
repository's application package is not part of a Python runtime snapshot.
"""

from __future__ import annotations

import atexit
import json
import os
import runpy
import sys
import threading
from pathlib import Path

RECORD_NAME = "test-call-monitor.json"
CONFIG_NAME = "test-call-monitor-config.json"
SCRIPT_NAME = "test-call-monitor.py"
MAX_VIOLATIONS = 128


def _normal(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _repository_path(filename: str, root: str) -> str | None:
    if filename.startswith("<") and filename.endswith(">"):
        return None
    try:
        relative = os.path.relpath(_normal(filename), root)
    except (OSError, ValueError):
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    return relative.replace(os.sep, "/")


def _is_test_code(relative: str) -> bool:
    name = relative.rsplit("/", 1)[-1].lower()
    return (name == "conftest.py" or name.startswith("test_") and name.endswith(".py")
            or name.endswith("_test.py") or
            any(part in {"test", "tests"} for part in relative.lower().split("/")[:-1])
            and name.endswith(".py"))


def install_monitor(*, root: str, changed_tests: list[str], output: str) -> str:
    """Observe function starts in changed tests and write one bounded record at exit."""
    root = _normal(root)
    session_entry = sys._getframe(1)
    main_thread = threading.main_thread()
    targets = {_normal(os.path.join(root, path.replace("/", os.sep))): path
               for path in changed_tests}
    found: dict[str, str | None] = {}
    violations: list[str] = []

    def target(filename: str) -> str | None:
        if filename not in found:
            found[filename] = targets.get(_normal(filename))
        return found[filename]

    def observe(code, started_frame) -> None:
        if len(violations) >= MAX_VIOLATIONS:
            return
        path = target(code.co_filename)
        if path is None:
            return
        if threading.current_thread() is not main_thread:
            violations.append(f"Changed test code ran on a non-main thread: "
                              f"{path}:{code.co_firstlineno}")
            return
        frame = started_frame.f_back if started_frame is not None else None
        while frame is not None:
            if frame is session_entry:
                return
            caller_path = _repository_path(frame.f_code.co_filename, root)
            if caller_path is not None and not _is_test_code(caller_path):
                violations.append(f"{caller_path}:{frame.f_lineno} -> "
                                  f"{path}:{code.co_firstlineno}")
                return
            frame = frame.f_back
        violations.append("Changed test code ran outside the pytest session stack "
                          f"(atexit/finalizer/signal handler): {path}:{code.co_firstlineno}")

    backend = "sys.setprofile"
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is not None:
        acquired = False
        try:
            tool = monitoring.PROFILER_ID
            monitoring.use_tool_id(tool, "sentinel-test-call-monitor")
            acquired = True

            def on_enter(code, _offset, *_exception):
                if target(code.co_filename) is None:
                    # CPython does not permit DISABLE for PY_THROW.
                    return None if _exception else monitoring.DISABLE
                frame = sys._getframe(1)
                observe(code, frame)

            events = (monitoring.events.PY_START | monitoring.events.PY_RESUME |
                      monitoring.events.PY_THROW)
            for event in (monitoring.events.PY_START, monitoring.events.PY_RESUME,
                          monitoring.events.PY_THROW):
                monitoring.register_callback(tool, event, on_enter)
            monitoring.set_events(tool, events)
            backend = "sys.monitoring"
        except (AttributeError, RuntimeError, ValueError):
            if acquired:
                try:
                    monitoring.free_tool_id(monitoring.PROFILER_ID)
                except (AttributeError, RuntimeError, ValueError):
                    pass
    if backend == "sys.setprofile":
        def on_call(frame, event, _arg):
            if event == "call":
                observe(frame.f_code, frame)

        sys.setprofile(on_call)

    def write_record() -> None:
        record = {"schema": 1, "backend": backend, "changed_tests": sorted(targets.values()),
                  "violations": violations}
        # Agent code runs in this process and can pre-create the known scratch
        # name. Our atexit handler runs after handlers registered by tests, so
        # overwrite that file with the observed record.
        with open(output, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, separators=(",", ":"))

    atexit.register(write_record)
    return backend


def prepare_monitor(scratch: Path, tree: Path, changed_tests: list[str],
                    coverage_argv: list[str]) -> tuple[list[str], str]:
    """Create a scratch launcher and return its argv plus expected record name."""
    if len(coverage_argv) < 5 or coverage_argv[3:5] != ["-m", "coverage"]:
        raise ValueError("Coverage command shape cannot be monitored")
    script = scratch / SCRIPT_NAME
    config = scratch / CONFIG_NAME
    script.write_bytes(Path(__file__).read_bytes())
    config.write_text(json.dumps({"root": str(tree), "changed_tests": changed_tests,
                                  "output": str(scratch / RECORD_NAME)}), encoding="utf-8")
    return [*coverage_argv[:3], str(script), str(config), *coverage_argv[5:]], RECORD_NAME


def assess_record(data: bytes | None, changed_tests: list[str]) -> str | None:
    """Return a named UNKNOWN reason for absent, malformed, or violating evidence."""
    if data is None or len(data) > 131_072:
        return "Test-call monitor record is missing or oversized."
    try:
        record = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        return "Test-call monitor record is unreadable."
    if (not isinstance(record, dict) or record.get("schema") != 1 or
            record.get("backend") not in {"sys.monitoring", "sys.setprofile"} or
            record.get("changed_tests") != sorted(changed_tests) or
            not isinstance(record.get("violations"), list) or
            len(record["violations"]) > MAX_VIOLATIONS or
            any(not isinstance(item, str) or not item or len(item) > 4096
                for item in record["violations"])):
        return "Test-call monitor record is invalid."
    if record["violations"]:
        return "Changed test code has an untrusted call path: " + record["violations"][0]
    if record["backend"] == "sys.setprofile":
        return "Test-call monitor fallback cannot observe all threads."
    return None


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Monitor configuration and coverage arguments are required")
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    install_monitor(root=config["root"], changed_tests=config["changed_tests"],
                    output=config["output"])
    arguments = sys.argv[2:]
    sys.path.insert(0, os.getcwd())
    sys.argv = ["coverage", *arguments]
    runpy.run_module("coverage", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
