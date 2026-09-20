import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Bot } from "lucide-react";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Select } from "@/components/FormDialog";
import { DataTable, EmptyState, PageHeader, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import type { AgentRun } from "@/lib/api/types";
import { agentRunInfo, formatRelative, formatTime } from "@/lib/status";
import { cn } from "@/lib/utils";
import { adaptersQuery, agentsQuery, isActiveRun } from "@/services/actions";
import { AttachAgent, LaunchAgent, RunControl } from "@/features/agents/AgentsTab";
import { useActors } from "@/features/authority/useActors";
import { changeListQuery } from "@/services/changes";

const RECENT = 8; // The API lists runs per Change, so runs are gathered for the most recent Changes.

type Row = { change: { id: string; title: string }; run: AgentRun };

/** Agents across the workspace: which adapters exist, what is running now, and a jump to launch on a Change. */
export function AgentsPage() {
  const changes = useQuery(changeListQuery());
  const adapters = useQuery(adaptersQuery());
  const recent = (changes.data?.items ?? []).slice(0, RECENT);
  const runs = useQueries({ queries: recent.map((c) => agentsQuery(c.id)) });
  const [target, setTarget] = useState("");
  const rows: Row[] = recent
    .flatMap((c, i) => (runs[i]?.data?.items ?? []).map((run) => ({ change: c, run })))
    .sort((a, b) => Date.parse(b.run.started_at) - Date.parse(a.run.started_at));
  const live = rows.filter((r) => isActiveRun(r.run));
  const past = rows.filter((r) => !isActiveRun(r.run)).slice(0, 10);
  const selected = target || recent[0]?.id || "";
  const { actors } = useActors(selected || undefined);
  const adapterList = adapters.data?.items ?? [];

  return (
    <>
      <PageHeader title="Agents" description="Top-level agent runs across your Changes. Sentinel records the run it started or was told about; it doesn't see what the agent spawns." />
      <Section title="Launch or attach" description="Runs belong to a Change. Pick one, then launch a new agent or record one that is already running.">
        {recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">Create a Change first.</p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid min-w-[16rem] gap-1.5">
              <label htmlFor="ag-change" className="text-sm font-medium">Change</label>
              <Select id="ag-change" value={selected} onChange={setTarget}>
                {recent.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </Select>
            </div>
            <LaunchAgent changeId={selected} actors={actors} adapters={adapterList} />
            <AttachAgent changeId={selected} actors={actors} adapters={adapterList} />
            <Button asChild variant="ghost"><Link to="/changes/$changeId/agents" params={{ changeId: selected }}>Open its Agents tab</Link></Button>
          </div>
        )}
      </Section>
      <Section title="Live runs" description={live.length ? `${live.length} running or paused` : undefined} flush>
        {changes.isPending ? (
          <Skeleton lines={2} label="Loading runs" />
        ) : live.length === 0 ? (
          <EmptyState icon={<Bot className="size-6" strokeWidth={1.5} aria-hidden="true" />} title="No live runs">Nothing is running now. Recent runs are listed below.</EmptyState>
        ) : (
          <RunTable rows={live} label="Live runs" controls actors={actors} />
        )}
      </Section>
      {past.length ? <Section title="Recent runs" flush><RunTable rows={past} label="Recent runs" /></Section> : null}
      <Section title="Adapters" description="Agent executables Sentinel found on this computer.">
        {adapters.isError ? (
          <ErrorState error={adapters.error} onRetry={() => adapters.refetch()} />
        ) : (adapters.data?.items ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground">{adapters.isPending ? "Loading…" : "No adapters are configured."}</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {adapters.data!.items.map((a) => (
              <li key={a.adapter} className="flex flex-wrap justify-between gap-2">
                <span className="font-medium">{a.adapter}</span>
                <span className="text-muted-foreground">{Object.entries(a.executables).map(([n, f]) => `${n}: ${f ? "found" : "not found"}`).join(" · ") || "none listed"}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}

function RunTable({ rows, label, controls = false, actors = [] }: { rows: Row[]; label: string; controls?: boolean; actors?: ReturnType<typeof useActors>["actors"] }) {
  return (
    <DataTable label={label}>
      <thead>
        <tr><th className={th}>Change</th><th className={th}>Adapter</th><th className={th}>Status</th><th className={th}>Started</th>{controls ? <th className={th}><span className="sr-only">Actions</span></th> : null}</tr>
      </thead>
      <tbody>
        {rows.map(({ change, run }) => (
          <tr key={run.id}>
            <td className={cn(td, "break-words")}>
              <Link to="/changes/$changeId/agents" params={{ changeId: change.id }} className="underline-offset-2 hover:underline">{change.title}</Link>
            </td>
            <td className={td}>{run.adapter}</td>
            <td className={td}><StatusLabel status={agentRunInfo(run.status)} /></td>
            <td className={td} title={formatTime(run.started_at)}>{formatRelative(run.started_at)}</td>
            {controls ? (
              <td className={td}>
                <div className="flex gap-1.5">
                  {run.status === "RUNNING" ? <RunControl kind="pause" run={run} changeId={change.id} actors={actors} /> : null}
                  {run.status === "PAUSED" ? <RunControl kind="resume" run={run} changeId={change.id} actors={actors} /> : null}
                  <RunControl kind="stop" run={run} changeId={change.id} actors={actors} />
                </div>
              </td>
            ) : null}
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
