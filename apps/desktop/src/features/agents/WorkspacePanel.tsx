import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorState } from "@/components/ErrorState";
import { errMessage, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { DataTable, Facts, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import type { ChangeWorkspace, WorkspaceApplyPreview } from "@/lib/api/types";
import { shortSha, workspaceInfo } from "@/lib/boundary";
import { formatRelative, formatTime } from "@/lib/status";
import { applyWorkspace, discardWorkspace, previewWorkspace, workspaceQuery } from "@/services/actions";
import { changeKeys } from "@/services/changes";
import type { useActors } from "@/features/authority/useActors";

type Actors = ReturnType<typeof useActors>["actors"];

/** States in which the agent's work can still be reviewed and applied. */
const OPEN = new Set(["READY", "SEALED", "APPLY_REFUSED"]);

/**
 * The Change's Sentinel-owned workspace clone (S3). The agent edits only this clone inside its box; its work reaches the user's
 * repository only through a sealed preview and a fast-forward apply that the operator approves here.
 */
export function WorkspacePanel({ changeId, actors }: { changeId: string; actors: Actors }) {
  const q = useQuery(workspaceQuery(changeId));
  const [preview, setPreview] = useState<WorkspaceApplyPreview | null>(null);
  const previewAct = useFormAction({ run: () => previewWorkspace(changeId), invalidate: [[...changeKeys.all]], onSuccess: (p) => setPreview(p) });
  // A preview (and its approval token) belongs to one Change and one sealed state: drop it when either moves on.
  const state = q.data?.state;
  useEffect(() => { setPreview(null); }, [changeId]);
  useEffect(() => { if (state && !OPEN.has(state)) setPreview(null); }, [state]);

  if (q.isPending) return <Section title="Workspace" flush><Skeleton lines={2} label="Loading workspace" /></Section>;
  if (q.isError) {
    const e = q.error;
    if (e instanceof ApiError && (e.kind === "not_found" || e.code === "CAPABILITY_UNAVAILABLE")) {
      return (
        <Section title="Workspace" description="Where a boxed agent works.">
          <p className="text-sm text-muted-foreground" data-testid="workspace-empty">
            {e.kind === "not_found"
              ? "No workspace yet. The first boxed agent launch clones the repository into a Sentinel-owned workspace; the agent never edits your repository directly."
              : "This backend has no workspace support configured."}
          </p>
        </Section>
      );
    }
    return <ErrorState error={e} onRetry={() => q.refetch()} />;
  }
  const ws = q.data;
  const open = OPEN.has(ws.state);
  return (
    <Section
      title="Workspace"
      description="The agent edits this Sentinel-owned clone inside its box. Its work reaches your repository only through a preview you approve."
      action={
        <div className="flex items-center gap-2">
          <StatusLabel status={workspaceInfo(ws.state)} />
          {open ? <Button size="sm" variant="outline" disabled={previewAct.isPending} onClick={() => previewAct.mutate(undefined)}>{previewAct.isPending ? "Sealing…" : "Preview changes"}</Button> : null}
          {open ? <DiscardWorkspace changeId={changeId} actors={actors} onDone={() => setPreview(null)} /> : null}
        </div>
      }
    >
      <WorkspaceFacts ws={ws} />
      {previewAct.error ? <Notice tone="danger" title="Preview failed" role="alert">{errMessage(previewAct.error)}</Notice> : null}
      {preview && preview.change_id === changeId && preview.workspace_id === ws.id ? <PreviewView preview={preview} changeId={changeId} actors={actors} onApplied={() => setPreview(null)} /> : null}
    </Section>
  );
}

function WorkspaceFacts({ ws }: { ws: ChangeWorkspace }) {
  return (
    <>
      <Facts
        items={[
          { label: "Base", value: <span><code>{shortSha(ws.base_sha)}</code>{ws.base_branch ? ` on ${ws.base_branch}` : ""}</span> },
          ...(ws.sealed_sha ? [{ label: "Sealed", value: <code>{shortSha(ws.sealed_sha)}</code> }] : []),
          ...(ws.applied_sha ? [{ label: "Applied", value: <code>{shortSha(ws.applied_sha)}</code> }] : []),
          { label: "Box profile", value: <code className="break-all">{ws.profile_name}</code> },
          ...(ws.package_sid ? [{ label: "Package SID", value: <code className="break-all">{ws.package_sid}</code> }] : []),
          { label: "Runs", value: <span className="tabular-nums">{ws.runs?.length ?? 0}</span> },
          { label: "Credential staged", value: ws.credential_staged ? "Yes, for a run only (deleted after it)" : "No" },
          { label: "Updated", value: <span title={formatTime(ws.updated_at)}>{formatRelative(ws.updated_at)}</span> },
        ]}
      />
      {ws.refusal_reason ? <Notice tone="danger" title="Apply was refused">{ws.refusal_reason}</Notice> : null}
      {ws.limitations?.length ? <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{ws.limitations.map((l) => <li key={l}>{l}</li>)}</ul> : null}
    </>
  );
}

function PreviewView({ preview, changeId, actors, onApplied }: { preview: WorkspaceApplyPreview; changeId: string; actors: Actors; onApplied: () => void }) {
  const paths = preview.changed_paths ?? [];
  const commits = preview.commits ?? [];
  return (
    <div className="mt-4 space-y-3" data-testid="workspace-preview">
      <h3 className="text-sm font-medium">Preview: <code>{shortSha(preview.base_sha)}</code> → <code>{shortSha(preview.sealed_sha)}</code>{preview.user_branch ? ` onto ${preview.user_branch}` : ""}</h3>
      {preview.fast_forward_possible && preview.approval_token
        ? <Notice tone="info" title="Ready to apply">Your branch can fast-forward to the sealed commit. Nothing is written until you apply.</Notice>
        : <Notice tone="danger" title="Cannot apply" role="alert">{preview.refusal_reason ?? "A fast-forward is not possible; Sentinel never forces or merges."}</Notice>}
      {paths.length ? (
        <DataTable label="Changed paths">
          <thead><tr><th className={th}>Status</th><th className={th}>Path</th><th className={th}>Flags</th></tr></thead>
          <tbody>
            {paths.map((p) => (
              <tr key={`${p.status}:${p.path}`}>
                <td className={td}>{p.status}</td>
                <td className={`${td} mono break-all`}>{p.path}</td>
                <td className={td}>{p.flags?.length ? <span className="text-warn">{p.flags.join(", ")}</span> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      ) : <p className="text-sm text-muted-foreground">No changed paths.</p>}
      {commits.length ? (
        <ul className="space-y-1 text-[13px]">
          {commits.map((c) => <li key={c.sha}><code>{shortSha(c.sha)}</code> {c.subject} <span className="text-muted-foreground">· {c.author}</span></li>)}
          {preview.commits_truncated ? <li className="text-muted-foreground">More commits not shown.</li> : null}
        </ul>
      ) : null}
      {preview.patch ? (
        <details className="rounded-md border">
          <summary className="cursor-pointer px-3 py-2 text-[13px] text-muted-foreground">Patch{preview.patch_truncated ? " (truncated)" : ""}</summary>
          <pre className="mono max-h-96 overflow-auto whitespace-pre border-t bg-secondary px-3 py-2 text-xs" tabIndex={0} aria-label="Patch">{preview.patch}</pre>
        </details>
      ) : null}
      {preview.limitations?.length ? <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted-foreground">{preview.limitations.map((l) => <li key={l}>{l}</li>)}</ul> : null}
      {preview.fast_forward_possible && preview.approval_token
        ? <ApplyWorkspace changeId={changeId} actors={actors} token={preview.approval_token} sealed={preview.sealed_sha} onDone={onApplied} />
        : null}
    </div>
  );
}

function ApplyWorkspace({ changeId, actors, token, sealed, onDone }: { changeId: string; actors: Actors; token: string; sealed: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [actor, setActor] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = useFormAction({
    run: (_: undefined, key) => applyWorkspace(changeId, { actor_id: actor, approval_token: token }, key),
    invalidate: [[...changeKeys.all]],
    onSuccess: () => { setOpen(false); onDone(); },
  });
  return (
    <>
      <Button size="sm" onClick={() => { act.reset(); act.renewKey(); setActor(""); setErr(null); setOpen(true); }}>Apply to my repository</Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Apply the agent's work?"
        description={`Your branch fast-forwards to ${shortSha(sealed)}, exactly the sealed commit you previewed. If your branch or the workspace changed since the preview, Sentinel refuses instead of merging.`}
        confirmLabel="Apply"
        danger={false}
        pending={act.isPending}
        error={act.error}
        onConfirm={() => (actor ? (setErr(null), act.mutate(undefined)) : setErr("Choose the actor who is approving this."))}
      >
        <ActorPicker id="apply-actor" label="Approved by" actors={actors} value={actor} onChange={setActor} error={err} />
      </ConfirmDialog>
    </>
  );
}

function DiscardWorkspace({ changeId, actors, onDone }: { changeId: string; actors: Actors; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [actor, setActor] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = useFormAction({
    run: (_: undefined, key) => discardWorkspace(changeId, { actor_id: actor }, key),
    invalidate: [[...changeKeys.all]],
    onSuccess: () => { setOpen(false); onDone(); },
  });
  return (
    <>
      <Button size="sm" variant="outline" className="text-danger" onClick={() => { act.reset(); act.renewKey(); setActor(""); setErr(null); setOpen(true); }}>Discard</Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Discard the agent's work?"
        description="The workspace clone and everything the agent changed in it are deleted. Your repository is not touched."
        confirmLabel="Discard work"
        pending={act.isPending}
        error={act.error}
        onConfirm={() => (actor ? (setErr(null), act.mutate(undefined)) : setErr("Choose the actor who is doing this."))}
      >
        <ActorPicker id="discard-actor" label="Acting as" actors={actors} value={actor} onChange={setActor} error={err} />
      </ConfirmDialog>
    </>
  );
}
