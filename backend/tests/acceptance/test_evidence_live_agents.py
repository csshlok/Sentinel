"""In-flight agent runs are visible and stoppable from a different request."""

from __future__ import annotations

import threading
import time

from backend.tests.acceptance.test_evidence_routes import FILES, build, setup_change
from backend.tests.support_kb import make_repo


def test_a_running_agent_is_listed_and_can_be_stopped_by_another_request(tmp_path):
    repo = make_repo(tmp_path / "repo", FILES)
    client = build(tmp_path)
    change, agent, _ = setup_change(client, repo, ["agent.launch", "agent.stop"])
    base = f"/api/v1/changes/{change['id']}"
    results: dict[str, object] = {}

    def launch() -> None:
        results["launch"] = client.post(f"{base}/agents/launch", json={
            "actor_id": agent, "launch": {"adapter": "generic", "executable": "python",
                                           "args": ["-c", "import time; time.sleep(60)"],
                                           "timeout_seconds": 120}})

    thread = threading.Thread(target=launch)
    thread.start()
    running = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and running is None:
        items = client.get(f"{base}/agents").json()["items"]
        running = next((r for r in items if r["status"] == "RUNNING" and r["top_level_pid"]), None)
        time.sleep(0.1)
    assert running is not None, "the in-flight run was never visible"
    assert running["descendant_control_available"] is False

    stopped = client.post(f"{base}/agents/{running['id']}/stop", json={"actor_id": agent})
    thread.join(20)
    assert stopped.status_code == 200 and stopped.json()["status"] == "CANCELLED"
    finished = results["launch"]
    assert finished.status_code == 201 and finished.json()["status"] == "CANCELLED"
    assert any("direct child only" in item for item in finished.json()["limitations"])
    final = client.get(f"{base}/agents").json()
    assert final["count"] == 1 and final["items"][0]["status"] == "CANCELLED"
    # Stopping again is a harmless read of the final record.
    again = client.post(f"{base}/agents/{running['id']}/stop", json={"actor_id": agent})
    assert again.status_code == 200 and again.json()["status"] == "CANCELLED"
