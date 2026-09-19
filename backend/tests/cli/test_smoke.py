"""Real end-to-end CLI smoke test against a live local server, no fakes."""

from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest
import uvicorn
from typer.testing import CliRunner

from backend.app.cli import main as cli_main
from backend.app.core.config import Settings
from backend.app.main import create_app

runner = CliRunner()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def live_api_url(tmp_path):
    port = _free_port()
    app = create_app(settings=Settings(database_path=tmp_path / "cli-smoke.sqlite3"))
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    # Every non-health route now requires a bearer token. The CLI is invoked
    # in-process by CliRunner below, so exporting it into this process's
    # environment is enough for ApiClient to pick it up automatically.
    previous_token = os.environ.get("CHANGE_ASSURANCE_API_TOKEN")
    os.environ["CHANGE_ASSURANCE_API_TOKEN"] = app.state.api_token
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if previous_token is None:
            os.environ.pop("CHANGE_ASSURANCE_API_TOKEN", None)
        else:
            os.environ["CHANGE_ASSURANCE_API_TOKEN"] = previous_token


def test_capabilities_and_change_lifecycle_against_a_real_server(live_api_url, tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    import subprocess

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    (repo / "file.txt").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

    capabilities = runner.invoke(
        cli_main.app, ["capabilities", "--api-url", live_api_url, "--json"]
    )
    assert capabilities.exit_code == 0, capabilities.stdout
    assert json.loads(capabilities.stdout)["items"]

    created = runner.invoke(
        cli_main.app,
        ["change", "create", "Smoke change", "Prove the CLI works end to end", str(repo), "--api-url", live_api_url, "--json"],
    )
    assert created.exit_code == 0, created.stdout
    change = json.loads(created.stdout)

    shown = runner.invoke(
        cli_main.app, ["change", "show", change["id"], "--api-url", live_api_url, "--json"]
    )
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["id"] == change["id"]
