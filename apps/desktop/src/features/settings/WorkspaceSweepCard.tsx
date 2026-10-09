import { useMutation } from "@tanstack/react-query";
import { errMessage } from "@/components/FormDialog";
import { Notice } from "@/components/product";
import { Button } from "@/components/ui/button";
import { sweepWorkspaces } from "@/services/actions";

/** Cleans workspaces left behind by a crash; unapplied agent work is preserved, never deleted silently. */
export function WorkspaceSweepCard() {
  const sweep = useMutation({ mutationFn: sweepWorkspaces });
  const r = sweep.data;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-muted-foreground">Sentinel sweeps leftover agent workspaces at startup. Run it again here after a crash. A workspace that still holds work you haven't applied or discarded is kept and listed.</p>
      <Button size="sm" variant="outline" disabled={sweep.isPending} onClick={() => sweep.mutate()}>{sweep.isPending ? "Sweeping…" : "Sweep workspaces"}</Button>
      {sweep.isError ? <Notice tone="danger" title="The sweep failed" role="alert">{errMessage(sweep.error)}</Notice> : null}
      {r ? (
        <p data-testid="sweep-result">
          {r.cleaned?.length ?? 0} cleaned, {r.preserved?.length ?? 0} kept with unapplied work, {r.failed?.length ?? 0} could not be cleaned.
        </p>
      ) : null}
    </div>
  );
}
