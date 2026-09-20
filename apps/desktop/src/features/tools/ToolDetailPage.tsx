import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, Select, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { Chips, Facts, Notice, PageHeader, Section, Skeleton, StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useActors } from "@/features/authority/useActors";
import type { ToolManifest, ToolTrustDecision, ToolTrustScope } from "@/lib/api/types";
import { formatTime, signatureInfo, trustInfo } from "@/lib/status";
import { trustTool } from "@/services/actions";
import { toolDetailQuery, toolKeys } from "@/services/tools";

export function ToolDetailPage() {
  const toolId = useParams({ from: "/tools/$toolId" }).toolId;
  const q = useQuery(toolDetailQuery(toolId));
  const { actors } = useActors();
  const [decided, setDecided] = useState<ToolTrustDecision | null>(null);

  const back = (
    <Link to="/tools" className="inline-flex items-center gap-1.5 rounded-sm text-[13px] text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-3.5" aria-hidden="true" /> Tools
    </Link>
  );
  if (q.isPending) return <>{back}<Section flush><Skeleton lines={4} label="Loading tool" /></Section></>;
  if (q.isError) return <>{back}<ErrorState error={q.error} onRetry={() => q.refetch()} /></>;

  const t = q.data;
  const denied = t.trust_state === "DENIED";
  return (
    <>
      {back}
      <PageHeader
        title={`${t.name} ${t.version}`}
        description={t.publisher ? `Published by ${t.publisher}` : "No publisher recorded"}
        actions={
          <>
            <StatusLabel status={trustInfo(t.trust_state)} />
            <StatusLabel status={signatureInfo(t.signature_state)} />
            <TrustDecision tool={t} actors={actors} onDecided={setDecided} />
          </>
        }
      />
      {denied ? (
        <Notice tone="danger" title="This executable is denied">
          A denial stays in force until someone records a later, explicit decision. Seeing the tool again, or changing its files, does not lift it.
        </Notice>
      ) : null}
      {decided ? (
        <Notice tone="info" title="Decision recorded" role="status">
          {decided.decision === "DENY" ? "Denied" : "Approved"} for {decided.scope === "exact_version" ? "this exact version" : "this publisher's policy"} at {formatTime(decided.decided_at)}.
        </Notice>
      ) : null}

      <Section title="Manifest">
        <Facts
          items={[
            { label: "Name", value: t.name },
            { label: "Version", value: t.version },
            { label: "Source", value: <code className="break-all">{t.source}</code> },
            { label: "Digest", value: <code className="break-all">{t.artifact_digest}</code> },
            { label: "First seen", value: formatTime(t.first_seen_at) },
            { label: "Last seen", value: formatTime(t.last_seen_at) },
          ]}
        />
      </Section>
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Claims capabilities"><Chips items={t.capabilities} empty="None declared." /></Section>
        <Section title="Credentials it asks for"><Chips items={t.credential_requirements} empty="None declared." /></Section>
        <Section title="Filesystem scope"><Chips items={t.filesystem_scope} empty="None declared." /></Section>
        <Section title="Network scope"><Chips items={t.network_scope} empty="None declared." /></Section>
      </div>
      <p className="text-xs leading-5 text-muted-foreground">
        These are the tool's own declarations, not something the runtime verified or enforces. Trust applies to the top-level executable the runtime launches or attaches; an agent's internal tool and MCP calls are not intercepted. The API doesn't expose a decision history.
      </p>
    </>
  );
}

export function TrustDecision({ tool, actors, onDecided, label = "Trust decision" }: { tool: ToolManifest; actors: ReturnType<typeof useActors>["actors"]; onDecided?: (d: ToolTrustDecision) => void; label?: string }) {
  const [v, setV] = useState({ actor: "", decision: "" as "" | "APPROVE" | "DENY", scope: "exact_version" as ToolTrustScope, reason: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setV({ actor: "", decision: "", scope: "exact_version", reason: "" }); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({
    run: (b: Parameters<typeof trustTool>[1], key) => trustTool(tool.id, b, key),
    invalidate: [[...toolKeys.list.slice(0, 1)]],
    onSuccess: (d) => { onDecided?.(d); dlg.close(); },
  });
  const publisherOk = Boolean(tool.publisher);
  return (
    <>
      <Button size="sm" variant="outline" onClick={dlg.show}>{label}</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title={`Trust decision for ${tool.name} ${tool.version}`}
        description="Approve or deny this top-level executable. A denial stays in force until an explicit later decision changes it."
        submitLabel={v.decision === "DENY" ? "Deny tool" : v.decision === "APPROVE" ? "Approve tool" : "Record decision"}
        danger={v.decision === "DENY"}
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!v.actor) e.actor = "Choose who is deciding.";
          if (!v.decision) e.decision = "Choose approve or deny.";
          if (v.scope === "publisher_policy" && !publisherOk) e.scope = "This tool has no publisher, so a publisher policy can't apply.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: v.actor, decision: v.decision as "APPROVE" | "DENY", scope: v.scope, reason: v.reason.trim() || null });
        }}
      >
        <ActorPicker id="tt-actor" label="Decided by" actors={actors} value={v.actor} onChange={(x) => setV((s) => ({ ...s, actor: x }))} error={errs.actor} />
        <fieldset className="grid gap-1.5">
          <legend className="text-sm font-medium">Decision</legend>
          {(["APPROVE", "DENY"] as const).map((d) => (
            <label key={d} className="flex items-center gap-2 text-sm">
              <input type="radio" name="tt-decision" checked={v.decision === d} onChange={() => setV((s) => ({ ...s, decision: d }))} />
              {d === "APPROVE" ? "Approve" : "Deny"}
            </label>
          ))}
          {errs.decision ? <p className="text-xs text-danger" role="alert">{errs.decision}</p> : null}
        </fieldset>
        <Field id="tt-scope" label="Applies to" error={errs.scope} hint={v.scope === "exact_version" ? `Only version ${tool.version} with this digest.` : `Every tool from ${tool.publisher ?? "this publisher"}, present and future.`}>
          <Select id="tt-scope" value={v.scope} onChange={(x) => setV((s) => ({ ...s, scope: x as ToolTrustScope }))} aria-describedby="tt-scope-h">
            <option value="exact_version">This exact version</option>
            <option value="publisher_policy" disabled={!publisherOk}>All of this publisher's tools</option>
          </Select>
        </Field>
        <Field id="tt-reason" label="Reason (optional)"><Input id="tt-reason" value={v.reason} onChange={(e) => setV((s) => ({ ...s, reason: e.target.value }))} autoComplete="off" /></Field>
      </FormDialog>
    </>
  );
}
