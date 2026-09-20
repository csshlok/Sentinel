import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, Select, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { DataTable, EmptyState, Notice, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useActors } from "@/features/authority/useActors";
import type { ChangeView } from "@/lib/api/types";
import { knownGrants, markGrantRevoked, rememberGrant } from "@/lib/known";
import { formatRelative, formatTime, outcomeInfo, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { closePull, createGrant, createPull, githubStatusQuery, outcomesQuery, refreshOutcomes, revokeGrant } from "@/services/actions";
import { changeDetailQuery, changeKeys } from "@/services/changes";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { GithubConnection } from "./GithubConnection";
import { KIND_LABEL, groupOutcomes } from "./outcomes";

const GRANT_SCOPES = ["github.repo.read", "github.pr.create", "github.pr.close"];

export function DeliveryTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const change = useQuery(changeDetailQuery(changeId));
  const outcomes = useQuery(outcomesQuery(changeId));
  const status = useQuery(githubStatusQuery());
  const { actors } = useActors(changeId);
  const [grantVersion, setGrantVersion] = useState(0);
  void grantVersion;
  const grants = knownGrants(changeId);
  const refreshGrants = () => setGrantVersion((v) => v + 1);

  if (outcomes.isPending || change.isPending) return <Section flush><Skeleton lines={3} label="Loading delivery" /></Section>;
  if (outcomes.isError) return <ErrorState error={outcomes.error} onRetry={() => outcomes.refetch()} />;
  if (change.isError) return <ErrorState error={change.error} onRetry={() => change.refetch()} />;

  const c = change.data;
  const groups = groupOutcomes(outcomes.data.items ?? [], c.git_summary?.head_sha);
  const connected = status.data?.configured === true;
  const usable = grants.filter((g) => !g.revoked && new Date(g.expires_at).getTime() > Date.now());

  return (
    <>
      <Section title="GitHub" description="Pull requests and CI state come from GitHub through a scoped grant, never a raw token.">
        <GithubConnection />
      </Section>

      <div className="flex flex-wrap gap-2" role="toolbar" aria-label="Delivery actions">
        <CreatePull change={c} actors={actors} grants={usable} disabled={!connected} />
        <RefreshOutcomes changeId={changeId} actors={actors} grants={usable} disabled={!connected} />
        <ClosePull changeId={changeId} actors={actors} grants={usable} disabled={!connected} />
        <NewGrant changeId={changeId} actors={actors} disabled={!connected} onDone={refreshGrants} />
      </div>
      {!connected && status.isSuccess ? <Notice title="Connect GitHub first">Pull-request actions need a connection. Local evidence and outcomes already recorded stay visible.</Notice> : null}

      <Section title="Outcomes" description={`For the current commit ${shortSha(c.git_summary?.head_sha)}. The newest observation of each kind is what counts.`} flush>
        {groups.length === 0 ? (
          <EmptyState title="No outcomes recorded">Create a pull request or refresh outcomes once GitHub is connected and a grant exists.</EmptyState>
        ) : (
          <DataTable label="Outcomes">
            <thead>
              <tr>
                <th className={th}>Kind</th>
                <th className={th}>Latest</th>
                <th className={th}>Repository</th>
                <th className={th}>Commit</th>
                <th className={th}>Observed</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.kind}>
                  <td className={cn(td, "font-medium")}>{KIND_LABEL[g.kind]}</td>
                  <td className={td}>
                    <StatusLabel status={outcomeInfo(g.latest.status)} />
                    {g.supersedesPass ? <p className="mt-1 max-w-[30ch] text-xs text-muted-foreground">Newer than an earlier pass, which no longer counts.</p> : null}
                  </td>
                  <td className={cn(td, "break-all")}>{g.latest.repository}<span className="block text-xs text-muted-foreground">{g.latest.provider_reference}</span></td>
                  <td className={td}>
                    <code title={g.latest.head_sha}>{shortSha(g.latest.head_sha)}</code>
                    {g.stale ? <p className="mt-1 text-xs text-warn">Not the current commit</p> : null}
                  </td>
                  <td className={td} title={formatTime(g.latest.observed_at)}>{formatRelative(g.latest.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>

      <Section title="Grants made from this app" description="A grant lets one actor use the connection for chosen scopes, for a limited time. The API can't list grants, so only the ones created here are shown.">
        {grants.length === 0 ? (
          <p className="text-sm text-muted-foreground">None yet.</p>
        ) : (
          <ul className="divide-y text-sm">
            {grants.map((g) => (
              <GrantRow key={g.id} changeId={changeId} grant={g} onChanged={refreshGrants} />
            ))}
          </ul>
        )}
      </Section>
      <p className="text-xs leading-5 text-muted-foreground">Outcomes are tied to a repository and commit. An outcome for a different commit doesn't describe the current one. The runtime doesn't intercept an agent's own GitHub calls.</p>
    </>
  );
}

type Grants = ReturnType<typeof knownGrants>;

function GrantRow({ changeId, grant, onChanged }: { changeId: string; grant: Grants[number]; onChanged: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const expired = new Date(grant.expires_at).getTime() <= Date.now();
  const revoke = useFormAction({ run: () => revokeGrant(changeId, grant.id), invalidate: [[...changeKeys.all]], onSuccess: () => { markGrantRevoked(grant.id); onChanged(); setConfirm(false); } });
  const state = grant.revoked ? { label: "Revoked", tone: "danger" as const } : expired ? { label: "Expired", tone: "warn" as const } : { label: "Active", tone: "ok" as const };
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <code className="text-xs text-muted-foreground" title={grant.id}>{grant.id.slice(0, 8)}</code>
        <span className="ml-2">{grant.scopes.join(", ")}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground" title={formatTime(grant.expires_at)}>expires {formatRelative(grant.expires_at)}</span>
        <StatusLabel status={state} />
        {state.label === "Active" ? <Button size="sm" variant="ghost" className="text-danger" onClick={() => { revoke.reset(); setConfirm(true); }}>Revoke</Button> : null}
      </div>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Revoke this grant?" description={`The actor can no longer use GitHub for ${grant.scopes.join(", ")} on this Change.`} confirmLabel="Revoke grant" pending={revoke.isPending} error={revoke.error} onConfirm={() => revoke.mutate(undefined)} />
    </li>
  );
}

function GrantPicker({ id, grants, value, onChange, error }: { id: string; grants: Grants; value: string; onChange: (v: string) => void; error?: string | null }) {
  return (
    <Field id={id} label="Grant" error={error} hint={grants.length === 0 ? "No usable grant made from this app. Create one first." : undefined}>
      <Select id={id} value={value} onChange={onChange} disabled={grants.length === 0} aria-describedby={`${id}-h`}>
        <option value="">Select a grant…</option>
        {grants.map((g) => <option key={g.id} value={g.id}>{`${g.id.slice(0, 8)} · ${g.scopes.join(", ")}`}</option>)}
      </Select>
    </Field>
  );
}

function NewGrant({ changeId, actors, disabled, onDone }: { changeId: string; actors: ReturnType<typeof useActors>["actors"]; disabled: boolean; onDone: () => void }) {
  const [actor, setActor] = useState("");
  const [scopes, setScopes] = useState<string[]>(["github.repo.read", "github.pr.create"]);
  const [ttl, setTtl] = useState("3600");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setActor(""); setScopes(["github.repo.read", "github.pr.create"]); setTtl("3600"); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({ run: (b: Parameters<typeof createGrant>[1], key) => createGrant(changeId, b, key), invalidate: [[...changeKeys.all]], onSuccess: (g) => { rememberGrant(g); onDone(); dlg.close(); } });
  return (
    <>
      <Button size="sm" variant="outline" onClick={dlg.show} disabled={disabled}>Create grant</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Create a GitHub grant"
        description="Let one actor use the connected GitHub account for chosen scopes, for a limited time. The actor must already hold matching authority on this Change."
        submitLabel="Create grant"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!actor) e.actor = "Choose the actor receiving the grant.";
          if (scopes.length === 0) e.scopes = "Pick at least one scope.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: actor, scopes, ttl_seconds: Number(ttl) });
        }}
      >
        <ActorPicker id="gr-actor" label="Grant to" actors={actors} value={actor} onChange={setActor} error={errs.actor} />
        <fieldset className="grid gap-1.5">
          <legend className="text-sm font-medium">Scopes</legend>
          {GRANT_SCOPES.map((s) => (
            <label key={s} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={scopes.includes(s)} onChange={() => setScopes((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]))} />
              <code>{s}</code>
            </label>
          ))}
          {errs.scopes ? <p className="text-xs text-danger" role="alert">{errs.scopes}</p> : null}
        </fieldset>
        <Field id="gr-ttl" label="Lasts">
          <Select id="gr-ttl" value={ttl} onChange={setTtl}>
            <option value="900">15 minutes</option>
            <option value="3600">1 hour</option>
            <option value="28800">8 hours</option>
          </Select>
        </Field>
      </FormDialog>
    </>
  );
}

