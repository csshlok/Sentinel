import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ErrorState } from "@/components/ErrorState";
import { Field, FormDialog, Select, useDialogState, useFormAction } from "@/components/FormDialog";
import { ActorPicker } from "@/components/pickers";
import { Chips, DataTable, EmptyState, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ActorKind, Delegation } from "@/lib/api/types";
import { rememberActor } from "@/lib/known";
import { delegationInfo, formatRelative, formatTime } from "@/lib/status";
import { cn } from "@/lib/utils";
import { createActor, createDelegation, delegationsQuery, revokeDelegation } from "@/services/actions";
import { changeKeys } from "@/services/changes";
import { useActors } from "./useActors";

/** Scope names the backend's policy layer checks today (from `_enforce_policy` call sites). Suggestions only; any scope may be typed. */
export const SCOPE_CHOICES: { scope: string; label: string }[] = [
  { scope: "agent.launch", label: "Launch a top-level agent" },
  { scope: "agent.attach", label: "Attach a top-level agent" },
  { scope: "agent.stop", label: "Stop a top-level agent" },
  { scope: "assurance.run", label: "Run assurance checks" },
  { scope: "change.fork", label: "Fork the Change" },
  { scope: "change.legacy_verify", label: "Run a verification command" },
  { scope: "github.repo.read", label: "Read repository state on GitHub" },
  { scope: "github.pr.create", label: "Create a pull request" },
  { scope: "github.pr.close", label: "Close a pull request" },
  { scope: "recovery.execute", label: "Execute an approved recovery" },
];

const TTL: { label: string; seconds: number }[] = [
  { label: "1 hour", seconds: 3_600 },
  { label: "8 hours", seconds: 28_800 },
  { label: "1 day", seconds: 86_400 },
  { label: "7 days", seconds: 604_800 },
];

/** Parses the scope box: one scope per line or comma-separated; trims, drops blanks and duplicates. */
export const parseScopes = (raw: string): string[] => [...new Set(raw.split(/[\n,]/).map((s) => s.trim()).filter(Boolean))];

