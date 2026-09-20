import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Notice, Section } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, errorDetailLines } from "@/lib/api/client";
import type { ChangeContract, ChangeLifecycleState, ChangeView, RiskLevel } from "@/lib/api/types";
import { lifecycleInfo } from "@/lib/status";
import { GUARDS, allowedTargets, guardText } from "@/lib/lifecycle";
import { cancelChange, captureEvidence, refreshChange, transitionChange, updateContract, verifyChange } from "@/services/actions";
import { changeKeys } from "@/services/changes";

const errMessage = (e: unknown) => (e instanceof ApiError ? e.message : "The request failed.");
const TERMINAL = new Set(["CANCELLED", "STABLE", "FAILED"]);

/** Runs a mutation, then refetches everything about Changes so every screen shows the new revision. */
function useAction<V, R>(fn: (v: V) => Promise<R>, onDone?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: changeKeys.all });
      onDone?.();
    },
  });
}

function FormDialog({ open, onOpenChange, title, description, children, submit, pending, error, submitLabel, disabled }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description: string; children: ReactNode;
  submit: () => void; pending: boolean; error: unknown; submitLabel: string; disabled?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="sm:max-w-[480px]">
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (!pending && !disabled) submit(); }}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {children}
          {error ? <Notice tone="danger" title="That didn't work" role="alert">{errMessage(error)}{errorDetailLines(error).map((l) => <span key={l} className="mt-1 block">{l}</span>)}</Notice> : null}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button>
            <Button type="submit" disabled={pending || disabled}>{pending ? "Working…" : submitLabel}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ChangeActions({ change }: { change: ChangeView }) {
  const [dialog, setDialog] = useState<null | "transition" | "verify" | "cancel">(null);
  const [target, setTarget] = useState<ChangeLifecycleState | "">("");
  const [reason, setReason] = useState("");
  const [exe, setExe] = useState("");
  const [args, setArgs] = useState("");
  const close = () => { setDialog(null); setReason(""); setTarget(""); };
  // Cancelling has its own action with its own confirmation, so it is not offered as a plain state move.
  const moves = (change.allowed_next_states ?? allowedTargets(change.lifecycle_state)).filter((s) => s !== "CANCELLED");
  const revision = change.revision ?? 0;
  const closed = TERMINAL.has(change.lifecycle_state ?? "");

  const refresh = useAction(() => refreshChange(change.id));
  const transition = useAction(() => transitionChange(change.id, { expected_revision: revision, target_state: target as ChangeLifecycleState, reason: reason.trim() || null }), close);
  const cancel = useAction(() => cancelChange(change.id, { expected_revision: revision, reason: reason.trim() || null }), close);
  const verify = useAction(() => verifyChange(change.id, { executable: exe.trim(), args: args.trim() ? args.trim().split(/\s+/) : [] }), () => { setDialog(null); });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Change actions">
        <Button variant="outline" size="sm" onClick={() => refresh.mutate(undefined)} disabled={refresh.isPending}>
          {refresh.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />} Refresh
        </Button>
        <Button variant="outline" size="sm" onClick={() => setDialog("verify")} disabled={closed}>Run verification</Button>
        <Button variant="outline" size="sm" onClick={() => setDialog("transition")} disabled={closed || moves.length === 0}>Change state</Button>
        <Button variant="ghost" size="sm" onClick={() => setDialog("cancel")} disabled={closed}>Cancel Change</Button>
      </div>
      {refresh.isError ? <Notice tone="danger" title="Refresh failed" role="alert">{errMessage(refresh.error)}</Notice> : null}

      <FormDialog open={dialog === "transition"} onOpenChange={(o) => !o && close()} title="Change state" description="Only moves the backend allows from the current state are listed. Some need conditions to be true first."
        submit={() => transition.mutate(undefined)} pending={transition.isPending} error={transition.error} submitLabel="Move" disabled={!target}>
        <div className="grid gap-1.5">
          <Label htmlFor="ts">New state</Label>
          <select id="ts" value={target} onChange={(e) => setTarget(e.target.value as ChangeLifecycleState)} className="h-9 rounded-md border border-input bg-card px-3 text-sm">
            <option value="">Choose a state…</option>
            {moves.map((s) => <option key={s} value={s}>{lifecycleInfo(s).label}</option>)}
          </select>
          {target && GUARDS[target] ? (
            <div className="rounded-md bg-secondary px-3 py-2 text-[13px]">
              <p className="font-medium">Needs to be true:</p>
              <ul className="mt-1 list-disc pl-5 text-muted-foreground">{GUARDS[target]!.map((g) => <li key={g}>{guardText(g)}</li>)}</ul>
            </div>
          ) : null}
        </div>
        <div className="grid gap-1.5"><Label htmlFor="tr">Reason (optional)</Label><Input id="tr" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
      </FormDialog>

      <FormDialog open={dialog === "cancel"} onOpenChange={(o) => !o && close()} title="Cancel this Change?" description="The Change is kept for the record but can no longer progress."
        submit={() => cancel.mutate(undefined)} pending={cancel.isPending} error={cancel.error} submitLabel="Cancel Change">
        <div className="grid gap-1.5"><Label htmlFor="cr">Reason (optional)</Label><Input id="cr" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
      </FormDialog>

      <FormDialog open={dialog === "verify"} onOpenChange={(o) => !o && setDialog(null)} title="Run verification" description="Runs one command in the repository and records the result. It can modify the repository, depending on the command."
        submit={() => verify.mutate(undefined)} pending={verify.isPending} error={verify.error} submitLabel="Run" disabled={!exe.trim()}>
        <div className="grid gap-1.5"><Label htmlFor="ve">Command</Label><Input id="ve" value={exe} onChange={(e) => setExe(e.target.value)} placeholder="pytest" className="font-mono text-[13px]" /></div>
        <div className="grid gap-1.5"><Label htmlFor="va">Arguments</Label><Input id="va" value={args} onChange={(e) => setArgs(e.target.value)} placeholder="-q tests/" className="font-mono text-[13px]" /></div>
      </FormDialog>
    </div>
  );
}

