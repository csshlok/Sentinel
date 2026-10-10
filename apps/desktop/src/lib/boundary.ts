import type { AgentRun, CheckRunView, ExecutionBoundary, WorkspaceState } from "./api/types";
import type { StatusInfo } from "./status";

/**
 * The boundary an agent run actually had, worded exactly as the CLI and TUI word it (`backend/app/core/boundary_text.py`;
 * `boundary.test.ts` fails if the two drift). Only the run's recorded `execution_boundary` (observed facts) is used: a run without
 * one says so, a reduced token is never called a sandbox, and the AppContainer line names what was verified.
 */
export const APPCONTAINER_LABEL = "AppContainer";
export const REDUCED_LABEL = "reduced token only";
export const NOT_OBSERVED = "Boundary: not observed (the run did not start, or was recorded before boundaries were)";
export const REDUCED_LINE = `Boundary: ${REDUCED_LABEL} (restricted token in a Job Object; not a sandbox, no filesystem or network restriction)`;
export const NONE_LINE = "Boundary: none (attached or unreduced run; no boundary was observed)";

export function boundaryLine(run: Pick<AgentRun, "execution_boundary">): string {
  const boundary = run.execution_boundary as ExecutionBoundary | null | undefined;
  // Python checks for a Mapping: an array or any non-object is "not observed" there too.
  if (!boundary || typeof boundary !== "object" || Array.isArray(boundary)) return NOT_OBSERVED;
  if (boundary.kind === "APPCONTAINER") {
    const capabilities = (boundary.capabilities ?? []).join(", ");
    const details = [
      `capabilities: ${capabilities || "none"}`,
      boundary.integrity_rid === "0x1000" ? "integrity low" : `integrity ${boundary.integrity_rid || "UNKNOWN"}`,
      boundary.job_verified ? "Job verified" : "Job NOT verified",
    ];
    if (boundary.workspace_drive) details.push(`workspace drive ${boundary.workspace_drive}`);
    return `Boundary: ${APPCONTAINER_LABEL} (${details.join("; ")})`;
  }
  if (boundary.kind === "RESTRICTED_TOKEN") return REDUCED_LINE;
  if (boundary.kind === "NONE") return NONE_LINE;
  // Python's repr(): a string kind is quoted, a missing kind is None.
  const kind = (boundary as { kind?: unknown }).kind;
  return `Boundary: UNKNOWN (${typeof kind === "string" ? `'${kind}'` : "None"})`;
}

/** Tone for the boundary badge: only a verified AppContainer is "ok"; a reduced token is a warning, anything else is danger. */
export function boundaryStatus(run: Pick<AgentRun, "execution_boundary">): StatusInfo {
  const kind = (run.execution_boundary as ExecutionBoundary | null | undefined)?.kind;
  if (kind === "APPCONTAINER") {
    const verified = (run.execution_boundary as ExecutionBoundary).job_verified;
    return verified ? { label: APPCONTAINER_LABEL, tone: "ok" } : { label: `${APPCONTAINER_LABEL}, Job not verified`, tone: "warn" };
  }
  if (kind === "RESTRICTED_TOKEN") return { label: "Reduced token only", tone: "warn" };
  if (kind === "NONE") return { label: "No boundary", tone: "danger" };
  return { label: "Boundary not observed", tone: "neutral" };
}

/** A check run's observed boundary (APPCONTAINER only for a verified box, UNCONFINED for a delegated opt-in run). */
export function checkBoundaryStatus(run: Pick<CheckRunView, "boundary">): StatusInfo {
  if (run.boundary === "APPCONTAINER") return { label: "Confined (AppContainer)", tone: "ok" };
  if (run.boundary === "UNCONFINED") return { label: "Unconfined (opt-in)", tone: "danger" };
  return { label: "No verified run", tone: "neutral" };
}

const WORKSPACE: Record<WorkspaceState, StatusInfo> = {
  CREATING: { label: "Creating", tone: "info" },
  READY: { label: "Ready", tone: "info" },
  SEALED: { label: "Sealed for review", tone: "warn" },
  APPLIED: { label: "Applied", tone: "ok" },
  APPLY_REFUSED: { label: "Apply refused", tone: "danger" },
  DISCARDED: { label: "Discarded", tone: "neutral" },
  CLEANED: { label: "Cleaned", tone: "neutral" },
  CLEANUP_FAILED: { label: "Cleanup failed", tone: "danger" },
};
export const workspaceInfo = (state: WorkspaceState): StatusInfo => WORKSPACE[state] ?? { label: state, tone: "neutral" };

/** Short form of a commit id for display. */
export const shortSha = (sha: string | null | undefined): string => (sha ? sha.slice(0, 12) : "—");
