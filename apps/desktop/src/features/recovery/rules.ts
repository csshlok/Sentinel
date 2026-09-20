import type { RecoveryPlan } from "../../lib/api/types";
import { recoveryInfo } from "../../lib/status.ts";

export interface Executability {
  ok: boolean;
  /** Why execution isn't offered. Empty when `ok`. */
  reasons: string[];
}

/**
 * Whether a previewed plan may be executed from here. The backend re-checks everything; this only avoids offering a button that can't work.
 * A plan is stale when the repository HEAD no longer equals the commit the plan was computed against.
 */
export function canExecute(plan: RecoveryPlan, headSha: string | null | undefined, recoveryAllowed: boolean): Executability {
  const reasons: string[] = [];
  if (plan.status !== "PLANNED") reasons.push(`This plan is ${recoveryInfo(plan.status).label.toLowerCase()}; only a planned, unapplied preview can be executed.`);
  if ((plan.conflicts ?? []).length) reasons.push("The plan reports conflicts. Resolve them and preview again.");
  const actions = plan.actions ?? [];
  if (actions.length && !actions[0]!.supported) reasons.push("The planned action isn't supported, so nothing can be executed.");
  const planned = actions[0]?.reversible_commit;
  if (planned && headSha && planned.toLowerCase() !== headSha.toLowerCase()) reasons.push("The repository HEAD moved since this preview. Preview again before executing.");
  if (!recoveryAllowed) reasons.push("The Change Contract doesn't allow recovery.");
  return { ok: reasons.length === 0, reasons };
}

/** The approval an operator types is the plan's short id, so an approval can't be pasted from a different plan. */
export const approvalPhrase = (plan: Pick<RecoveryPlan, "id">) => plan.id.slice(0, 8);
