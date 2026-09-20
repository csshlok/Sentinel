import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { DataTable, EmptyState, Facts, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useActors } from "@/features/authority/useActors";
import { ApiError } from "@/lib/api/client";
import type { ChangeView, RecoveryPlan } from "@/lib/api/types";
import { formatRelative, formatTime, lifecycleInfo, recoveryInfo, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { executeRecovery, previewRecovery, recoveryQuery } from "@/services/actions";
import { changeDetailQuery, changeKeys } from "@/services/changes";
import { approvalPhrase, canExecute } from "./rules";

export function RecoveryTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const change = useQuery(changeDetailQuery(changeId));
  const plan = useQuery(recoveryQuery(changeId));
  const { actors } = useActors(changeId);
  const preview = useFormAction({ run: () => previewRecovery(changeId), invalidate: [[...changeKeys.all]] });

  if (plan.isPending || change.isPending) return <Section flush><Skeleton lines={3} label="Loading recovery" /></Section>;
  if (change.isError) return <ErrorState error={change.error} onRetry={() => change.refetch()} />;
  const missing = plan.isError && plan.error instanceof ApiError && plan.error.kind === "not_found";
  if (plan.isError && !missing) return <ErrorState error={plan.error} onRetry={() => plan.refetch()} />;

  const c = change.data;
  const p = plan.data;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Recovery actions">
        <Button size="sm" variant={p ? "outline" : "default"} disabled={preview.isPending} onClick={() => preview.mutate(undefined)}>
          {preview.isPending ? "Previewing…" : p ? "Preview again" : "Preview recovery"}
        </Button>
        {p ? <ExecuteRecovery change={c} plan={p} actors={actors} /> : null}
      </div>
      {preview.isError ? <Notice tone="danger" title="Preview failed" role="alert">{preview.error instanceof ApiError ? preview.error.message : "The request failed."}</Notice> : null}

      {!p ? (
        <Section><EmptyState title="No recovery plan">A preview computes what recovery would do on a dedicated branch. Nothing changes until you approve and execute it.</EmptyState></Section>
      ) : (
        <PlanView plan={p} change={c} />
      )}
      <p className="text-xs leading-5 text-muted-foreground">Recovery is limited to reverting Git commits on a dedicated branch and provider actions the plan lists. There is no general undo, and files the runtime never recorded can't be restored.</p>
    </>
  );
}

function PlanView({ plan, change }: { plan: RecoveryPlan; change: ChangeView }) {
  const info = recoveryInfo(plan.status);
  const actions = plan.actions ?? [];
  const verified = change.lifecycle_state === "RECOVERED_VERIFIED";
  const exec = canExecute(plan, change.git_summary?.head_sha, Boolean(change.contract?.recovery_allowed));
  return (
    <>
      <Section title="Recovery plan" action={<StatusLabel status={info} />}>
        <Facts
          items={[
            { label: "Plan", value: <code>{approvalPhrase(plan)}</code> },
            { label: "Previewed", value: <span title={formatTime(plan.created_at)}>{formatRelative(plan.created_at)}</span> },
            { label: "From checkpoint", value: <code title={plan.source_checkpoint_id}>{shortSha(plan.source_checkpoint_id)}</code> },
            ...(plan.approved_at ? [{ label: "Approved", value: formatTime(plan.approved_at) }] : []),
            ...(plan.completed_at ? [{ label: "Completed", value: formatTime(plan.completed_at) }] : []),
            { label: "Verified afterwards", value: verified ? "Yes, the Change is Recovered, verified" : `No (${lifecycleInfo(change.lifecycle_state).label})` },
          ]}
        />
        <p className="mt-3 text-[13px] text-muted-foreground">“Recovered” means the Git action was applied. It is a separate step from the Change being verified afterwards.</p>
      </Section>

      {!exec.ok && plan.status === "PLANNED" ? (
        <Notice tone="warn" title="This plan can't be executed as it stands">
          <ul className="list-disc pl-5">{exec.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </Notice>
      ) : null}

      <Section title="Planned actions" flush>
        {actions.length === 0 ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">The plan contains no actions. There is nothing to undo.</p>
        ) : (
          <DataTable label="Planned recovery actions">
            <thead><tr><th className={th}>Action</th><th className={th}>What it does</th><th className={th}>Supported</th><th className={th}>Commit</th><th className={th}>Limits</th></tr></thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a.id}>
                  <td className={cn(td, "font-medium")}>{a.kind.replace(/_/g, " ").toLowerCase()}</td>
                  <td className={cn(td, "break-words")}>{a.description}</td>
                  <td className={td}><StatusLabel status={a.supported ? { label: "Supported", tone: "ok" } : { label: "Not supported", tone: "danger" }} /></td>
                  <td className={cn(td, "mono")}>{shortSha(a.reversible_commit)}</td>
                  <td className={cn(td, "text-muted-foreground")}>{a.limitations?.length ? a.limitations.join(" ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>

      <List title="Conflicts" tone="danger" items={plan.conflicts} />
      <List title="Effects recovery can't undo" tone="warn" items={plan.unsupported_effects} />
    </>
  );
}

function List({ title, items, tone }: { title: string; items: string[] | undefined; tone: "danger" | "warn" }) {
  if (!items?.length) return null;
  return (
    <Notice tone={tone} title={title}>
      <ul className="list-disc pl-5">{items.map((i) => <li key={i} className="break-words">{i}</li>)}</ul>
    </Notice>
  );
}

function ExecuteRecovery({ change, plan, actors }: { change: ChangeView; plan: RecoveryPlan; actors: ReturnType<typeof useActors>["actors"] }) {
  const [actor, setActor] = useState("");
  const [typed, setTyped] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const exec = canExecute(plan, change.git_summary?.head_sha, Boolean(change.contract?.recovery_allowed));
  const phrase = approvalPhrase(plan);
  const dlg = useDialogState(() => { setActor(""); setTyped(""); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({
    run: (b: { actor_id: string; approval_token: string }, key) => executeRecovery(change.id, plan.id, b, key),
    invalidate: [[...changeKeys.all]],
    onSuccess: () => dlg.close(),
  });
  return (
    <>
      <Button size="sm" variant="destructive" disabled={!exec.ok} title={exec.ok ? undefined : exec.reasons[0]} onClick={dlg.show}>Execute recovery…</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Execute this recovery plan?"
        description="This applies the previewed actions on a dedicated recovery branch. It won't touch your current branch, but it can't be undone from here."
        submitLabel="Execute recovery"
        danger
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!actor) e.actor = "Choose who is approving this.";
          if (typed.trim() !== phrase) e.typed = `Type ${phrase} to approve this exact plan.`;
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: actor, approval_token: typed.trim() });
        }}
      >
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {(plan.actions ?? []).map((a) => <li key={a.id} className="break-words">{a.description}</li>)}
        </ul>
        <ActorPicker id="ex-actor" label="Approved by" actors={actors} value={actor} onChange={setActor} error={errs.actor} />
        <Field id="ex-typed" label={`Type ${phrase} to approve`} error={errs.typed} hint="This ties your approval to the plan shown here.">
          <Input id="ex-typed" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} className="mono" aria-describedby="ex-typed-h" />
        </Field>
      </FormDialog>
    </>
  );
}
