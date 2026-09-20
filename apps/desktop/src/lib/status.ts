import type {
  AgentRunStatus,
  AssuranceStatus,
  ChangeLifecycleState,
  Delegation,
  EvidenceStatus,
  OutcomeStatus,
  RecoveryStatus,
  ReviewState,
  RiskLevel,
  ToolSignatureState,
  ToolTrustState,
} from "./api/types";

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";
export interface StatusInfo {
  label: string;
  tone: Tone;
}

const LIFECYCLE: Record<ChangeLifecycleState, StatusInfo> = {
  DRAFT: { label: "Draft", tone: "neutral" },
  ACTIVE: { label: "Active", tone: "info" },
  PAUSED: { label: "Paused", tone: "warn" },
  LOCALLY_VERIFIED: { label: "Locally verified", tone: "ok" },
  REVIEW_READY: { label: "Review ready", tone: "ok" },
  PR_OPEN: { label: "PR open", tone: "info" },
  CI_VERIFIED: { label: "CI verified", tone: "ok" },
  ARTIFACT_BUILT: { label: "Artifact built", tone: "ok" },
  DEPLOYED: { label: "Deployed", tone: "info" },
  OBSERVING: { label: "Observing", tone: "info" },
  STABLE: { label: "Stable", tone: "ok" },
  BLOCKED: { label: "Blocked", tone: "danger" },
  FAILED: { label: "Failed", tone: "danger" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
  RECOVERY_PENDING: { label: "Recovery pending", tone: "warn" },
  RECOVERING: { label: "Recovering", tone: "warn" },
  RECOVERED_VERIFIED: { label: "Recovered, verified", tone: "ok" },
  RECOVERY_CONFLICT: { label: "Recovery conflict", tone: "danger" },
  RECOVERY_FAILED: { label: "Recovery failed", tone: "danger" },
};

/** Forward path shown as the lifecycle rail. Other states are shown as an off-path banner. */
export const LIFECYCLE_PATH: ChangeLifecycleState[] = [
  "DRAFT",
  "ACTIVE",
  "LOCALLY_VERIFIED",
  "REVIEW_READY",
  "PR_OPEN",
  "CI_VERIFIED",
  "ARTIFACT_BUILT",
  "DEPLOYED",
  "OBSERVING",
  "STABLE",
];

const unknown = (value: string): StatusInfo => ({ label: value.replace(/_/g, " ").toLowerCase(), tone: "neutral" });

export const lifecycleInfo = (state: ChangeLifecycleState | undefined): StatusInfo =>
  LIFECYCLE[state ?? "DRAFT"] ?? unknown(String(state));

const REVIEW: Record<ReviewState, StatusInfo> = {
  NO_CHANGES: { label: "No changes", tone: "neutral" },
  MISSING_EVIDENCE: { label: "Evidence missing", tone: "warn" },
  FAILED_VERIFICATION: { label: "Verification failed", tone: "danger" },
  READY_FOR_HUMAN_REVIEW: { label: "Ready for human review", tone: "ok" },
};
export const reviewInfo = (state: ReviewState): StatusInfo => REVIEW[state] ?? unknown(String(state));

const RISK: Record<RiskLevel, StatusInfo> = {
  UNKNOWN: { label: "Risk unknown", tone: "neutral" },
  LOW: { label: "Low risk", tone: "ok" },
  MEDIUM: { label: "Medium risk", tone: "warn" },
  HIGH: { label: "High risk", tone: "danger" },
  CRITICAL: { label: "Critical risk", tone: "danger" },
};
export const riskInfo = (level: RiskLevel | undefined): StatusInfo => RISK[level ?? "UNKNOWN"] ?? unknown(String(level));

const TRUST: Record<ToolTrustState, StatusInfo> = {
  UNKNOWN: { label: "Unknown", tone: "neutral" },
  OBSERVED: { label: "Observed", tone: "info" },
  PROVISIONAL: { label: "Provisional", tone: "warn" },
  APPROVED: { label: "Approved", tone: "ok" },
  DENIED: { label: "Denied", tone: "danger" },
};
export const trustInfo = (state: ToolTrustState): StatusInfo => TRUST[state] ?? unknown(String(state));

const SIGNATURE: Record<ToolSignatureState, StatusInfo> = {
  valid: { label: "Signature valid", tone: "ok" },
  invalid: { label: "Signature invalid", tone: "danger" },
  unsigned: { label: "Unsigned", tone: "warn" },
  unknown: { label: "Signature unknown", tone: "neutral" },
};
export const signatureInfo = (state: ToolSignatureState): StatusInfo => SIGNATURE[state] ?? unknown(String(state));

export const shortSha = (sha: string | null | undefined) => (sha ? sha.slice(0, 8) : "—");
export const repoName = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? path;
export const formatTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31_536_000],
  ["month", 2_592_000],
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "2 hours ago"; falls back to "just now" under a minute. Pair with `formatTime` in a title for the exact time. */
export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  for (const [unit, size] of UNITS) {
    if (abs >= size) return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(Math.round(seconds / size), unit);
  }
  return "just now";
}

