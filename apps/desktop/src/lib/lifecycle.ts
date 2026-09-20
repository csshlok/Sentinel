import type { ChangeLifecycleState as S } from "./api/types";

// Mirror of `backend/app/core/lifecycle.py` (ALLOWED_TRANSITIONS and GUARDS). The backend stays the authority: the UI only uses this to
// offer moves that can succeed and to explain a guard up front. `lifecycle.test.ts` parses the Python file and fails if the two diverge.
export const ALLOWED_TRANSITIONS: Record<S, readonly S[]> = {
  DRAFT: ["ACTIVE", "CANCELLED"],
  ACTIVE: ["PAUSED", "LOCALLY_VERIFIED", "BLOCKED", "FAILED", "CANCELLED", "RECOVERY_PENDING"],
  PAUSED: ["ACTIVE", "BLOCKED", "FAILED", "CANCELLED"],
  LOCALLY_VERIFIED: ["ACTIVE", "REVIEW_READY", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  REVIEW_READY: ["ACTIVE", "PR_OPEN", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  PR_OPEN: ["ACTIVE", "CI_VERIFIED", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  CI_VERIFIED: ["ACTIVE", "ARTIFACT_BUILT", "STABLE", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  ARTIFACT_BUILT: ["DEPLOYED", "STABLE", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  DEPLOYED: ["OBSERVING", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  OBSERVING: ["STABLE", "BLOCKED", "FAILED", "RECOVERY_PENDING"],
  STABLE: ["ACTIVE", "RECOVERY_PENDING"],
  BLOCKED: ["ACTIVE", "FAILED", "CANCELLED", "RECOVERY_PENDING"],
  FAILED: ["ACTIVE", "CANCELLED", "RECOVERY_PENDING"],
  CANCELLED: [],
  RECOVERY_PENDING: ["RECOVERING", "CANCELLED"],
  RECOVERING: ["RECOVERED_VERIFIED", "RECOVERY_CONFLICT", "RECOVERY_FAILED"],
  RECOVERY_CONFLICT: ["RECOVERING", "RECOVERY_FAILED", "CANCELLED"],
  RECOVERY_FAILED: ["RECOVERY_PENDING", "CANCELLED"],
  RECOVERED_VERIFIED: ["ACTIVE"],
};

export const GUARDS: Partial<Record<S, readonly string[]>> = {
  ACTIVE: ["repository_valid", "contract_present", "authority_valid"],
  LOCALLY_VERIFIED: ["required_assurance_passed", "assurance_fresh"],
  REVIEW_READY: ["deviations_resolved", "required_evidence_complete"],
  PR_OPEN: ["pull_request_recorded"],
  CI_VERIFIED: ["ci_passed_for_current_head"],
  ARTIFACT_BUILT: ["artifact_recorded"],
  DEPLOYED: ["deployment_recorded"],
  OBSERVING: ["deployment_recorded"],
  STABLE: ["observation_criteria_met"],
  RECOVERING: ["recovery_plan_approved"],
  RECOVERED_VERIFIED: ["recovery_verified"],
  RECOVERY_CONFLICT: ["recovery_conflict"],
  RECOVERY_FAILED: ["recovery_failed"],
};

export const allowedTargets = (current: S | undefined): readonly S[] => ALLOWED_TRANSITIONS[current ?? "DRAFT"];

/** Plain-language requirement names for the guards the backend reports. Unknown names are shown as-is. */
const GUARD_TEXT: Record<string, string> = {
  repository_valid: "The repository is valid",
  contract_present: "A Change Contract exists",
  authority_valid: "A valid, unexpired delegation exists",
  required_assurance_passed: "Required assurance checks passed",
  assurance_fresh: "Assurance results are fresh for the current checkpoint",
  deviations_resolved: "No unresolved deviations",
  required_evidence_complete: "Required evidence is complete",
  pull_request_recorded: "A pull request outcome is recorded",
  ci_passed_for_current_head: "CI passed for the current head commit",
  artifact_recorded: "An artifact outcome is recorded",
  deployment_recorded: "A deployment outcome is recorded",
  observation_criteria_met: "Observation criteria are met",
  no_unresolved_recovery_actions: "No recovery actions are unresolved",
  recovery_plan_approved: "The recovery plan is approved",
  recovery_verified: "Recovery was verified",
  recovery_conflict: "A recovery conflict was recorded",
  recovery_failed: "A recovery failure was recorded",
};
export const guardText = (name: string) => GUARD_TEXT[name] ?? name.replace(/_/g, " ");
