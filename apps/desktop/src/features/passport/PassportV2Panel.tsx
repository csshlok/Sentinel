import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { errMessage } from "@/components/FormDialog";
import { Facts, Notice, Section, StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import type { PassportV2Issued } from "@/lib/api/types";
import { savePassportBundle, type SaveResult } from "@/lib/export";
import type { StatusInfo } from "@/lib/status";
import { formatTime } from "@/lib/status";
import { issuePassportV2 } from "@/services/actions";

const BOUNDARY: Record<string, StatusInfo> = {
  APPCONTAINER: { label: "AppContainer (every started agent run verified)", tone: "ok" },
  RESTRICTED_TOKEN_ONLY: { label: "Reduced token only (not a sandbox)", tone: "warn" },
  MIXED: { label: "Mixed (not every launch was boxed)", tone: "warn" },
  NONE: { label: "No boundary", tone: "danger" },
  UNKNOWN: { label: "Unknown", tone: "neutral" },
};
const CLAIM: Record<string, StatusInfo> = {
  PASS: { label: "PASS", tone: "ok" },
  FAIL: { label: "FAIL", tone: "danger" },
  UNKNOWN: { label: "UNKNOWN", tone: "neutral" },
  ALLOW: { label: "ALLOW", tone: "ok" },
  DENY: { label: "DENY", tone: "danger" },
  NONE: { label: "None", tone: "ok" },
  PRESENT: { label: "Present", tone: "warn" },
};
const claim = (v: string | null | undefined): StatusInfo => CLAIM[v ?? "UNKNOWN"] ?? { label: String(v), tone: "neutral" };

/** Issues the signed Passport v2 (ES256, non-exportable key) and saves the offline-verifiable `.sentinel` bundle. */
export function PassportV2Panel({ changeId }: { changeId: string }) {
  const [issued, setIssued] = useState<PassportV2Issued | null>(null);
  const [saved, setSaved] = useState<SaveResult | null>(null);
  const issue = useMutation({ mutationFn: () => issuePassportV2(changeId), onSuccess: setIssued });
  const bundle = useMutation({ mutationFn: () => savePassportBundle(changeId), onSuccess: setSaved });
  return (
    <Section
      title="Signed Passport (v2)"
      description="Signed claims about this Change with a key that cannot be exported. Recipients verify the bundle offline with `sentinel verify`, trusting your key by fingerprint."
      action={
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={issued ? "outline" : "default"} disabled={issue.isPending} onClick={() => issue.mutate()}>{issue.isPending ? "Signing…" : issued ? "Re-issue" : "Issue signed passport"}</Button>
          <Button size="sm" variant="outline" disabled={bundle.isPending} onClick={() => { setSaved(null); bundle.mutate(); }}><Download aria-hidden="true" /> {bundle.isPending ? "Preparing…" : "Save bundle"}</Button>
        </div>
      }
    >
      {issue.isError ? <Notice tone="danger" title="The passport wasn't issued" role="alert">{errMessage(issue.error)}</Notice> : null}
      {bundle.isError ? <Notice tone="danger" title="The bundle wasn't saved" role="alert">{bundle.error instanceof Error ? bundle.error.message : "Saving failed."}</Notice> : null}
      {saved?.kind === "saved" ? <Notice title="Bundle saved" role="status">Written to <code className="break-all">{saved.where}</code>.</Notice> : null}
      {issued ? <IssuedView issued={issued} /> : <p className="text-sm text-muted-foreground">Not issued in this session. Issuing signs the Change's current state; it does not change the Change.</p>}
    </Section>
  );
}

export function IssuedView({ issued }: { issued: PassportV2Issued }) {
  const p = issued.payload;
  const bearing = p.execution_bearing_changes ?? [];
  return (
    <div className="space-y-3" data-testid="passport-v2">
      <Facts
        items={[
          { label: "Execution boundary", value: <StatusLabel status={BOUNDARY[p.execution_boundary ?? "UNKNOWN"] ?? claim(p.execution_boundary)} /> },
          { label: "Confined checks", value: <StatusLabel status={claim(p.confined_checks)} /> },
          { label: "Diff exercised", value: <StatusLabel status={claim(p.diff_coverage?.diff_exercised)} /> },
          { label: "Policy", value: <span><StatusLabel status={claim(p.policy_decision)} />{p.policy_preset_name ? ` ${p.policy_preset_name}` : ""}</span> },
          { label: "Runs later", value: <StatusLabel status={claim(p.runs_later)} /> },
          { label: "Journal", value: `${p.journal_integrity}, ${p.journal_event_count} events` },
          { label: "Signer", value: <span><code className="break-all">{issued.signer_fingerprint}</code> ({issued.signer_provider})</span> },
          { label: "Payload digest", value: <code className="break-all">{issued.payload_digest}</code> },
          { label: "Issued", value: formatTime(p.issued_at) },
        ]}
      />
      {bearing.length ? (
        <div>
          <h3 className="text-sm font-medium">Changed files that run code later</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px]">{bearing.map((b) => <li key={b.path}><code className="break-all">{b.path}</code> <span className="text-muted-foreground">({b.category})</span></li>)}</ul>
        </div>
      ) : null}
      {p.policy_denials?.length ? <ul className="list-disc space-y-1 pl-5 text-[13px] text-danger">{p.policy_denials.map((d) => <li key={d}>{d}</li>)}</ul> : null}
      {p.limitations?.length ? <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{p.limitations.map((l) => <li key={l}>{l}</li>)}</ul> : null}
    </div>
  );
}
