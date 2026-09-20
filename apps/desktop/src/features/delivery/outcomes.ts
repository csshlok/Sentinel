import type { Outcome } from "@/lib/api/types";

export interface OutcomeGroup {
  kind: Outcome["kind"];
  latest: Outcome;
  earlier: Outcome[];
  /** The newest observation is for a different commit than the Change's current HEAD, so it says nothing about the current state. */
  stale: boolean;
  /** A newer non-passing observation exists behind an older pass, which is the case the UI must not hide. */
  supersedesPass: boolean;
}

/**
 * Groups outcomes by kind, newest observation first. The latest observation is what represents the kind: an older pass never outranks a
 * newer pending or failing one. Each group is also compared with the Change's current HEAD so a pass for an old commit isn't shown as current.
 */
export function groupOutcomes(outcomes: readonly Outcome[], headSha: string | null | undefined): OutcomeGroup[] {
  const byKind = new Map<Outcome["kind"], Outcome[]>();
  for (const o of outcomes) byKind.set(o.kind, [...(byKind.get(o.kind) ?? []), o]);
  const groups: OutcomeGroup[] = [];
  for (const [kind, list] of byKind) {
    const sorted = [...list].sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at));
    const [latest, ...earlier] = sorted as [Outcome, ...Outcome[]];
    groups.push({
      kind,
      latest,
      earlier,
      stale: Boolean(headSha) && latest.head_sha !== headSha,
      supersedesPass: latest.status !== "PASSED" && earlier.some((o) => o.status === "PASSED"),
    });
  }
  return groups.sort((a, b) => a.kind.localeCompare(b.kind));
}

export const KIND_LABEL: Record<Outcome["kind"], string> = {
  PULL_REQUEST: "Pull request",
  CI: "CI",
  ARTIFACT: "Artifact",
  DEPLOYMENT: "Deployment",
};