const AGENT_RUN: Record<AgentRunStatus, StatusInfo> = {
  ATTACHED: { label: "Attached", tone: "info" },
  RUNNING: { label: "Running", tone: "info" },
  PAUSED: { label: "Paused", tone: "warn" },
  PASSED: { label: "Exited cleanly", tone: "ok" },
  FAILED: { label: "Failed", tone: "danger" },
  TIMED_OUT: { label: "Timed out", tone: "danger" },
  CANCELLED: { label: "Stopped", tone: "neutral" },
  ERROR: { label: "Error", tone: "danger" },
};
export const agentRunInfo = (s: AgentRunStatus): StatusInfo => AGENT_RUN[s] ?? unknown(String(s));

const ASSURANCE: Record<AssuranceStatus, StatusInfo> = {
  PENDING: { label: "Pending", tone: "neutral" },
  RUNNING: { label: "Running", tone: "info" },
  PASSED: { label: "Passed", tone: "ok" },
  FAILED: { label: "Failed", tone: "danger" },
  TIMED_OUT: { label: "Timed out", tone: "danger" },
  ERROR: { label: "Error", tone: "danger" },
  SKIPPED: { label: "Skipped", tone: "warn" },
};
export const assuranceInfo = (s: AssuranceStatus): StatusInfo => ASSURANCE[s] ?? unknown(String(s));

const EVIDENCE: Record<EvidenceStatus, StatusInfo> = {
  CURRENT: { label: "Current", tone: "ok" },
  STALE: { label: "Stale", tone: "warn" },
  MISSING: { label: "Missing", tone: "danger" },
  UNSUPPORTED: { label: "Unsupported", tone: "neutral" },
  PARTIAL: { label: "Partial", tone: "warn" },
};
export const evidenceInfo = (s: EvidenceStatus): StatusInfo => EVIDENCE[s] ?? unknown(String(s));

const OUTCOME: Record<OutcomeStatus, StatusInfo> = {
  UNKNOWN: { label: "Unknown", tone: "neutral" },
  PENDING: { label: "Pending", tone: "info" },
  PASSED: { label: "Passed", tone: "ok" },
  FAILED: { label: "Failed", tone: "danger" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
  UNAVAILABLE: { label: "Unavailable", tone: "warn" },
};
export const outcomeInfo = (s: OutcomeStatus): StatusInfo => OUTCOME[s] ?? unknown(String(s));

const RECOVERY: Record<RecoveryStatus, StatusInfo> = {
  PLANNED: { label: "Planned, not applied", tone: "info" },
  APPROVED: { label: "Approved", tone: "info" },
  EXECUTING: { label: "Executing", tone: "warn" },
  RECOVERED: { label: "Recovered", tone: "ok" },
  PARTIAL: { label: "Partially recovered", tone: "warn" },
  RECOVERY_FAILED: { label: "Recovery failed", tone: "danger" },
  CONFLICTED: { label: "Conflict", tone: "danger" },
};
export const recoveryInfo = (s: RecoveryStatus): StatusInfo => RECOVERY[s] ?? unknown(String(s));

/** Revoked, expired and exhausted are different reasons a delegation stops working, so they are kept distinct. */
export function delegationInfo(d: Pick<Delegation, "revoked_at" | "expires_at" | "use_limit" | "uses">, now = Date.now()): StatusInfo {
  if (d.revoked_at) return { label: "Revoked", tone: "danger" };
  if (new Date(d.expires_at).getTime() <= now) return { label: "Expired", tone: "warn" };
  if (d.use_limit != null && d.uses >= d.use_limit) return { label: "Exhausted", tone: "warn" };
  return { label: "Active", tone: "ok" };
}
