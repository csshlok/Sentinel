import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { DataTable, EmptyState, PageHeader, Section, Skeleton, StatusLabel, td, th } from "@/components/product";
import { GithubConnection } from "@/features/delivery/GithubConnection";
import { KIND_LABEL, groupOutcomes } from "@/features/delivery/outcomes";
import { formatRelative, outcomeInfo, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { outcomesQuery } from "@/services/actions";
import { changeListQuery } from "@/services/changes";

/** The GitHub connection, and where each Change stands on pull requests and CI. Grants and pull requests are made on a Change's Delivery tab. */
export function GithubPage() {
  const changes = useQuery(changeListQuery());
  const recent = (changes.data?.items ?? []).slice(0, 8);
  const outcomes = useQueries({ queries: recent.map((c) => outcomesQuery(c.id)) });
  const rows = recent.flatMap((c, i) => groupOutcomes(outcomes[i]?.data?.items ?? [], c.git_summary?.head_sha).map((g) => ({ c, g })));
  return (
    <>
      <PageHeader title="GitHub" description="Sentinel opens and tracks pull requests through scoped, time-limited grants, never a raw token." />
      <Section title="Connection"><GithubConnection /></Section>
      <Section title="Pull requests and CI across your Changes" description="The newest observation of each kind. Create, refresh or close from a Change's Delivery tab." flush>
        {changes.isPending ? (
          <Skeleton lines={3} label="Loading outcomes" />
        ) : rows.length === 0 ? (
          <EmptyState title="No outcomes recorded">Once a Change has a pull request, its state and CI result appear here.</EmptyState>
        ) : (
          <DataTable label="Outcomes across Changes">
            <thead>
              <tr><th className={th}>Change</th><th className={th}>Kind</th><th className={th}>Latest</th><th className={th}>Commit</th><th className={th}>Observed</th></tr>
            </thead>
            <tbody>
              {rows.map(({ c, g }) => (
                <tr key={`${c.id}-${g.kind}`}>
                  <td className={cn(td, "break-words")}>
                    <Link to="/changes/$changeId/delivery" params={{ changeId: c.id }} className="underline-offset-2 hover:underline">{c.title}</Link>
                  </td>
                  <td className={td}>{KIND_LABEL[g.kind]}</td>
                  <td className={td}><StatusLabel status={outcomeInfo(g.latest.status)} /></td>
                  <td className={cn(td, "mono")}>{shortSha(g.latest.head_sha)}{g.stale ? <span className="ml-2 text-xs text-warn">not current</span> : null}</td>
                  <td className={td}>{formatRelative(g.latest.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>
    </>
  );
}
