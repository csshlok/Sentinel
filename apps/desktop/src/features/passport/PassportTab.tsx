import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Download } from "lucide-react";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { DataTable, EmptyState, Facts, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { useActors } from "@/features/authority/useActors";
import { ApiError } from "@/lib/api/client";
import { exportFileName, saveJsonExport, type SaveResult } from "@/lib/export";
import { evidenceInfo, formatRelative, formatTime, lifecycleInfo, recoveryInfo, signatureInfo, trustInfo } from "@/lib/status";
import { buildPassport, passportQuery } from "@/services/actions";

/** "Trace verified" is the honest reading of a verified hash chain; a passport doesn't prove the change is correct. */
function replayLine(p: { replay_verified?: boolean | null; replay_checked_events?: number | null; replay_first_break_seq?: number | null }) {
  if (p.replay_verified == null) return "Not checked when this passport was built";
  if (p.replay_verified) return `Trace verified (${p.replay_checked_events ?? 0} events)`;
  return `Trace chain broken at event ${p.replay_first_break_seq ?? "?"}`;
}

export function PassportTab() {
  const id = useParams({ from: "/changes/$changeId" }).changeId;
  const qc = useQueryClient();
  const q = useQuery(passportQuery(id));
  const { nameOf } = useActors(id);
  const [saved, setSaved] = useState<SaveResult | null>(null);
  const build = useMutation({ mutationFn: () => buildPassport(id), onSuccess: () => qc.invalidateQueries({ queryKey: passportQuery(id).queryKey }) });
  const save = useMutation({ mutationFn: (data: unknown) => saveJsonExport(exportFileName("passport", id), data), onSuccess: setSaved });

  const missing = q.isError && q.error instanceof ApiError && q.error.kind === "not_found";
  const p = q.data;
  if (q.isPending) return <Section flush><Skeleton lines={3} label="Loading passport" /></Section>;
  if (q.isError && !missing) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;

  const buildButton = (
    <Button size="sm" variant={p ? "outline" : "default"} disabled={build.isPending} onClick={() => build.mutate()}>
      {build.isPending ? "Building…" : p ? "Rebuild" : "Build passport"}
    </Button>
  );

  return (
    <>
      {build.isError ? <Notice tone="danger" title="The passport wasn't built" role="alert">{build.error instanceof ApiError ? build.error.message : "The request failed."}</Notice> : null}
      {save.isError ? <Notice tone="danger" title="The export wasn't saved" role="alert">{save.error instanceof Error ? save.error.message : "Saving failed."}</Notice> : null}
      {saved?.kind === "saved" ? <Notice title="Saved" role="status">Written to <code className="break-all">{saved.where}</code>.</Notice> : null}

      {!p ? (
        <Section><EmptyState title="No passport yet" action={buildButton}>A passport summarizes intent, authority, evidence, outcomes and tool trust for this Change at one moment. Building one doesn't change the Change.</EmptyState></Section>
      ) : (
        <>
          <Section
            title="Change passport"
            description={`Built ${formatRelative(p.generated_at)}`}
            action={<div className="flex gap-2">{buildButton}<Button size="sm" variant="outline" disabled={save.isPending} onClick={() => save.mutate(p)}><Download aria-hidden="true" /> Export JSON</Button></div>}
          >
            <Facts
              items={[
                { label: "Lifecycle", value: <StatusLabel status={lifecycleInfo(p.lifecycle_state)} /> },
                { label: "Digest", value: <code className="break-all" title={p.canonical_digest}>{p.canonical_digest}</code> },
                { label: "Built", value: formatTime(p.generated_at) },
                { label: "Trace", value: replayLine(p) },
                { label: "Recovery", value: p.recovery_status ? <StatusLabel status={recoveryInfo(p.recovery_status)} /> : "None" },
                { label: "Outcomes", value: p.outcomes?.length ? p.outcomes.join(", ") : "None recorded" },
              ]}
            />
            <p className="mt-3 text-xs text-muted-foreground">Exports contain exactly this passport as the server produced it. A passport records what was observed; it doesn't certify the change is correct.</p>
          </Section>

          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Actors">
              {p.actor_ids?.length ? <ul className="space-y-1 text-sm">{p.actor_ids.map((a) => <li key={a} className="break-words">{nameOf(a)}</li>)}</ul> : <p className="text-sm text-muted-foreground">None recorded.</p>}
            </Section>
            <Section title="Authority">
              {p.authority_summary?.length ? <ul className="list-disc space-y-1 pl-5 text-sm">{p.authority_summary.map((a) => <li key={a} className="break-words">{a}</li>)}</ul> : <p className="text-sm text-muted-foreground">No delegations recorded.</p>}
            </Section>
          </div>

          <Section title="Evidence" flush>
            {p.evidence?.length ? (
              <DataTable label="Evidence references">
                <thead><tr><th className={th}>Kind</th><th className={th}>Reference</th><th className={th}>Status</th><th className={th}>Captured</th></tr></thead>
                <tbody>
                  {p.evidence.map((e) => (
                    <tr key={`${e.kind}:${e.id}`}>
                      <td className={td}>{e.kind.replace(/_/g, " ")}</td>
                      <td className={`${td} mono`} title={e.id}>{e.id.slice(0, 12)}</td>
                      <td className={td}><StatusLabel status={evidenceInfo(e.status)} /></td>
                      <td className={td} title={formatTime(e.captured_at)}>{formatRelative(e.captured_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            ) : <p className="px-5 py-4 text-sm text-muted-foreground">No evidence referenced.</p>}
          </Section>

          <Section title="Tool trust" flush>
            {p.tool_trust_summary?.length ? (
              <DataTable label="Tool trust">
                <thead><tr><th className={th}>Tool</th><th className={th}>Publisher</th><th className={th}>Signature</th><th className={th}>Trust</th><th className={th}>Drift</th></tr></thead>
                <tbody>
                  {p.tool_trust_summary.map((t) => (
                    <tr key={t.tool_id}>
                      <td className={td}>{t.name} {t.version}</td>
                      <td className={td}>{t.publisher ?? "—"}</td>
                      <td className={td}><StatusLabel status={signatureInfo(t.signature_state)} /></td>
                      <td className={td}><StatusLabel status={trustInfo(t.trust_state)} /></td>
                      <td className={td}>{t.drifted ? "Changed since decision" : "None"}</td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            ) : <p className="px-5 py-4 text-sm text-muted-foreground">No top-level tools recorded.</p>}
          </Section>

          <Section title="Limitations" description="What this passport can't tell you.">
            {p.limitations?.length ? <ul className="list-disc space-y-1 pl-5 text-sm">{p.limitations.map((l) => <li key={l}>{l}</li>)}</ul> : <p className="text-sm text-muted-foreground">None reported.</p>}
          </Section>
        </>
      )}
    </>
  );
}
