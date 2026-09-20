import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Download, LoaderCircle, RefreshCw } from "lucide-react";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { DataTable, EmptyState, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { useActors } from "@/features/authority/useActors";
import type { JournalEvent } from "@/lib/api/types";
import { exportFileName, saveJsonExport, type SaveResult } from "@/lib/export";
import { formatRelative, formatTime } from "@/lib/status";
import { cn } from "@/lib/utils";
import { replayQuery, replayVerifyQuery } from "@/services/actions";
import { eventPagesQuery } from "@/services/changes";
import { http } from "@/lib/api";
import { displayPayload, restorationText } from "./payload";

export function TimelineTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const events = useInfiniteQuery(eventPagesQuery(changeId));
  const verify = useQuery(replayVerifyQuery(changeId));
  const [selected, setSelected] = useState<string | null>(null);
  const { nameOf } = useActors(changeId);

  if (events.isPending) return <Section flush><Skeleton lines={5} label="Loading timeline" /></Section>;
  if (events.isError && !events.data) return <ErrorState error={events.error} onRetry={() => events.refetch()} />;

  const seen = new Set<string>();
  const items = (events.data?.pages ?? []).flatMap((p) => p.items ?? []).filter((e) => (seen.has(e.id) ? false : (seen.add(e.id), true)));
  const firstBreak = verify.data && !verify.data.verified ? verify.data.first_break_seq : null;
  const current = items.find((e) => e.id === selected) ?? null;

  return (
    <>
      <ChainStatus changeId={changeId} verify={verify} />
      {items.length === 0 ? (
        <Section><EmptyState title="No events yet">Events appear here as this Change is created, updated and verified.</EmptyState></Section>
      ) : (
        <div className={cn("grid gap-6", current ? "xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]" : "")}>
          <div className="min-w-0 space-y-4">
            <Section flush>
              <DataTable label="Change events">
                <thead>
                  <tr>
                    <th className={th}>#</th>
                    <th className={th}>When</th>
                    <th className={th}>Event</th>
                    <th className={th}>Actor</th>
                    <th className={th}>Subject</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((e) => {
                    const broken = firstBreak != null && e.seq === firstBreak;
                    return (
                      <tr key={e.id} className={cn(e.id === selected && "bg-[var(--primary-tint)]", broken && "bg-[var(--status-error-bg)]")}>
                        <td className={cn(td, "tabular-nums")}>{e.seq}</td>
                        <td className={td} title={formatTime(e.occurred_at)}>{formatRelative(e.occurred_at)}</td>
                        <td className={td}>
                          <button type="button" className="mono break-all rounded-sm text-left underline-offset-2 hover:underline" aria-pressed={e.id === selected} onClick={() => setSelected(e.id === selected ? null : e.id)}>
                            {e.event_type}
                          </button>
                          {broken ? <span className="ml-2 text-xs text-danger">chain breaks here</span> : null}
                        </td>
                        <td className={cn(td, "break-words")}>{e.actor_id ? nameOf(e.actor_id) : "—"}</td>
                        <td className={cn(td, "break-words")}>{e.subject_type ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </DataTable>
            </Section>
            {events.hasNextPage ? (
              <div className="flex items-center gap-3">
                <Button variant="outline" size="sm" disabled={events.isFetchingNextPage} onClick={() => events.fetchNextPage()}>
                  {events.isFetchingNextPage ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}
                  Load more
                </Button>
                <span className="text-xs text-muted-foreground">{items.length} events loaded</span>
              </div>
            ) : null}
          </div>
          {current ? <EventInspector changeId={changeId} event={current} actor={current.actor_id ? nameOf(current.actor_id) : null} onClose={() => setSelected(null)} /> : null}
        </div>
      )}
      <p className="text-xs leading-5 text-muted-foreground">
        This is the recorded event trace, checked by its hash chain. “Trace verified” means the recorded events weren't altered; it isn't a re-run of the work, and it doesn't prove the change is correct. Events are never re-executed. There is no process tree or file-write timeline.
      </p>
    </>
  );
}

function ChainStatus({ changeId, verify }: { changeId: string; verify: ReturnType<typeof useQuery<import("@/lib/api/types").ChainVerificationResult>> }) {
  const [saved, setSaved] = useState<SaveResult | null>(null);
  const exportTrace = useMutation({
    mutationFn: async () => saveJsonExport(exportFileName("trace", changeId), await http.get(`/api/v1/changes/${encodeURIComponent(changeId)}/replay/export`)),
    onSuccess: setSaved,
  });
  const d = verify.data;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3" role="group" aria-label="Trace verification">
        {verify.isPending ? (
          <StatusLabel status={{ label: "Verifying trace…", tone: "neutral" }} />
        ) : verify.isError ? (
          <StatusLabel status={{ label: "Verification unavailable", tone: "warn" }} />
        ) : d?.verified ? (
          <StatusLabel status={{ label: `Trace verified · ${d.checked_events} events`, tone: "ok" }} />
        ) : (
          <StatusLabel status={{ label: `Chain broken at event ${d?.first_break_seq ?? "?"}`, tone: "danger" }} />
        )}
        <Button size="sm" variant="outline" disabled={verify.isFetching} onClick={() => verify.refetch()}>
          <RefreshCw className={verify.isFetching ? "animate-spin" : undefined} aria-hidden="true" /> Verify again
        </Button>
        <Button size="sm" variant="outline" disabled={exportTrace.isPending} onClick={() => exportTrace.mutate()}>
          <Download aria-hidden="true" /> Export trace
        </Button>
      </div>
      {d && !d.verified ? (
        <Notice tone="danger" title="The recorded trace doesn't verify" role="alert">
          {d.reason ?? "An event's hash doesn't match the chain."} Events after event {d.first_break_seq ?? "the break"} can't be trusted as recorded.
        </Notice>
      ) : null}
      {exportTrace.isError ? <Notice tone="danger" title="The trace wasn't exported" role="alert">{exportTrace.error instanceof Error ? exportTrace.error.message : "Export failed."}</Notice> : null}
      {saved?.kind === "saved" ? <Notice title="Saved" role="status">Written to <code className="break-all">{saved.where}</code>.</Notice> : null}
    </div>
  );
}

function EventInspector({ changeId, event, actor, onClose }: { changeId: string; event: JournalEvent; actor: string | null; onClose: () => void }) {
  const replay = useQuery(replayQuery(changeId));
  const effects = (replay.data?.effects ?? []).filter((f) => f.event_id === event.id);
  return (
    <Section title={event.event_type} description={`Event ${event.seq} · ${formatTime(event.occurred_at)}`} action={<Button size="sm" variant="ghost" onClick={onClose}>Close</Button>} className="h-fit xl:sticky xl:top-0">
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Actor</dt><dd className="break-words">{actor ?? "—"}</dd>
        <dt className="text-muted-foreground">Subject</dt><dd className="break-words">{event.subject_type ?? "—"}{event.subject_id ? <code className="ml-1 text-xs" title={event.subject_id}>{event.subject_id.slice(0, 8)}</code> : null}</dd>
        <dt className="text-muted-foreground">Hash</dt><dd><code className="break-all text-xs">{event.event_hash}</code></dd>
        <dt className="text-muted-foreground">Previous</dt><dd><code className="break-all text-xs">{event.prev_event_hash ?? "(first event)"}</code></dd>
      </dl>

      <h3 className="mt-4 text-[13px] font-medium">Recorded effects</h3>
      {replay.isPending ? (
        <p className="mt-1 text-sm text-muted-foreground" role="status">Loading…</p>
      ) : replay.isError ? (
        <p className="mt-1 text-sm text-muted-foreground">Effects couldn't be loaded.</p>
      ) : effects.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">This event recorded no effects.</p>
      ) : (
        <ul className="mt-1 space-y-2 text-sm">
          {effects.map((f) => (
            <li key={f.id} className="rounded-md border px-3 py-2">
              <p className="break-words font-medium">{f.resource_type} <code className="text-xs font-normal text-muted-foreground" title={f.resource_id}>{f.resource_id.slice(0, 12)}</code></p>
              <p className="text-xs text-muted-foreground">{restorationText(f.restoration_class)}</p>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-4 text-[13px] font-medium">Payload</h3>
      <pre className="mono mt-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-secondary px-3 py-2 text-xs" tabIndex={0} aria-label="Event payload">{JSON.stringify(displayPayload(event.payload ?? {}), null, 2)}</pre>
      <p className="mt-1 text-xs text-muted-foreground">Credential-like fields are hidden here. Long values are shortened for display only.</p>
    </Section>
  );
}
