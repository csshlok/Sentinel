"""One operator-facing line per agent run naming the boundary it actually had (plan 02-04).

Shared by the CLI and the TUI so the two can never word it differently. The
text comes only from the run's recorded ``execution_boundary`` (observed
facts); a run without one says so rather than implying a boundary. A reduced
token is never called a sandbox, and the AppContainer line names what was
verified.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

APPCONTAINER_LABEL = "AppContainer"
REDUCED_LABEL = "reduced token only"


def boundary_line(run: Mapping[str, Any]) -> str:
    """``Boundary: ...`` for one serialized ``AgentRun``."""

    boundary = run.get("execution_boundary")
    if not isinstance(boundary, Mapping):
        return ("Boundary: not observed (the run did not start, or was recorded before "
                "boundaries were)")
    kind = boundary.get("kind")
    if kind == "APPCONTAINER":
        capabilities = ", ".join(str(item) for item in boundary.get("capabilities") or [])
        details = [f"capabilities: {capabilities or 'none'}",
                   "integrity low" if boundary.get("integrity_rid") == "0x1000"
                   else f"integrity {boundary.get('integrity_rid') or 'UNKNOWN'}",
                   "Job verified" if boundary.get("job_verified") else "Job NOT verified"]
        if boundary.get("workspace_drive"):
            details.append(f"workspace drive {boundary['workspace_drive']}")
        return f"Boundary: {APPCONTAINER_LABEL} ({'; '.join(details)})"
    if kind == "RESTRICTED_TOKEN":
        return (f"Boundary: {REDUCED_LABEL} (restricted token in a Job Object; not a sandbox, "
                "no filesystem or network restriction)")
    if kind == "NONE":
        return "Boundary: none (attached or unreduced run; no boundary was observed)"
    return f"Boundary: UNKNOWN ({kind!r})"


def boundary_lines(result: Any) -> list[str]:
    """Boundary lines for a CLI result: one run, a list of runs, or nothing."""

    if isinstance(result, Mapping) and "status" in result and "adapter" in result:
        return [boundary_line(result)]
    items = result.get("items") if isinstance(result, Mapping) else result
    if isinstance(items, list):
        return [f"{item.get('id')}: {boundary_line(item)}" for item in items
                if isinstance(item, Mapping) and "adapter" in item]
    return []