function CreatePull({ change, actors, grants, disabled }: { change: ChangeView; actors: ReturnType<typeof useActors>["actors"]; grants: Grants; disabled: boolean }) {
  const [v, setV] = useState({ actor: "", grant: "", title: "", head: "", base: "main" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setV({ actor: "", grant: "", title: change.title, head: change.git_summary?.branch ?? "", base: "main" }); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({
    run: (b: Omit<Parameters<typeof createPull>[1], "idempotency_key">, key) => createPull(change.id, { ...b, idempotency_key: key }),
    invalidate: [[...changeKeys.all]],
    onSuccess: () => dlg.close(),
  });
  const set = (k: keyof typeof v) => (val: string) => setV((s) => ({ ...s, [k]: val }));
  return (
    <>
      <Button size="sm" onClick={dlg.show} disabled={disabled}>Create pull request</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Create a pull request"
        description="Opens a pull request on GitHub for this Change. Review the summary below before you continue."
        submitLabel="Create pull request"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!v.actor) e.actor = "Choose who is creating it.";
          if (!v.grant) e.grant = "Choose a grant that allows github.pr.create.";
          if (!v.title.trim()) e.title = "Enter a title.";
          if (!v.head.trim()) e.head = "Enter the branch with your changes.";
          if (!v.base.trim()) e.base = "Enter the branch to merge into.";
          if (v.head.trim() && v.head.trim() === v.base.trim()) e.base = "The base and head branches must differ.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: v.actor, grant_id: v.grant, title: v.title.trim(), head_branch: v.head.trim(), base_branch: v.base.trim() });
        }}
      >
        <ActorPicker id="pr-actor" label="Created by" actors={actors} value={v.actor} onChange={set("actor")} error={errs.actor} />
        <GrantPicker id="pr-grant" grants={grants} value={v.grant} onChange={set("grant")} error={errs.grant} />
        <Field id="pr-title" label="Title" error={errs.title}><Input id="pr-title" value={v.title} onChange={(e) => set("title")(e.target.value)} aria-describedby="pr-title-h" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field id="pr-head" label="From branch" error={errs.head}><Input id="pr-head" value={v.head} onChange={(e) => set("head")(e.target.value)} className="mono text-[13px]" aria-describedby="pr-head-h" /></Field>
          <Field id="pr-base" label="Into branch" error={errs.base}><Input id="pr-base" value={v.base} onChange={(e) => set("base")(e.target.value)} className="mono text-[13px]" aria-describedby="pr-base-h" /></Field>
        </div>
        <Notice title="What will happen">
          {v.head && v.base ? <>A pull request titled “{v.title || "…"}” will be opened from <code>{v.head}</code> into <code>{v.base}</code> for commit <code>{shortSha(change.git_summary?.head_sha)}</code>. If you retry after a timeout, the same request is recognized and not duplicated.</> : "Fill in both branches to see the summary."}
        </Notice>
      </FormDialog>
    </>
  );
}