export function AuthorityTab() {
  const changeId = useParams({ from: "/changes/$changeId" }).changeId;
  const q = useQuery(delegationsQuery(changeId));
  const { actors, refresh, nameOf, total, complete } = useActors(changeId);

  if (q.isPending) return <Section flush><Skeleton lines={3} label="Loading authority" /></Section>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const delegations = q.data.items ?? [];

  return (
    <>
      <div className="flex flex-wrap gap-2" role="toolbar" aria-label="Authority actions">
        <NewDelegation changeId={changeId} actors={actors} />
        <NewActor onCreated={refresh} />
      </div>

      <Section title="Delegations" description="Who may do what on this Change, until when." flush>
        {delegations.length === 0 ? (
          <EmptyState title="No one has authority yet">
            A Change can't become Active until a valid delegation exists. Create an actor, then delegate scopes to them.
          </EmptyState>
        ) : (
          <DataTable label="Delegations">
            <thead>
              <tr>
                <th className={th}>Grantee</th>
                <th className={th}>Granted by</th>
                <th className={th}>Scopes</th>
                <th className={th}>State</th>
                <th className={th}>Uses</th>
                <th className={th}>Expires</th>
                <th className={th}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {delegations.map((d) => (
                <DelegationRow key={d.id} d={d} nameOf={nameOf} />
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>

      <Section
        title="Actors"
        description={complete ? `${total ?? actors.length} registered${total != null && total > actors.length ? `, showing the first ${actors.length}` : ""}.` : "This backend can't list actors, so these come from this Change's delegations and actors created here."}
      >
        {actors.length === 0 ? (
          <p className="text-sm text-muted-foreground">None yet.</p>
        ) : (
          <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
            {actors.map((a) => (
              <li key={a.id} className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 break-words">{a.display_name} <span className="text-muted-foreground">· {a.kind.toLowerCase()}</span></span>
                <code className="shrink-0 text-xs text-muted-foreground" title={a.id}>{a.id.slice(0, 8)}</code>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <p className="text-xs leading-5 text-muted-foreground">Authority is checked by the backend on every action; this screen only records it. An expired, exhausted or revoked delegation no longer applies.</p>
    </>
  );
}

function DelegationRow({ d, nameOf }: { d: Delegation; nameOf: (id: string) => string }) {
  const info = delegationInfo(d);
  const [confirm, setConfirm] = useState(false);
  const revoke = useFormAction({ run: () => revokeDelegation(d.id), invalidate: [[...changeKeys.all]], onSuccess: () => setConfirm(false) });
  return (
    <tr>
      <td className={cn(td, "break-words")}>{nameOf(d.grantee_id)}</td>
      <td className={cn(td, "break-words")}>{nameOf(d.grantor_id)}</td>
      <td className={cn(td, "min-w-[19rem]")}><Chips items={d.scopes} empty="None" /></td>
      <td className={td}><StatusLabel status={info} /></td>
      <td className={cn(td, "whitespace-nowrap tabular-nums")}>{d.uses}{d.use_limit != null ? ` / ${d.use_limit}` : ""}</td>
      <td className={cn(td, "whitespace-nowrap")} title={formatTime(d.expires_at)}>{d.revoked_at ? `revoked ${formatRelative(d.revoked_at)}` : formatRelative(d.expires_at)}</td>
      <td className={td}>
        {info.label === "Active" ? (
          <>
            <Button size="sm" variant="ghost" className="text-danger" onClick={() => { revoke.reset(); setConfirm(true); }}>Revoke</Button>
            <ConfirmDialog
              open={confirm}
              onOpenChange={setConfirm}
              title={`Revoke ${nameOf(d.grantee_id)}'s authority?`}
              description={`They lose ${d.scopes.join(", ") || "all scopes"} on this Change immediately. This can't be undone; issue a new delegation to restore access.`}
              confirmLabel="Revoke authority"
              pending={revoke.isPending}
              error={revoke.error}
              onConfirm={() => revoke.mutate(undefined)}
            />
          </>
        ) : null}
      </td>
    </tr>
  );
}

function NewActor({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ActorKind>("HUMAN");
  const [err, setErr] = useState<string | null>(null);
  const dlg = useDialogState(() => { setName(""); setKind("HUMAN"); setErr(null); create.reset(); create.renewKey(); });
  const create = useFormAction({
    run: (v: { display_name: string; kind: ActorKind }, key) => createActor(v, key),
    invalidate: [["actors"]],
    onSuccess: (actor) => { rememberActor(actor); onCreated(); dlg.close(); },
  });
  return (
    <>
      <Button size="sm" variant="outline" onClick={dlg.show}>Create actor</Button>
      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Create actor"
        description="Register a person, agent or service that can be given authority."
        submitLabel="Create actor"
        pending={create.isPending}
        error={create.error}
        submit={() => {
          if (!name.trim()) return setErr("Enter a display name.");
          setErr(null);
          create.mutate({ display_name: name.trim(), kind });
        }}
      >
        <Field id="actor-name" label="Display name" error={err}>
          <Input id="actor-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" aria-describedby="actor-name-h" />
        </Field>
        <Field id="actor-kind" label="Kind">
          <Select id="actor-kind" value={kind} onChange={(v) => setKind(v as ActorKind)}>
            <option value="HUMAN">Human</option>
            <option value="AGENT">Agent</option>
            <option value="SERVICE">Service</option>
          </Select>
        </Field>
      </FormDialog>
    </>
  );
}

function NewDelegation({ changeId, actors }: { changeId: string; actors: ReturnType<typeof useActors>["actors"] }) {
  const [grantor, setGrantor] = useState("");
  const [grantee, setGrantee] = useState("");
  const [scopes, setScopes] = useState("");
  const [ttl, setTtl] = useState(3_600);
  const [limit, setLimit] = useState("");
  const [errs, setErrs] = useState<Record<string, string>>({});
  const dlg = useDialogState(() => { setGrantor(""); setGrantee(""); setScopes(""); setTtl(3_600); setLimit(""); setErrs({}); create.reset(); create.renewKey(); });
  const create = useFormAction({
    run: (v: Parameters<typeof createDelegation>[0], key) => createDelegation(v, key),
    invalidate: [[...changeKeys.all], ["actors"]],
    onSuccess: () => dlg.close(),
  });
  const list = parseScopes(scopes);
  const toggle = (scope: string) => setScopes(list.includes(scope) ? list.filter((s) => s !== scope).join("\n") : [...list, scope].join("\n"));

  const submit = () => {
    const e: Record<string, string> = {};
    if (!grantor) e.grantor = "Choose who grants this authority.";
    if (!grantee) e.grantee = "Choose who receives it.";
    else if (grantee === grantor) e.grantee = "An actor can't delegate authority to itself. Choose someone else.";
    if (list.length === 0) e.scopes = "Pick or enter at least one scope.";
    if (limit.trim() && !/^[1-9]\d*$/.test(limit.trim())) e.limit = "Use a whole number of 1 or more, or leave blank.";
    setErrs(e);
    if (Object.keys(e).length) return;
    create.mutate({ change_id: changeId, grantor_id: grantor, grantee_id: grantee, scopes: list, ttl_seconds: ttl, use_limit: limit.trim() ? Number(limit) : null });
  };

  return (
    <>
      <Button size="sm" onClick={dlg.show}>Delegate authority</Button>
      <FormDialog open={dlg.open} onOpenChange={dlg.onOpenChange} title="Delegate authority" description="Give an actor scoped, time-limited authority on this Change." submitLabel="Delegate" pending={create.isPending} error={create.error} submit={submit}>
        <ActorPicker id="dg-grantor" label="Granted by" actors={actors} value={grantor} onChange={setGrantor} error={errs.grantor} />
        <ActorPicker id="dg-grantee" label="Granted to" actors={actors} value={grantee} onChange={setGrantee} error={errs.grantee} />
        <fieldset className="grid gap-1.5">
          <legend className="text-sm font-medium">Scopes</legend>
          <div className="grid gap-1">
            {SCOPE_CHOICES.map((s) => (
              <label key={s.scope} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={list.includes(s.scope)} onChange={() => toggle(s.scope)} />
                <span>{s.label}</span> <code className="text-xs text-muted-foreground">{s.scope}</code>
              </label>
            ))}
          </div>
          {errs.scopes ? <p className="text-xs text-danger" role="alert">{errs.scopes}</p> : <p className="text-xs text-muted-foreground">The raw scope names are what the backend checks.</p>}
        </fieldset>
        <div className="grid grid-cols-2 gap-3">
          <Field id="dg-ttl" label="Lasts">
            <Select id="dg-ttl" value={String(ttl)} onChange={(v) => setTtl(Number(v))}>
              {TTL.map((t) => <option key={t.seconds} value={t.seconds}>{t.label}</option>)}
            </Select>
          </Field>
          <Field id="dg-limit" label="Use limit (optional)" error={errs.limit} hint="Blank means unlimited.">
            <Input id="dg-limit" inputMode="numeric" value={limit} onChange={(e) => setLimit(e.target.value)} aria-describedby="dg-limit-h" />
          </Field>
        </div>
      </FormDialog>
    </>
  );
}
