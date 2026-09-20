import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useLocation, useParams } from "@tanstack/react-router";
import { ArrowLeft, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ErrorState";
import { Chips, DataTable, EmptyState, Facts, PageHeader, PathText, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import type { ChangeContract, ChangeLifecycleState, ChangeView } from "@/lib/api/types";
import { LIFECYCLE_PATH, formatRelative, formatTime, lifecycleInfo, reviewInfo, riskInfo, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { ChangeActions, ContractEditor } from "./Actions";
import { DeleteChange } from "./DeleteChange";
import { useEffect, useRef, useState } from "react";
import { changeDetailQuery, eventsQuery } from "@/services/changes";

function useChangeId() {
  return useParams({ from: "/changes/$changeId" }).changeId;
}

const tabClass = "-mb-px whitespace-nowrap border-b-2 border-transparent px-3.5 py-2 text-sm text-muted-foreground hover:text-foreground";

export function ChangeWorkspace() {
  const changeId = useChangeId();
  const change = useQuery(changeDetailQuery(changeId));
  const tabsRef = useRef<HTMLElement | null>(null);
  const pathname = useLocation({ select: (l) => l.pathname });
  // At narrow widths the strip scrolls; keep the current tab visible after navigating.
  useEffect(() => {
    tabsRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }, [pathname, change.isSuccess]);

  const back = (
    <Link to="/changes" className="inline-flex items-center gap-1.5 rounded-sm text-[13px] text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-3.5" aria-hidden="true" /> Changes
    </Link>
  );

  if (change.isPending) {
    return (
      <>
        {back}
        <Section flush>
          <Skeleton lines={4} label="Loading Change" />
        </Section>
      </>
    );
  }
  if (change.isError) {
    return (
      <>
        {back}
        <ErrorState error={change.error} onRetry={() => change.refetch()} />
      </>
    );
  }

  const data = change.data;
  const tabs = [
    { to: "/changes/$changeId", label: "Overview", exact: true },
    { to: "/changes/$changeId/contract", label: "Contract" },
    { to: "/changes/$changeId/evidence", label: "Evidence" },
    { to: "/changes/$changeId/assurance", label: "Assurance" },
    { to: "/changes/$changeId/agents", label: "Agents" },
    { to: "/changes/$changeId/delivery", label: "Delivery" },
    { to: "/changes/$changeId/authority", label: "Authority" },
    { to: "/changes/$changeId/recovery", label: "Recovery" },
    { to: "/changes/$changeId/passport", label: "Passport" },
    { to: "/changes/$changeId/timeline", label: "Timeline" },
  ] as const;

  return (
    <>
      {back}
      <PageHeader
        title={data.title}
        description={<PathText path={data.repository_path} />}
        actions={
          <>
            <StatusLabel status={lifecycleInfo(data.lifecycle_state)} />
            <StatusLabel status={riskInfo(data.risk_level)} />
            <DeleteChange changeId={changeId} title={data.title} />
          </>
        }
      />
      {data.forked_from_change_id ? (
        <p className="text-[13px] text-muted-foreground">
          Forked from{" "}
          <Link to="/changes/$changeId" params={{ changeId: data.forked_from_change_id }} className="underline underline-offset-2">
            {data.forked_from_change_id.slice(0, 8)}
          </Link>
          {data.forked_from_checkpoint_id ? <> at checkpoint <code>{data.forked_from_checkpoint_id.slice(0, 8)}</code></> : null}
        </p>
      ) : null}
      <nav ref={tabsRef} className="quiet-scroll flex gap-1 overflow-x-auto border-b" aria-label="Change sections">
        {tabs.map((tab) => (
          <Link
            key={tab.to}
            to={tab.to}
            params={{ changeId }}
            activeOptions={{ exact: "exact" in tab }}
            className={tabClass}
            activeProps={{ className: cn(tabClass, "border-primary font-medium text-[var(--text-primary)]"), "aria-current": "page" }}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      <Outlet />
    </>
  );
}

/** Things worth a look, derived only from what the backend reported. Never invented. */
function attentionItems(change: ChangeView): string[] {
  const items: string[] = [];
  if (!change.git_summary) items.push("No repository summary has been captured yet.");
  if (change.review_state === "MISSING_EVIDENCE") items.push("Evidence is missing, so this Change can't be reviewed yet.");
  if (change.review_state === "FAILED_VERIFICATION") items.push("The latest verification failed.");
  if (change.verification?.output_truncated) items.push("Verification output was truncated.");
  if (change.git_summary?.patch_truncated) items.push("The recorded patch was truncated for size.");
  if (change.git_summary?.untracked_patch_omitted) items.push("Untracked files are not included in the recorded patch.");
  const state = change.lifecycle_state ?? "DRAFT";
  if (!LIFECYCLE_PATH.includes(state)) items.push(`The Change is ${lifecycleInfo(state).label.toLowerCase()}, outside the normal forward path.`);
  return items;
}

function LifecycleRail({ current }: { current: ChangeLifecycleState | undefined }) {
  const at = LIFECYCLE_PATH.indexOf(current ?? "DRAFT");
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 text-[13px]" aria-label="Lifecycle">
      {LIFECYCLE_PATH.map((state, index) => {
        const done = at !== -1 && index < at;
        const now = index === at;
        return (
          <li
            key={state}
            aria-current={now ? "step" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5",
              now ? "border-primary bg-[var(--primary-tint)] font-medium text-[var(--text-primary)]" : done ? "text-foreground" : "text-subtle",
            )}
          >
            {done ? <Check className="size-3 text-ok" aria-hidden="true" /> : null}
            {lifecycleInfo(state).label}
            <span className="sr-only">{done ? " (reached)" : now ? " (current)" : " (not reached)"}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function OverviewTab() {
  const changeId = useChangeId();
  const { data: change } = useQuery(changeDetailQuery(changeId));
  if (!change) return null;

  const git = change.git_summary;
  const verification = change.verification;
  const attention = attentionItems(change);

  return (
    <>
      <ChangeActions change={change} />
      <Section title="Needs attention">
        {attention.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing flagged. Everything the backend reports for this Change looks in order.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {attention.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-warn" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Lifecycle" description={`${change.last_transition_at ? `Last transition ${formatRelative(change.last_transition_at)}` : "No transitions yet"} · revision ${change.revision ?? "—"}`}>
        <LifecycleRail current={change.lifecycle_state} />
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Repository" action={git ? <span className="text-xs text-muted-foreground">observed {formatRelative(git.refreshed_at)}</span> : undefined}>
          {git ? (
            <Facts
              items={[
                { label: "Branch", value: git.branch ?? "detached HEAD" },
                { label: "HEAD", value: <code>{shortSha(git.head_sha)}</code> },
                ...(change.forked_from_change_id ? [{ label: "Forked from", value: <Link to="/changes/$changeId" params={{ changeId: change.forked_from_change_id }} className="underline underline-offset-2">{change.forked_from_change_id.slice(0, 8)}</Link> }] : []),
                { label: "Working tree", value: git.is_clean ? "Clean" : "Has changes" },
                {
                  label: "Changed files",
                  value: (
                    <span className="tabular-nums">
                      {(git.files ?? []).length} <span className="text-muted-foreground">(+{git.total_additions} / −{git.total_deletions})</span>
                    </span>
                  ),
                },
              ]}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Nothing captured yet.</p>
          )}
        </Section>

        <Section title="Verification" action={<StatusLabel status={reviewInfo(change.review_state)} />}>
          {verification ? (
            <Facts
              items={[
                { label: "Result", value: verification.status.replace("_", " ").toLowerCase() },
                { label: "Command", value: <code>{[verification.executable, ...(verification.args ?? [])].join(" ")}</code> },
                { label: "Exit code", value: <span className="tabular-nums">{verification.exit_code ?? "—"}</span> },
                { label: "Duration", value: <span className="tabular-nums">{verification.duration_ms} ms</span> },
                { label: "Completed", value: <span title={formatTime(verification.completed_at)}>{formatRelative(verification.completed_at)}</span> },
              ]}
            />
          ) : (
            <p className="text-sm text-muted-foreground">No verification has been run for this Change.</p>
          )}
        </Section>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChangedFiles change={change} />
        <RecentActivity changeId={changeId} />
      </div>

      <p className="text-xs leading-5 text-muted-foreground">
        Values come straight from the local service. A passing check is evidence for one Git state, not proof the change is correct.
        The runtime doesn't observe descendant processes, file writes, or an agent's internal tool calls.
      </p>
    </>
  );
}

const FILE_STATUS: Record<string, string> = { ADDED: "Added", MODIFIED: "Modified", DELETED: "Deleted", RENAMED: "Renamed", UNTRACKED: "Untracked" };
const FILES_SHOWN = 8;

function ChangedFiles({ change }: { change: ChangeView }) {
  const files = change.git_summary?.files ?? [];
  return (
    <Section title="Changed files" description={files.length ? `${files.length} in the working tree` : undefined} flush>
      {files.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">
          {change.git_summary ? "No changed files. The working tree matches HEAD." : "Nothing captured yet."}
        </p>
      ) : (
        <>
          <DataTable label="Changed files">
            <tbody>
              {files.slice(0, FILES_SHOWN).map((f) => (
                <tr key={f.path}>
                  <td className={cn(td, "mono break-all")}>{f.path}</td>
                  <td className={cn(td, "whitespace-nowrap text-muted-foreground")}>{FILE_STATUS[String(f.status)] ?? String(f.status).toLowerCase()}</td>
                  <td className={cn(td, "whitespace-nowrap text-right tabular-nums")}>
                    <span className="text-ok">+{f.additions ?? 0}</span> <span className="text-danger">−{f.deletions ?? 0}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          {files.length > FILES_SHOWN ? <p className="border-t px-5 py-2.5 text-xs text-muted-foreground">and {files.length - FILES_SHOWN} more</p> : null}
        </>
      )}
    </Section>
  );
}

function RecentActivity({ changeId }: { changeId: string }) {
  const events = useQuery(eventsQuery(changeId));
  const items = (events.data?.items ?? []).slice(-5).reverse();
  return (
    <Section title="Recent activity" flush>
      {events.isPending ? (
        <Skeleton lines={3} label="Loading activity" />
      ) : items.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">No events recorded yet.</p>
      ) : (
        <ul className="divide-y text-sm">
          {items.map((e) => (
            <li key={e.id} className="flex items-baseline justify-between gap-4 px-5 py-2.5">
              <span className="mono min-w-0 break-all">{e.event_type}</span>
              <time className="shrink-0 text-xs text-muted-foreground" dateTime={e.occurred_at} title={formatTime(e.occurred_at)}>
                {formatRelative(e.occurred_at)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

export function ContractTab() {
  const changeId = useChangeId();
  const { data: change } = useQuery(changeDetailQuery(changeId));
  if (!change) return null;
  const c: Partial<ChangeContract> = change.contract ?? {};
  const [editing, setEditing] = useState(false);
  if (editing) return <ContractEditor change={change} onDone={() => setEditing(false)} />;

  const rows: { title: string; items: string[] | undefined; empty: string }[] = [
    { title: "Allowed paths", items: c.allowed_paths, empty: "No path allowlist, so nothing is constrained by path." },
    { title: "Forbidden paths", items: c.forbidden_paths, empty: "None declared." },
    { title: "Required checks", items: c.required_checks, empty: "None declared." },
    { title: "Expected outcomes", items: c.expected_outcomes, empty: "None declared." },
    { title: "Authority ceiling", items: c.authority_ceiling, empty: "None declared." },
    { title: "Provider operations", items: c.allowed_provider_operations, empty: "None allowed." },
  ];

  return (
    <>
      <Section title="Intent" action={<Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit contract</Button>}>
        <p className="whitespace-pre-wrap break-words text-sm leading-6">{change.intent}</p>
      </Section>
      <Section title="Limits">
        <Facts
          items={[
            { label: "Max risk", value: c.max_risk ?? "—" },
            { label: "Recovery", value: c.recovery_allowed ? "Allowed" : "Not allowed" },
            { label: "Schema", value: `v${c.schema_version ?? "—"}` },
          ]}
        />
      </Section>
      <div className="grid gap-6 lg:grid-cols-2">
        {rows.map((row) => (
          <Section key={row.title} title={row.title}>
            <Chips items={row.items} empty={row.empty} />
          </Section>
        ))}
      </div>
    </>
  );
}