function RefreshOutcomes({ changeId, actors, grants, disabled }: { changeId: string; actors: ReturnType<typeof useActors>["actors"]; grants: Grants; disabled: boolean }) {
  const [v, setV] = useState({ actor: "", grant: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setV({ actor: "", grant: "" }); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({ run: (b: { actor_id: string; grant_id: string }) => refreshOutcomes(changeId, b), invalidate: [[...changeKeys.all]], onSuccess: () => dlg.close() });
  return (
    <>
      <Button size="sm" variant="outline" onClick={dlg.show} disabled={disabled}>Refresh outcomes</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Refresh outcomes"
        description="Fetch the current pull request and CI state from GitHub for this commit."
        submitLabel="Refresh"
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!v.actor) e.actor = "Choose who is refreshing.";
          if (!v.grant) e.grant = "Choose a grant that allows github.repo.read.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: v.actor, grant_id: v.grant });
        }}
      >
        <ActorPicker id="ro-actor" label="Refreshed by" actors={actors} value={v.actor} onChange={(x) => setV((s) => ({ ...s, actor: x }))} error={errs.actor} />
        <GrantPicker id="ro-grant" grants={grants} value={v.grant} onChange={(x) => setV((s) => ({ ...s, grant: x }))} error={errs.grant} />
      </FormDialog>
    </>
  );
}

function ClosePull({ changeId, actors, grants, disabled }: { changeId: string; actors: ReturnType<typeof useActors>["actors"]; grants: Grants; disabled: boolean }) {
  const [v, setV] = useState({ actor: "", grant: "" });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setV({ actor: "", grant: "" }); setErrs({}); run.reset(); run.renewKey(); });
  const run = useFormAction({ run: (b: { actor_id: string; grant_id: string }, key) => closePull(changeId, { ...b, idempotency_key: key }), invalidate: [[...changeKeys.all]], onSuccess: () => dlg.close() });
  return (
    <>
      <Button size="sm" variant="ghost" className="text-danger" onClick={dlg.show} disabled={disabled}>Close pull request</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Close the pull request?"
        description="Closes the pull request this Change opened on GitHub. It can be reopened on GitHub, but not from here."
        submitLabel="Close pull request"
        danger
        pending={run.isPending}
        error={run.error}
        submit={() => {
          const e: Record<string, string> = {};
          if (!v.actor) e.actor = "Choose who is closing it.";
          if (!v.grant) e.grant = "Choose a grant that allows github.pr.close.";
          setErrs(e);
          if (Object.keys(e).length) return;
          run.mutate({ actor_id: v.actor, grant_id: v.grant });
        }}
      >
        <ActorPicker id="cp-actor" label="Closed by" actors={actors} value={v.actor} onChange={(x) => setV((s) => ({ ...s, actor: x }))} error={errs.actor} />
        <GrantPicker id="cp-grant" grants={grants} value={v.grant} onChange={(x) => setV((s) => ({ ...s, grant: x }))} error={errs.grant} />
      </FormDialog>
    </>
  );
}
