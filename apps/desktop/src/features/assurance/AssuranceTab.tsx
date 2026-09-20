import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { DataTable, EmptyState, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import type { AssuranceEvaluation, AssurancePlan, AssuranceRun } from "@/lib/api/types";
import { assuranceInfo, evidenceInfo, formatRelative, formatTime, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { assuranceEvaluationQuery, assuranceFactsQuery, assurancePlanQuery, createAssurancePlan, runAssurancePlan } from "@/services/actions";
import { changeKeys } from "@/services/changes";
import { useActors } from "@/features/authority/useActors";

const isMissing = (e: unknown) => e instanceof ApiError && e.kind === "not_found";
const yesNo = (ok: boolean): { label: string; tone: "ok" | "warn" } => (ok ? { label: "Yes", tone: "ok" } : { label: "No", tone: "warn" });

export function AssuranceTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const facts = useQuery(assuranceFactsQuery(changeId));
  const plan = useQuery(assurancePlanQuery(changeId));
  const planId = plan.data?.id ?? "";
  const evaluation = useQuery(assuranceEvaluationQuery(changeId, planId));
  const { actors } = useActors(changeId);
  const [lastRun, setLastRun] = useState<AssuranceRun[]>([]);

  const create = useFormAction({ run: () => createAssurancePlan(changeId), invalidate: [[...changeKeys.all]], onSuccess: () => setLastRun([]) });

  if (facts.isPending || plan.isPending) return <Section flush><Skeleton lines={4} label="Loading assurance" /></Section>;
  if (facts.isError) return <ErrorState error={facts.error} onRetry={() => facts.refetch()} />;
  if (plan.isError && !isMissing(plan.error)) return <ErrorState error={plan.error} onRetry={() => plan.refetch()} />;

  const f = facts.data;
  const p = plan.data;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Assurance actions">
        <Button size="sm" variant={p ? "outline" : "default"} disabled={create.isPending} onClick={() => create.mutate(undefined)}>
          {create.isPending ? "Planning…" : p ? "Re-plan from latest evidence" : "Create plan"}
        </Button>
        {p ? <RunPlan changeId={changeId} plan={p} actors={actors} onDone={setLastRun} /> : null}
      </div>
      {create.isError ? <Notice tone="danger" title="The plan wasn't created" role="alert">{create.error instanceof ApiError ? create.error.message : "The request failed."}</Notice> : null}

      <Section title="What must be true" description="Four separate questions. Passing checks answer only the second.">
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          {([
            ["Required evidence is complete", f.required_evidence_complete],
            ["Required checks passed", f.required_assurance_passed],
            ["Results are fresh for the current checkpoint", f.assurance_fresh],
            ["Deviations are resolved", f.deviations_resolved],
          ] as const).map(([label, ok]) => (
            <div key={label} className="flex items-center justify-between gap-3 text-sm">
              <dt>{label}</dt>
              <dd><StatusLabel status={yesNo(Boolean(ok))} /></dd>
            </div>
          ))}
        </dl>
        {f.reasons?.length ? (
          <ul className="mt-4 list-disc space-y-1 border-t pt-3 pl-5 text-[13px] text-muted-foreground">{f.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        ) : null}
      </Section>

      {!p ? (
        <Section><EmptyState title="No assurance plan">A plan is derived from the latest captured checkpoint. Capture evidence first if none exists.</EmptyState></Section>
      ) : (
        <>
          <PlanChecks plan={p} evaluation={evaluation.data} />
          {evaluation.isPending ? null : evaluation.isError && !isMissing(evaluation.error) ? (
            <ErrorState error={evaluation.error} onRetry={() => evaluation.refetch()} />
          ) : (
            <Evaluation evaluation={evaluation.data} lastRun={lastRun} plan={p} />
          )}
        </>
      )}
      <p className="text-xs leading-5 text-muted-foreground">Passing checks are evidence for one Git state, not proof the change is correct. Checks that can't run or were skipped are shown as such rather than as passes.</p>
    </>
  );
}

function PlanChecks({ plan, evaluation }: { plan: AssurancePlan; evaluation: AssuranceEvaluation | undefined }) {
  const byCheck = new Map((evaluation?.results ?? []).map((r) => [r.check_id, r]));
  const checks = plan.checks ?? [];
  return (
    <Section title="Planned checks" description={`For checkpoint ${shortSha(plan.checkpoint_id)} · planned ${formatRelative(plan.created_at)}`} flush>
      {checks.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">The plan contains no checks. See coverage gaps below.</p>
      ) : (
        <DataTable label="Planned checks">
          <thead>
            <tr>
              <th className={th}>Check</th>
              <th className={th}>Command</th>
              <th className={th}>Required</th>
              <th className={th}>Why</th>
              <th className={th}>Latest result</th>
            </tr>
          </thead>
          <tbody>
            {checks.map((c) => {
              const r = byCheck.get(c.id);
              return (
                <tr key={c.id}>
                  <td className={cn(td, "font-medium text-[var(--text-primary)]")}>{c.name}</td>
                  <td className={cn(td, "mono break-all text-[13px]")}>{[c.executable, ...(c.args ?? [])].join(" ")}</td>
                  <td className={td}>{c.required ? "Required" : "Optional"}</td>
                  <td className={cn(td, "max-w-[28ch] text-muted-foreground")}>{c.rationale}</td>
                  <td className={td}>{r ? <StatusLabel status={assuranceInfo(r.status)} /> : <span className="text-muted-foreground">Not run</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </DataTable>
      )}
      {plan.coverage_gaps?.length ? (
        <div className="border-t px-5 py-3">
          <p className="text-[13px] font-medium">Coverage gaps</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{plan.coverage_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </div>
      ) : null}
    </Section>
  );
}

function Evaluation({ evaluation, lastRun, plan }: { evaluation: AssuranceEvaluation | undefined; lastRun: AssuranceRun[]; plan: AssurancePlan }) {
  const names = new Map((plan.checks ?? []).map((c) => [c.id, c.name]));
  if (!evaluation) {
    return <Section><EmptyState title="Not evaluated yet">Run the plan to get results. Nothing is reported as passed before it runs.</EmptyState></Section>;
  }
  return (
    <>
      <Section title="Evaluation" action={<StatusLabel status={evidenceInfo(evaluation.status)} />}>
        <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          {([
            ["Required checks passed", evaluation.required_assurance_passed],
            ["Evidence complete", evaluation.required_evidence_complete],
            ["Fresh", evaluation.fresh && evaluation.assurance_fresh],
            ["Deviations resolved", evaluation.deviations_resolved],
          ] as const).map(([label, ok]) => (
            <div key={label} className="flex items-center justify-between gap-3">
              <dt>{label}</dt>
              <dd><StatusLabel status={yesNo(Boolean(ok))} /></dd>
            </div>
          ))}
        </dl>
        <Reasons title="Failed" items={evaluation.failed?.map((id) => names.get(id) ?? id)} />
        <Reasons title="Required evidence missing" items={evaluation.missing_required} />
        <Reasons title="Why results may be stale" items={evaluation.freshness_reasons} />
        <Reasons title="Coverage gaps" items={evaluation.coverage_gaps} />
      </Section>

      {evaluation.deviations?.length ? (
        <Section title="Deviations" description="Places the change went outside its contract." flush>
          <DataTable label="Deviations">
            <thead><tr><th className={th}>Severity</th><th className={th}>Category</th><th className={th}>Subject</th><th className={th}>Detail</th></tr></thead>
            <tbody>
              {evaluation.deviations.map((d, i) => (
                <tr key={`${d.category}-${d.subject}-${i}`}>
                  <td className={td}>{String(d.severity).toLowerCase()}</td>
                  <td className={td}>{String(d.category).replace(/_/g, " ").toLowerCase()}</td>
                  <td className={cn(td, "mono break-all text-[13px]")}>{d.subject}</td>
                  <td className={cn(td, "text-muted-foreground")}>{d.detail}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Section>
      ) : null}

      <Section title="Check results" flush>
        {(evaluation.results ?? []).length === 0 ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">No results recorded.</p>
        ) : (
          <DataTable label="Check results">
            <thead><tr><th className={th}>Check</th><th className={th}>Result</th><th className={th}>Required</th><th className={th}>Exit</th><th className={th}>Summary</th></tr></thead>
            <tbody>
              {(evaluation.results ?? []).map((r) => (
                <tr key={r.check_id}>
                  <td className={td}>{names.get(r.check_id) ?? r.check_id}</td>
                  <td className={td}><StatusLabel status={assuranceInfo(r.status)} /></td>
                  <td className={td}>{r.required ? "Required" : "Optional"}</td>
                  <td className={cn(td, "tabular-nums")}>{r.exit_code ?? "—"}</td>
                  <td className={cn(td, "break-words text-muted-foreground")}>{r.summary}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>

      {lastRun.length ? (
        <Section title="Output from the last run" description="Bounded by the output limit you set. Truncation is marked." flush>
          <ul className="divide-y">
            {lastRun.map((r) => (
              <li key={r.id} className="px-5 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="font-medium">{names.get(r.check_id) ?? r.check_id}</span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground" title={formatTime(r.completed_at)}>
                    <span className="tabular-nums">{r.duration_ms} ms</span>
                    <StatusLabel status={assuranceInfo(r.status)} />
                  </span>
                </div>
                {r.stdout || r.stderr ? (
                  <details className="mt-2 rounded-md border">
                    <summary className="cursor-pointer px-3 py-1.5 text-[13px] text-muted-foreground">Output{r.output_truncated ? " (truncated)" : ""}</summary>
                    <pre className="mono max-h-64 overflow-auto whitespace-pre-wrap break-words border-t bg-secondary px-3 py-2 text-xs" tabIndex={0} aria-label="Check output">{[r.stdout, r.stderr && `--- stderr ---\n${r.stderr}`].filter(Boolean).join("\n")}</pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </>
  );
}

function Reasons({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items?.length) return null;
  return (
    <div className="mt-4 border-t pt-3">
      <p className="text-[13px] font-medium">{title}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{items.map((i) => <li key={i}>{i}</li>)}</ul>
    </div>
  );
}

function RunPlan({ changeId, plan, actors, onDone }: { changeId: string; plan: AssurancePlan; actors: ReturnType<typeof useActors>["actors"]; onDone: (runs: AssuranceRun[]) => void }) {
  const [actor, setActor] = useState("");
  const [limit, setLimit] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setActor(""); setLimit(""); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({
    run: (b: { actor_id: string; output_limit_bytes?: number }, key) => runAssurancePlan(changeId, plan.id, b, key),
    invalidate: [[...changeKeys.all]],
    onSuccess: (res) => { onDone(res.items ?? []); dlg.close(); },
  });
  const checks = plan.checks ?? [];
  const commands = checks.filter((c) => c.required).length;
  return (
    <>
      <Button size="sm" onClick={dlg.show} disabled={checks.length === 0}>Run checks</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Run the planned checks"
        description={`This executes ${checks.length} command${checks.length === 1 ? "" : "s"} (${commands} required) in the repository. They can modify files, depending on what they are.`}
        submitLabel="Run checks"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!actor) e.actor = "Choose who is running these checks.";
          if (limit.trim() && !/^[1-9]\d*$/.test(limit.trim())) e.limit = "Use a whole number of bytes.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: actor, ...(limit.trim() ? { output_limit_bytes: Number(limit) } : {}) });
        }}
      >
        <ActorPicker id="rp-actor" label="Run as" actors={actors} value={actor} onChange={setActor} error={errs.actor} />
        <Field id="rp-limit" label="Output limit in bytes (optional)" error={errs.limit} hint="Output beyond this is cut and marked truncated.">
          <Input id="rp-limit" inputMode="numeric" value={limit} onChange={(e) => setLimit(e.target.value)} aria-describedby="rp-limit-h" />
        </Field>
        <ul className="mono max-h-32 overflow-auto rounded-md border bg-secondary px-3 py-2 text-xs">
          {checks.map((c) => <li key={c.id} className="break-all">{[c.executable, ...(c.args ?? [])].join(" ")}</li>)}
        </ul>
      </FormDialog>
    </>
  );
}
