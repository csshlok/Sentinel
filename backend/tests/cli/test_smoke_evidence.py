"""Real CLI -> live server -> real Git/agent/pytest flow for the Person 2 stream."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from backend.app.cli import main as cli_main
from backend.tests.cli.test_smoke import live_api_url  # noqa: F401  (pytest fixture)
from backend.tests.support_kb import make_repo

runner = CliRunner()
FILES = {
    "pyproject.toml": '[project]\nname = "d"\ndependencies = ["flask==2.0.0"]\n'
                      "[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
    "requirements.txt": "flask==2.0.0\n",
    "app.py": "def add(a, b):\n    return a + b\n",
    "tests/test_app.py": "from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
}
EDIT = ("import pathlib\n"
        "pathlib.Path('app.py').write_text('def add(a, b):\\n    return b + a\\n')\n"
        "pathlib.Path('requirements.txt').write_text('flask==3.0.0\\n')\nprint('agent done')\n")


def call(url, *argv, expect=0):
    args = list(argv)
    cut = args.index("--") if "--" in args else len(args)     # options must precede `--`
    result = runner.invoke(cli_main.app, [*args[:cut], "--api-url", url, "--json", *args[cut:]])
    assert result.exit_code == expect, result.stdout
    return json.loads(result.stdout)


def test_person_two_flow_through_the_cli_against_a_real_server(live_api_url, tmp_path):  # noqa: F811
    repo = make_repo(tmp_path / "repo", FILES)
    change = call(live_api_url, "change", "create", "Feature", "Exercise evidence", str(repo))
    human = call(live_api_url, "actor", "create", "HUMAN", "Owner")
    agent = call(live_api_url, "actor", "create", "AGENT", "Agent")
    call(live_api_url, "delegation", "create", human["id"], agent["id"], change["id"],
         "--scope", "agent.launch", "--scope", "assurance.run")
    cid, aid = change["id"], agent["id"]

    assert call(live_api_url, "evidence", "show", cid)["baseline_captured"] is False
    assert call(live_api_url, "evidence", "baseline", cid)["checkpoint"]["name"] == "baseline"
    run = call(live_api_url, "agent", "launch", cid, aid, "python", "--timeout", "60", "--",
               "-c", EDIT)
    assert run["status"] == "PASSED", run["stderr"] + run["stdout"]
    assert run["stdout"].strip() == "agent done"
    current = call(live_api_url, "evidence", "current", cid)
    assert current["comparison"]["added_paths"] == ["app.py", "requirements.txt"]

    plan = call(live_api_url, "assurance", "plan", cid)
    assert any(check["id"] == "pytest" for check in plan["checks"])
    ran = call(live_api_url, "assurance", "run", cid, plan["id"], aid)
    assert [r["status"] for r in ran["items"] if r["check_id"] == "pytest"] == ["PASSED"]
    evaluation = call(live_api_url, "assurance", "evaluate", cid, plan["id"])
    assert evaluation["fresh"] and evaluation["required_assurance_passed"]
    assert call(live_api_url, "assurance", "facts", cid)["assurance_fresh"] is True
    assert call(live_api_url, "agent", "list", cid)["count"] == 1
    assert {a["adapter"] for a in call(live_api_url, "agent", "adapters")["items"]} == {
        "generic", "codex", "claude"}

    denied = call(live_api_url, "agent", "launch", cid, human["id"], "python", "--", "-c", "print(1)",
                  expect=1)
    assert denied["error"]["code"] == "POLICY_DENIED"
