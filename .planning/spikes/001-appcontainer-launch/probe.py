"""Spike 001: documented AppContainer launch + Job Object before resume, with a control run."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "a0_lib"))
import acbox  # noqa: E402

PROFILE = "sentinel.a0.spike001"
SYSTEM32 = os.path.join(os.environ["SystemRoot"], "System32")
results: dict[str, object] = {}

sid, created = acbox.ensure_profile(PROFILE, ("internetClient",))
results["profile"] = {"name": PROFILE, "created": created, "sid": acbox.sid_to_string(sid),
                      "folder": acbox.container_folder(sid)}

control = acbox.run(r'cmd.exe /d /c echo control-ran', cwd=SYSTEM32, sid=None)
results["control"] = {"exit": control.exit_code, "out": control.output.strip(), "token": control.token,
                      "job_pids_before_resume": control.job_pids_before_resume, "pid": control.child_pid}

boxed = acbox.run(r'cmd.exe /d /c echo boxed-ran', cwd=SYSTEM32, sid=sid, capabilities=("internetClient",))
results["boxed"] = {"exit": boxed.exit_code, "out": boxed.output.strip(), "token": boxed.token,
                    "job_pids_before_resume": boxed.job_pids_before_resume, "pid": boxed.child_pid}

# Zero-capability container also launches (capabilities are optional at the API level).
bare = acbox.run(r'cmd.exe /d /c echo bare-ran', cwd=SYSTEM32, sid=sid)
results["zero_capability"] = {"exit": bare.exit_code, "out": bare.output.strip(), "token": bare.token}

checks = {
    "control_not_appcontainer": control.token["is_appcontainer"] is False,
    "boxed_is_appcontainer": boxed.token["is_appcontainer"] is True,
    "boxed_package_sid_matches_profile": boxed.token["package_sid"] == results["profile"]["sid"],
    "boxed_low_integrity": boxed.token["integrity_rid"] == "0x1000",
    "boxed_in_job_before_resume": boxed.child_pid in boxed.job_pids_before_resume,
    "boxed_ran": boxed.exit_code == 0 and "boxed-ran" in boxed.output,
}
results["checks"] = checks
print(json.dumps(results, indent=2))
sys.exit(0 if all(checks.values()) else 1)
