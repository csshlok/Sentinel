import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker, CheckpointPicker } from "@/components/pickers";
import { Chips, DataTable, EmptyState, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useActors } from "@/features/authority/useActors";
import { CaptureEvidence } from "@/features/changes/Actions";
import { ApiError } from "@/lib/api/client";
import type { EnvironmentDrift, EnvironmentFact, GitCheckpoint } from "@/lib/api/types";
import { evidenceInfo, formatRelative, formatTime, lifecycleInfo, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { changeToolsQuery, checkpointsQuery, comparisonQuery, declareTool, dependenciesQuery, environmentQuery, forkChange, forksQuery } from "@/services/actions";
import { changeKeys, evidenceQuery } from "@/services/changes";

const isMissing = (e: unknown) => e instanceof ApiError && e.kind === "not_found";
const Loading = ({ label }: { label: string }) => <Section flush><Skeleton lines={3} label={label} /></Section>;

export function EvidenceTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const evidence = useQuery(evidenceQuery(changeId));
  const checkpoints = useQuery(checkpointsQuery(changeId));
  const [forkFrom, setForkFrom] = useState<GitCheckpoint | null>(null);

  if (evidence.isPending || checkpoints.isPending) return <Loading label="Loading evidence" />;
  if (evidence.isError) return <ErrorState error={evidence.error} onRetry={() => evidence.refetch()} />;
  if (checkpoints.isError) return <ErrorState error={checkpoints.error} onRetry={() => checkpoints.refetch()} />;

  const ev = evidence.data;
  const list = checkpoints.data.items ?? [];
  const fresh = ev.latest_checkpoint_fresh;

  return (
    <>
      <CaptureEvidence changeId={changeId} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Baseline" action={<StatusLabel status={ev.baseline_captured ? { label: "Captured", tone: "ok" } : { label: "Not captured", tone: "warn" }} />}>
          <p className="text-sm text-muted-foreground">{ev.baseline_captured ? "A baseline checkpoint exists to compare later state against." : "No baseline yet. Comparisons and recovery need one."}</p>
        </Section>
        <Section title="Latest checkpoint" action={<StatusLabel status={fresh === true ? { label: "Fresh", tone: "ok" } : fresh === false ? { label: "Stale", tone: "warn" } : { label: "None", tone: "neutral" }} />}>
          <p className="text-sm text-muted-foreground">
            {fresh === false ? "The repository has moved since the latest checkpoint. Capture new evidence before relying on it." : fresh === true ? "Matches the repository as of the last check." : "No checkpoint has been captured."}
          </p>
        </Section>
      </div>

      <Section title="Git checkpoints" description="Git state at a moment in time. Not a record of who wrote which file." flush>
        {list.length === 0 ? (
          <EmptyState title="No checkpoints">Capture a baseline to start.</EmptyState>
        ) : (
          <DataTable label="Git checkpoints">
            <thead><tr><th className={th}>Name</th><th className={th}>Branch</th><th className={th}>HEAD</th><th className={th}>Files</th><th className={th}>Captured</th><th className={th}><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {list.map((cp) => (
                <tr key={cp.id}>
                  <td className={td}>{cp.name}</td>
                  <td className={td}>{cp.branch ?? "detached"}</td>
                  <td className={cn(td, "mono")}>{shortSha(cp.head_sha)}</td>
                  <td className={cn(td, "tabular-nums")}>{(cp.summary.files ?? []).length}</td>
                  <td className={td} title={formatTime(cp.captured_at)}>{formatRelative(cp.captured_at)}</td>
                  <td className={td}><Button size="sm" variant="ghost" onClick={() => setForkFrom(cp)}>Fork from here</Button></td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>

      <Compare changeId={changeId} checkpoints={list} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Environment changeId={changeId} />
        <Dependencies changeId={changeId} />
      </div>
      <ToolsSeen changeId={changeId} />
      <Forks changeId={changeId} />
      {forkFrom ? <ForkDialog changeId={changeId} checkpoint={forkFrom} onClose={() => setForkFrom(null)} /> : null}
      <p className="text-xs leading-5 text-muted-foreground">Checkpoints record Git state, environment facts and dependency manifests. They don't attribute individual file writes or processes to an actor, and environment values are shown only as fingerprints when sensitive.</p>
    </>
  );
}

function Compare({ changeId, checkpoints }: { changeId: string; checkpoints: GitCheckpoint[] }) {
  const sorted = [...checkpoints].sort((a, b) => Date.parse(a.captured_at) - Date.parse(b.captured_at));
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const from = a || sorted[0]?.id || "";
  const to = b || sorted[sorted.length - 1]?.id || "";
  const q = useQuery(comparisonQuery(changeId, from, to));
  const same = from !== "" && from === to;
  return (
    <Section title="Compare checkpoints" description="What moved between two Git checkpoints.">
      <div className="grid gap-3 sm:grid-cols-2">
        <CheckpointPicker id="cmp-a" label="From" checkpoints={sorted} value={from} onChange={setA} />
        <CheckpointPicker id="cmp-b" label="To" checkpoints={sorted} value={to} onChange={setB} />
      </div>
      <div className="mt-4">
        {sorted.length < 2 ? (
          <p className="text-sm text-muted-foreground">Comparison needs at least two checkpoints. Capture current evidence after the work.</p>
        ) : same ? (
          <p className="text-sm text-muted-foreground">Pick two different checkpoints.</p>
        ) : q.isPending ? (
          <p className="text-sm text-muted-foreground" role="status">Comparing…</p>
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : (
          <div className="space-y-3">
            <p className="text-sm">
              HEAD {q.data.head_changed ? <strong>changed</strong> : "unchanged"} · branch {q.data.branch_moved ? <strong>moved</strong> : "unchanged"}
            </p>
            <div className="grid gap-4 md:grid-cols-3">
              <PathList title="Added" items={q.data.added_paths} />
              <PathList title="Changed" items={q.data.changed_paths} />
              <PathList title="Removed" items={q.data.removed_paths} />
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

function PathList({ title, items }: { title: string; items: string[] | undefined }) {
  const list = items ?? [];
  return (
    <div>
      <p className="text-[13px] font-medium">{title} <span className="tabular-nums text-muted-foreground">({list.length})</span></p>
      {list.length === 0 ? <p className="mt-1 text-sm text-muted-foreground">None</p> : <Chips items={list.slice(0, 50)} empty="" />}
      {list.length > 50 ? <p className="mt-1 text-xs text-muted-foreground">and {list.length - 50} more</p> : null}
    </div>
  );
}

function FactRows({ facts }: { facts: EnvironmentFact[] }) {
  return (
    <ul className="divide-y text-sm">
      {facts.map((f) => (
        <li key={f.key} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
          <code className="break-all">{f.key}</code>
          <span className="flex items-center gap-2 text-muted-foreground">
            {f.sensitive ? <span title={f.fingerprint ?? undefined}>sensitive · {f.fingerprint ? `fingerprint ${f.fingerprint.slice(0, 8)}` : "hidden"}</span> : <span className="break-all">{f.value ?? "—"}</span>}
            <StatusLabel status={evidenceInfo(f.status)} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function Drift({ drift }: { drift: EnvironmentDrift }) {
  const groups: [string, EnvironmentFact[] | undefined][] = [["Added", drift.added], ["Removed", drift.removed], ["Changed", drift.changed], ["Unknown", drift.unknown]];
  const total = groups.reduce((n, [, l]) => n + (l?.length ?? 0), 0);
  return (
    <div className="mt-4 border-t pt-3">
      <p className="text-[13px] font-medium">Drift since the baseline <span className="tabular-nums text-muted-foreground">({total})</span></p>
      {total === 0 ? <p className="mt-1 text-sm text-muted-foreground">No drift recorded.</p> : groups.map(([label, l]) => (l?.length ? <div key={label} className="mt-2"><p className="text-xs text-muted-foreground">{label}</p><FactRows facts={l} /></div> : null))}
      {!drift.causal_attribution_available ? <p className="mt-2 text-xs text-muted-foreground">Drift shows what differs, not what caused it.</p> : null}
    </div>
  );
}

function Environment({ changeId }: { changeId: string }) {
  const q = useQuery(environmentQuery(changeId));
  return (
    <Section title="Environment">
      {q.isPending ? <p className="text-sm text-muted-foreground" role="status">Loading…</p> : q.isError && !isMissing(q.error) ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !q.data?.passport ? (
        <p className="text-sm text-muted-foreground">No environment captured yet.</p>
      ) : (
        <>
          <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground"><span>Captured {formatRelative(q.data.passport.captured_at)}</span><StatusLabel status={evidenceInfo(q.data.passport.status)} /></div>
          {(q.data.passport.facts ?? []).length ? <FactRows facts={q.data.passport.facts!.slice(0, 40)} /> : <p className="text-sm text-muted-foreground">No facts recorded.</p>}
          {(q.data.passport.facts ?? []).length > 40 ? <p className="mt-1 text-xs text-muted-foreground">Showing the first 40 of {q.data.passport.facts!.length}.</p> : null}
          {q.data.passport.limitations?.length ? <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">{q.data.passport.limitations.map((l) => <li key={l}>{l}</li>)}</ul> : null}
          {q.data.drift ? <Drift drift={q.data.drift} /> : null}
        </>
      )}
    </Section>
  );
}

function Dependencies({ changeId }: { changeId: string }) {
  const q = useQuery(dependenciesQuery(changeId));
  const changes = q.data?.changes ?? [];
  return (
    <Section title="Dependencies" flush>
      {q.isPending ? <p className="px-5 py-4 text-sm text-muted-foreground" role="status">Loading…</p> : q.isError && !isMissing(q.error) ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !q.data ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">No dependency report yet.</p>
      ) : changes.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">No dependency changes since the baseline.</p>
      ) : (
        <DataTable label="Dependency changes">
          <thead><tr><th className={th}>Package</th><th className={th}>Version</th><th className={th}>Source</th><th className={th}>Evidence</th></tr></thead>
          <tbody>
            {changes.map((d) => (
              <tr key={`${d.ecosystem}:${d.package}:${d.source_path}`}>
                <td className={td}><span className="font-medium">{d.package}</span><span className="block text-xs text-muted-foreground">{d.ecosystem}{d.direct === false ? " · indirect" : ""}</span></td>
                <td className={cn(td, "whitespace-nowrap tabular-nums")}>{d.old_version ?? "—"} → {d.new_version ?? "removed"}</td>
                <td className={cn(td, "mono break-all text-xs")}>{d.source_path}</td>
                <td className={td}><StatusLabel status={evidenceInfo(d.evidence_status)} />{d.risk_notes?.length ? <p className="mt-1 max-w-[26ch] text-xs text-muted-foreground">{d.risk_notes.join(" ")}</p> : null}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      {q.data?.unsupported_ecosystems?.length ? <p className="border-t px-5 py-2.5 text-xs text-muted-foreground">Not analyzed: {q.data.unsupported_ecosystems.join(", ")}.</p> : null}
    </Section>
  );
}

function ToolsSeen({ changeId }: { changeId: string }) {
  const q = useQuery(changeToolsQuery(changeId));
  const [path, setPath] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const dlg = useDialogState(() => { setPath(""); setErr(null); declare.reset(); });
  const declare = useFormAction({ run: (p: string) => declareTool(changeId, p), invalidate: [[...changeKeys.all], ["tools"]], onSuccess: () => dlg.close() });
  const items = q.data?.items ?? [];
  return (
    <Section title="Tools seen" description="Top-level executables observed for this Change." action={<Button size="sm" variant="outline" onClick={dlg.show}>Declare a tool</Button>} flush>
      {q.isPending ? <p className="px-5 py-4 text-sm text-muted-foreground" role="status">Loading…</p> : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : items.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">No tools seen for this Change.</p>
      ) : (
        <ul className="divide-y text-sm">
          {items.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
              <Link to="/tools/$toolId" params={{ toolId: t.id }} className="min-w-0 break-words underline-offset-2 hover:underline">{t.name} {t.version}</Link>
              <StatusLabel status={{ label: t.trust_state.toLowerCase(), tone: t.trust_state === "DENIED" ? "danger" : t.trust_state === "APPROVED" ? "ok" : "neutral" }} />
            </li>
          ))}
        </ul>
      )}
      <FormDialog open={dlg.open} onOpenChange={dlg.onOpenChange} title="Declare a tool" description="Register a top-level tool from a manifest file on this computer." submitLabel="Declare" pending={declare.isPending} error={declare.error} submit={() => (path.trim() ? (setErr(null), declare.mutate(path.trim())) : setErr("Enter the manifest path."))}>
        <Field id="dt-path" label="Manifest path" error={err}><Input id="dt-path" value={path} onChange={(e) => setPath(e.target.value)} className="mono text-[13px]" autoComplete="off" aria-describedby="dt-path-h" /></Field>
      </FormDialog>
    </Section>
  );
}

function Forks({ changeId }: { changeId: string }) {
  const q = useQuery(forksQuery(changeId));
  const items = q.data?.items ?? [];
  if (q.isPending || (q.isSuccess && items.length === 0)) return null;
  return (
    <Section title="Forked from this Change" description="Each fork is its own Change; this one isn't modified." flush>
      {q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
        <ul className="divide-y text-sm">
          {items.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-3 px-5 py-2.5">
              <Link to="/changes/$changeId" params={{ changeId: c.id }} className="min-w-0 break-words underline-offset-2 hover:underline">{c.title}</Link>
              <StatusLabel status={lifecycleInfo(c.lifecycle_state)} />
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function ForkDialog({ changeId, checkpoint, onClose }: { changeId: string; checkpoint: GitCheckpoint; onClose: () => void }) {
  const { actors } = useActors(changeId);
  const navigate = useNavigate();
  const [v, setV] = useState({ actor: "", title: "", intent: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const run = useFormAction({
    run: (b: Parameters<typeof forkChange>[1], key) => forkChange(changeId, b, key),
    invalidate: [[...changeKeys.all]],
    onSuccess: (created) => { onClose(); void navigate({ to: "/changes/$changeId", params: { changeId: created.id } }); },
  });
  return (
    <FormDialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Fork this Change"
      description={`Start a new Change from checkpoint “${checkpoint.name}” (${shortSha(checkpoint.head_sha)}). The original is not modified.`}
      submitLabel="Create fork"
      pending={run.isPending}
      error={run.error}
      submit={() => {
        const e: Record<string, string> = {};
        if (!v.actor) e.actor = "Choose who is forking.";
        if (!v.title.trim()) e.title = "Enter a title for the new Change.";
        if (!v.intent.trim()) e.intent = "Describe the intent of the new Change.";
        setErrs(e);
        if (Object.keys(e).length) return;
        run.mutate({ actor_id: v.actor, fork: { checkpoint_id: checkpoint.id, title: v.title.trim(), intent: v.intent.trim() } });
      }}
    >
      <ActorPicker id="fk-actor" label="Forked by" actors={actors} value={v.actor} onChange={(x) => setV((s) => ({ ...s, actor: x }))} error={errs.actor} />
      <Field id="fk-title" label="New title" error={errs.title}><Input id="fk-title" value={v.title} onChange={(e) => setV((s) => ({ ...s, title: e.target.value }))} aria-describedby="fk-title-h" /></Field>
      <Field id="fk-intent" label="New intent" error={errs.intent}><Input id="fk-intent" value={v.intent} onChange={(e) => setV((s) => ({ ...s, intent: e.target.value }))} aria-describedby="fk-intent-h" /></Field>
      <Notice title="What a fork keeps">The new Change copies this Change's contract, uses the checkpoint as its baseline, and records its parent for lineage. Delegations aren't copied, so grant authority again on the new Change.</Notice>
    </FormDialog>
  );
}
