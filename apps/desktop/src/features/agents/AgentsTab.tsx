import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, Select, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { EmptyState, Facts, Notice, Section, Skeleton, StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AgentAdapterInfo, AgentRun } from "@/lib/api/types";
import { agentRunInfo, formatRelative, formatTime } from "@/lib/status";
import { adaptersQuery, agentsQuery, attachAgent, isActiveRun, launchAgent, pauseAgent, resumeAgent, stopAgent } from "@/services/actions";
import { changeKeys } from "@/services/changes";
import { useActors } from "@/features/authority/useActors";

/** Splits an argument string the way a shell would for simple cases: whitespace-separated, double or single quotes group words. */
export function splitArgs(raw: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  for (let m = re.exec(raw); m; m = re.exec(raw)) out.push(m[1] ?? m[2] ?? m[3] ?? "");
  return out;
}

export function AgentsTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const runs = useQuery(agentsQuery(changeId));
  const adapters = useQuery(adaptersQuery());
  const { actors } = useActors(changeId);

  if (runs.isPending) return <Section flush><Skeleton lines={3} label="Loading agent runs" /></Section>;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;
  const items = runs.data.items ?? [];

  return (
    <>
      <div className="flex flex-wrap gap-2" role="toolbar" aria-label="Agent actions">
        <LaunchAgent changeId={changeId} actors={actors} adapters={adapters.data?.items ?? []} />
        <AttachAgent changeId={changeId} actors={actors} adapters={adapters.data?.items ?? []} />
      </div>

      {adapters.isError ? <Notice tone="warn" title="Adapter list unavailable">Launch and attach need an adapter name. Try again once the runtime responds.</Notice> : null}

      {items.length === 0 ? (
        <Section><EmptyState title="No agent runs">No top-level agent has been launched or attached for this Change.</EmptyState></Section>
      ) : (
        items.map((run) => <RunCard key={run.id} run={run} changeId={changeId} actors={actors} />)
      )}

      <Section title="Adapters" description="Which agent executables the runtime found on this computer.">
        {adapters.isPending ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (adapters.data?.items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">No adapters are configured.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {(adapters.data?.items ?? []).map((a) => (
              <li key={a.adapter} className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium">{a.adapter}</span>
                <span className="text-muted-foreground">
                  {Object.entries(a.executables).map(([name, found]) => `${name}: ${found ? "found" : "not found"}`).join(" · ") || "no executables listed"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <p className="text-xs leading-5 text-muted-foreground">The runtime records the top-level run only. It doesn't observe descendant processes, file writes, or an agent's internal tool calls, and stopping a run doesn't stop its descendants.</p>
    </>
  );
}

type RunAction = "pause" | "resume" | "stop";
const RUN_ACTIONS: Record<RunAction, { button: string; title: string; description: string; confirm: string; danger: boolean; run: typeof stopAgent }> = {
  pause: { button: "Pause", title: "Pause this top-level run?", description: "The runtime suspends the top-level process it started. Processes that one spawned aren't tracked, so they may keep running.", confirm: "Pause run", danger: false, run: pauseAgent },
  resume: { button: "Resume", title: "Resume this top-level run?", description: "The runtime resumes the top-level process it suspended.", confirm: "Resume run", danger: false, run: resumeAgent },
  stop: { button: "Stop", title: "Stop this top-level run?", description: "The runtime asks the run it started to stop. Processes it spawned are not tracked and may keep running.", confirm: "Stop run", danger: true, run: stopAgent },
};

/** One control for pause, resume and stop: choose the acting actor, confirm the consequence, and reconcile from the server afterwards. */
function RunControl({ kind, run, changeId, actors }: { kind: RunAction; run: AgentRun; changeId: string; actors: ReturnType<typeof useActors>["actors"] }) {
  const spec = RUN_ACTIONS[kind];
  const [open, setOpen] = useState(false);
  const [actor, setActor] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = useFormAction({ run: () => spec.run(changeId, run.id, actor), invalidate: [[...changeKeys.all]], onSuccess: () => setOpen(false) });
  return (
    <>
      <Button size="sm" variant="outline" className={spec.danger ? "text-danger" : undefined} onClick={() => { act.reset(); setActor(""); setErr(null); setOpen(true); }}>{spec.button}</Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={spec.title}
        description={spec.description}
        confirmLabel={spec.confirm}
        danger={spec.danger}
        pending={act.isPending}
        error={act.error}
        onConfirm={() => (actor ? (setErr(null), act.mutate(undefined)) : setErr(`Choose the actor who is doing this.`))}
      >
        <ActorPicker id={`${kind}-actor-${run.id}`} label="Acting as" actors={actors} value={actor} onChange={setActor} error={err} />
      </ConfirmDialog>
    </>
  );
}

function RunCard({ run, changeId, actors }: { run: AgentRun; changeId: string; actors: ReturnType<typeof useActors>["actors"] }) {
  const info = agentRunInfo(run.status);
  return (
    <Section
      title={`${run.adapter} run`}
      description={`Started ${formatRelative(run.started_at)}`}
      action={
        <div className="flex items-center gap-2">
          <StatusLabel status={info} />
          {run.status === "RUNNING" ? <RunControl kind="pause" run={run} changeId={changeId} actors={actors} /> : null}
          {run.status === "PAUSED" ? <RunControl kind="resume" run={run} changeId={changeId} actors={actors} /> : null}
          {isActiveRun(run) ? <RunControl kind="stop" run={run} changeId={changeId} actors={actors} /> : null}
        </div>
      }
    >
      <Facts
        items={[
          { label: "Started", value: <span title={formatTime(run.started_at)}>{formatTime(run.started_at)}</span> },
          ...(run.paused_at ? [{ label: "Paused", value: formatTime(run.paused_at) }] : []),
          ...(run.resumed_at ? [{ label: "Resumed", value: formatTime(run.resumed_at) }] : []),
          ...(run.completed_at ? [{ label: "Finished", value: formatTime(run.completed_at) }] : []),
          { label: "Exit code", value: <span className="tabular-nums">{run.exit_code ?? "—"}</span> },
          { label: "Duration", value: run.duration_ms == null ? "—" : <span className="tabular-nums">{run.duration_ms} ms</span> },
          { label: "Top-level PID", value: <span className="tabular-nums">{run.top_level_pid ?? "—"}</span> },
          ...(run.external_run_id ? [{ label: "External run", value: <code>{run.external_run_id}</code> }] : []),
          { label: "Descendant control", value: run.descendant_control_available ? "Available" : "Not available" },
        ]}
      />
      {run.limitations?.length ? <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{run.limitations.map((l) => <li key={l}>{l}</li>)}</ul> : null}
      <OutputBlock label="stdout" text={run.stdout} />
      <OutputBlock label="stderr" text={run.stderr} />
      {run.output_truncated ? <p className="mt-2 text-xs text-muted-foreground">Output was truncated to the configured limit.</p> : null}
    </Section>
  );
}

function OutputBlock({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <details className="mt-3 rounded-md border">
      <summary className="cursor-pointer px-3 py-2 text-[13px] text-muted-foreground">{label} <span className="tabular-nums">({text.length.toLocaleString()} chars)</span></summary>
      <pre className="mono max-h-72 overflow-auto whitespace-pre-wrap break-words border-t bg-secondary px-3 py-2 text-xs" tabIndex={0} aria-label={`${label} output`}>{text}</pre>
    </details>
  );
}

function AdapterSelect({ id, adapters, value, onChange, error }: { id: string; adapters: AgentAdapterInfo[]; value: string; onChange: (v: string) => void; error?: string | null }) {
  return (
    <Field id={id} label="Adapter" error={error} hint={adapters.length === 0 ? "No adapters reported." : undefined}>
      <Select id={id} value={value} onChange={onChange} aria-describedby={`${id}-h`}>
        <option value="">Select an adapter…</option>
        {adapters.map((a) => <option key={a.adapter} value={a.adapter}>{a.adapter}</option>)}
      </Select>
    </Field>
  );
}

function LaunchAgent({ changeId, actors, adapters }: { changeId: string; actors: ReturnType<typeof useActors>["actors"]; adapters: AgentAdapterInfo[] }) {
  const [v, setV] = useState({ actor: "", adapter: "", exe: "", args: "", timeout: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setV({ actor: "", adapter: adapters.length === 1 ? adapters[0]!.adapter : "", exe: "", args: "", timeout: "" }); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({ run: (b: Parameters<typeof launchAgent>[1], key) => launchAgent(changeId, b, key), invalidate: [[...changeKeys.all], ["tools"]], onSuccess: () => dlg.close() });
  const set = (k: keyof typeof v) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  return (
    <>
      <Button size="sm" onClick={dlg.show}>Launch agent</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Launch a top-level agent"
        description="Start an agent executable in this repository. The runtime records this run only, not its descendant processes."
        submitLabel="Launch"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!v.actor) e.actor = "Choose who is launching this run.";
          if (!v.adapter) e.adapter = "Choose an adapter.";
          if (!v.exe.trim()) e.exe = "Enter the executable to run.";
          if (v.timeout.trim() && !/^[1-9]\d*$/.test(v.timeout.trim())) e.timeout = "Use a whole number of seconds.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: v.actor, launch: { adapter: v.adapter, executable: v.exe.trim(), args: splitArgs(v.args), ...(v.timeout.trim() ? { timeout_seconds: Number(v.timeout) } : {}) } });
        }}
      >
        <ActorPicker id="la-actor" label="Launched by" actors={actors} value={v.actor} onChange={set("actor")} error={errs.actor} />
        <AdapterSelect id="la-adapter" adapters={adapters} value={v.adapter} onChange={set("adapter")} error={errs.adapter} />
        <Field id="la-exe" label="Executable" error={errs.exe}>
          <Input id="la-exe" value={v.exe} onChange={(e) => set("exe")(e.target.value)} className="mono text-[13px]" autoComplete="off" aria-describedby="la-exe-h" />
        </Field>
        <Field id="la-args" label="Arguments (optional)" hint="Separated by spaces. Use quotes for arguments containing spaces.">
          <Input id="la-args" value={v.args} onChange={(e) => set("args")(e.target.value)} className="mono text-[13px]" autoComplete="off" aria-describedby="la-args-h" />
        </Field>
        <Field id="la-timeout" label="Time limit in seconds (optional)" error={errs.timeout}>
          <Input id="la-timeout" inputMode="numeric" value={v.timeout} onChange={(e) => set("timeout")(e.target.value)} aria-describedby="la-timeout-h" />
        </Field>
      </FormDialog>
    </>
  );
}

function AttachAgent({ changeId, actors, adapters }: { changeId: string; actors: ReturnType<typeof useActors>["actors"]; adapters: AgentAdapterInfo[] }) {
  const [v, setV] = useState({ actor: "", adapter: "", external: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setV({ actor: "", adapter: "", external: "" }); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({ run: (b: Parameters<typeof attachAgent>[1], key) => attachAgent(changeId, b, key), invalidate: [[...changeKeys.all], ["tools"]], onSuccess: () => dlg.close() });
  const set = (k: keyof typeof v) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  return (
    <>
      <Button size="sm" variant="outline" onClick={dlg.show}>Attach a running agent</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Attach a running agent"
        description="Record an agent that is already running elsewhere. The runtime can't observe it; the run id is what you declare."
        submitLabel="Attach"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!v.actor) e.actor = "Choose who is attaching this run.";
          if (!v.adapter) e.adapter = "Choose an adapter.";
          if (!v.external.trim()) e.external = "Enter the run id the agent reports.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: v.actor, attach: { adapter: v.adapter, external_run_id: v.external.trim() } });
        }}
      >
        <ActorPicker id="at-actor" label="Attached by" actors={actors} value={v.actor} onChange={set("actor")} error={errs.actor} />
        <AdapterSelect id="at-adapter" adapters={adapters} value={v.adapter} onChange={set("adapter")} error={errs.adapter} />
        <Field id="at-ext" label="External run id" error={errs.external}>
          <Input id="at-ext" value={v.external} onChange={(e) => set("external")(e.target.value)} className="mono text-[13px]" autoComplete="off" aria-describedby="at-ext-h" />
        </Field>
      </FormDialog>
    </>
  );
}