export function CaptureEvidence({ changeId }: { changeId: string }) {
  const [note, setNote] = useState<string[] | null>(null);
  const run = (kind: "baseline" | "current") => useCapture.mutate(kind);
  const useCapture = useAction((k: "baseline" | "current") => captureEvidence(changeId, k).then((r) => setNote(r.limitations ?? [])));
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={useCapture.isPending} onClick={() => run("baseline")}>Capture baseline</Button>
        <Button size="sm" variant="outline" disabled={useCapture.isPending} onClick={() => run("current")}>Capture current</Button>
      </div>
      {useCapture.isError ? <Notice tone="danger" title="Capture failed" role="alert">{errMessage(useCapture.error)}</Notice> : null}
      {note && note.length > 0 ? <Notice title="Limitations of this capture">{note.join(" ")}</Notice> : null}
    </div>
  );
}

const LINES = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);
type ListKey = "allowed_paths" | "forbidden_paths" | "required_checks" | "expected_outcomes" | "authority_ceiling" | "allowed_provider_operations";
const FIELDS: { key: ListKey; label: string; hint: string }[] = [
  { key: "allowed_paths", label: "Allowed paths", hint: "One glob per line. Empty means no path allowlist." },
  { key: "forbidden_paths", label: "Forbidden paths", hint: "One glob per line." },
  { key: "required_checks", label: "Required checks", hint: "One check per line." },
  { key: "expected_outcomes", label: "Expected outcomes", hint: "One outcome per line." },
  { key: "authority_ceiling", label: "Authority ceiling", hint: "One scope per line." },
  { key: "allowed_provider_operations", label: "Provider operations", hint: "One operation per line." },
];
const RISKS: RiskLevel[] = ["UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

/** Revision-aware editor: a stale revision (409) is explained and the user's draft is kept. */
export function ContractEditor({ change, onDone }: { change: ChangeView; onDone: () => void }) {
  const c = change.contract as ChangeContract;
  const [draft, setDraft] = useState<Record<ListKey, string>>(() => Object.fromEntries(FIELDS.map((f) => [f.key, ((c?.[f.key] as string[]) ?? []).join("\n")])) as Record<ListKey, string>);
  const [risk, setRisk] = useState<RiskLevel>(c?.max_risk ?? "UNKNOWN");
  const [recovery, setRecovery] = useState(Boolean(c?.recovery_allowed));
  const save = useAction(
    () => updateContract(change.id, { expected_revision: change.revision ?? 0, contract: { ...c, ...Object.fromEntries(FIELDS.map((f) => [f.key, LINES(draft[f.key])])), max_risk: risk, recovery_allowed: recovery } as ChangeContract }),
    onDone,
  );
  const conflict = save.error instanceof ApiError && save.error.kind === "conflict";
  return (
    <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); if (!save.isPending) save.mutate(undefined); }}>
      {save.isError ? (
        <Notice tone={conflict ? "warn" : "danger"} title={conflict ? "This Change was updated elsewhere" : "The contract wasn't saved"} role="alert">
          {conflict ? "Your draft is kept below. Cancel to reload the latest contract, then re-apply your edits." : errMessage(save.error)}
        </Notice>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-2">
        {FIELDS.map((f) => (
          <Section key={f.key} title={f.label} description={f.hint}>
            <Textarea aria-label={f.label} value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} className="mono min-h-[84px] text-[13px]" />
          </Section>
        ))}
      </div>
      <Section title="Limits">
        <div className="flex flex-wrap items-center gap-6">
          <div className="grid gap-1.5"><Label htmlFor="mr">Max risk</Label>
            <select id="mr" value={risk} onChange={(e) => setRisk(e.target.value as RiskLevel)} className="h-9 rounded-md border border-input bg-card px-3 text-sm">{RISKS.map((r) => <option key={r}>{r}</option>)}</select></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={recovery} onChange={(e) => setRecovery(e.target.checked)} /> Allow recovery</label>
        </div>
      </Section>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save contract"}</Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={save.isPending}>Cancel</Button>
      </div>
    </form>
  );
}

