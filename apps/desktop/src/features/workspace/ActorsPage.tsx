import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { ErrorState } from "@/components/ErrorState";
import { DataTable, EmptyState, PageHeader, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { NewActor } from "@/features/authority/AuthorityTab";
import { formatRelative, formatTime } from "@/lib/status";
import { cn } from "@/lib/utils";
import { actorListQuery } from "@/services/actions";

/** Everyone who can be given authority, across all Changes. Delegations are made per Change, on its Authority tab. */
export function ActorsPage() {
  const q = useQuery(actorListQuery());
  const items = q.data?.items ?? [];
  return (
    <>
      <PageHeader
        title="Actors"
        description="People, agents and services registered with Sentinel. Give one authority on a Change from that Change's Authority tab."
        actions={<NewActor onCreated={() => void q.refetch()} />}
      />
      {q.isPending ? (
        <Section flush><Skeleton lines={4} label="Loading actors" /></Section>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : items.length === 0 ? (
        <Section>
          <EmptyState icon={<Users className="size-6" strokeWidth={1.5} aria-hidden="true" />} title="No actors yet">
            Register a person, an agent or a service. Nothing can act on a Change until it holds a delegation.
          </EmptyState>
        </Section>
      ) : (
        <Section title={`${q.data.total} registered`} description={q.data.total > items.length ? `Showing the first ${items.length}.` : undefined} flush>
          <DataTable label="Actors">
            <thead>
              <tr><th className={th}>Name</th><th className={th}>Kind</th><th className={th}>Id</th><th className={th}>Registered</th></tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className={cn(td, "break-words font-medium text-[var(--text-primary)]")}>{a.display_name}</td>
                  <td className={td}><StatusLabel status={{ label: a.kind.toLowerCase(), tone: a.kind === "AGENT" ? "info" : "neutral" }} /></td>
                  <td className={cn(td, "mono text-xs")} title={a.id}>{a.id.slice(0, 8)}</td>
                  <td className={td} title={formatTime(a.created_at)}>{formatRelative(a.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Section>
      )}
    </>
  );
}
