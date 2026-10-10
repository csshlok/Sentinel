"""Spike 008: does the native codex.exe run inside a Sentinel workspace AppContainer?

Usage: python .planning/spikes/008-codex-in-box/spike.py <step> [prompt]
  version  -> codex --version                         (no model call)
  login    -> codex login status                      (no model call)
  exec     -> codex exec ... "<prompt>"               (ONE small model call)
Uses only sentinel.test.* profiles (swept at the end) and a throwaway repo.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.app.contracts.models import AgentLaunchRequest  # noqa: E402
from backend.app.core.database import Database  # noqa: E402
from backend.app.credentials.broker import CredentialBroker  # noqa: E402
from backend.app.credentials.memory_store import InMemoryCredentialStore  # noqa: E402
from backend.app.execution.agent_profiles import BoundaryKind, RuntimeProfile  # noqa: E402
from backend.app.execution.launcher import AgentAdapter, AgentLauncher  # noqa: E402
from backend.app.workspace.manager import WorkspaceManager  # noqa: E402
from backend.tests.support_kb import make_repo  # noqa: E402
from backend.tests.workspace.conftest import delete_test_profiles, teardown_workspaces  # noqa: E402

VENDOR = Path(os.environ["APPDATA"]) / "npm" / "node_modules" / "@openai" / "codex" / "node_modules" \
    / "@openai" / "codex-win32-x64" / "vendor" / "x86_64-pc-windows-msvc"

ARGS = {
    "version": ["--version"],
    "login": ["login", "status"],
    "exec": ["exec", "--skip-git-repo-check", "--sandbox", "danger-full-access",
             "--color", "never"],
}


def main() -> None:
    step = sys.argv[1]
    args = list(ARGS[step])
    if step == "exec":
        args.append(sys.argv[2] if len(sys.argv) > 2 else
                    "Create a file named hello.txt containing exactly: boxed. Do nothing else.")
    os.environ["PATH"] = os.pathsep.join([str(VENDOR / "codex"), str(VENDOR / "path"),
                                          os.environ["PATH"]])
    work = Path(tempfile.mkdtemp(prefix="spike008-"))
    database = Database(work / "db.sqlite3")
    database.initialize()
    manager = WorkspaceManager(database, profile_prefix="sentinel.test.")
    repo = make_repo(work / "repo", {"README.md": "spike\n"})
    profile = RuntimeProfile(
        "codex-spike", BoundaryKind.APPCONTAINER, capabilities=("internetClient",),
        tool_snapshot=True, staged_home=True, credential_kind="codex-auth-file",
        static_env=(("GIT_CONFIG_NOSYSTEM", "1"), ("GIT_TERMINAL_PROMPT", "0")),
        requires_native_executable=True, workspace_drive=True,
        home_env=(("CODEX_HOME", ".codex"),),
    )
    launcher = AgentLauncher(
        adapters={"codex-spike": AgentAdapter("codex-spike", frozenset({"codex"}))},
        profiles={"codex-spike": profile}, workspaces=manager,
        credentials=CredentialBroker(InMemoryCredentialStore()),
    )
    change_id = uuid4()
    try:
        run = launcher.launch(change_id, str(repo), AgentLaunchRequest(
            adapter="codex-spike", executable="codex.exe", args=args, timeout_seconds=240), 65_536)
        print("STATUS", run.status, "EXIT", run.exit_code)
        print("BOUNDARY", run.execution_boundary)
        print("STDOUT", run.stdout[-3000:])
        print("STDERR", run.stderr[-3000:])
        for line in run.limitations:
            print("LIMITATION", line)
        record = manager.live_for_change(change_id)
        if record is not None and step == "exec":
            hello = Path(record.workspace_path) / "hello.txt"
            print("HELLO", hello.read_text(encoding="utf-8") if hello.exists() else "<missing>")
    finally:
        teardown_workspaces(manager)
        delete_test_profiles()


if __name__ == "__main__":
    main()
