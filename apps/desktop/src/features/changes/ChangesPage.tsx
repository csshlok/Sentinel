import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { GitPullRequestArrow, LoaderCircle, Plus, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, PageHeader, Section, Skeleton, StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChangeView } from "@/lib/api/types";
import { formatRelative, formatTime, lifecycleInfo, repoName, reviewInfo, shortSha } from "@/lib/status";
import { cn } from "@/lib/utils";
import { changePagesQuery } from "@/services/changes";
import { NewChangeDialog } from "./NewChangeDialog";

/** Filtering is only worth the space once the list is long enough to scan. */
const FILTER_THRESHOLD = 6;

export function ChangeRow({ change, stacked = false }: { change: ChangeView; stacked?: boolean }) {
  const git = change.git_summary;
  return (
    <Link
      to="/changes/$changeId"
      params={{ changeId: change.id }}
      className={cn("flex flex-col gap-2 px-5 py-3.5 transition-colors hover:bg-accent focus-visible:bg-accent", !stacked && "sm:flex-row sm:items-center sm:justify-between sm:gap-4")}
    >
      <div className="min-w-0">
        <p className="break-words font-medium text-[var(--text-primary)]">{change.title}</p>
        <p className="mt-0.5 break-words text-[13px] text-muted-foreground">
          {repoName(change.repository_path)}
          {git ? ` · ${git.branch ?? "detached"} @ ${shortSha(git.head_sha)} · ${(git.files ?? []).length} changed` : ""}
          {" · "}
          <time dateTime={change.updated_at} title={formatTime(change.updated_at)}>
            updated {formatRelative(change.updated_at)}
          </time>
        </p>
      </div>
      <div className={cn("flex shrink-0 flex-wrap items-center gap-2", !stacked && "sm:justify-end")}>
        {change.review_state === "NO_CHANGES" ? null : <StatusLabel status={reviewInfo(change.review_state)} />}
        <StatusLabel status={lifecycleInfo(change.lifecycle_state)} />
      </div>
    </Link>
  );
}

export function ChangesPage() {
  const navigate = useNavigate();
  const creating = useSearch({ from: "/changes", select: (s) => Boolean(s.new) });
  const [filter, setFilter] = useState("");
  const opener = useRef<HTMLElement | null>(null);
  const list = useInfiniteQuery(changePagesQuery());

  const setCreating = (open: boolean) => void navigate({ to: "/changes", search: open ? { new: true } : {}, replace: true });
  const newButton = (
    <Button
      onClick={() => {
        opener.current = document.activeElement as HTMLElement | null;
        setCreating(true);
      }}
    >
      <Plus /> New Change
    </Button>
  );

  // Pages can overlap if a Change is created between requests, so de-duplicate by id.
  const items = useMemo(() => {
    const seen = new Set<string>();
    return (list.data?.pages ?? []).flatMap((p) => p.items).filter((c) => (seen.has(c.id) ? false : (seen.add(c.id), true)));
  }, [list.data]);
  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((c) => `${c.title} ${c.repository_path} ${c.git_summary?.branch ?? ""}`.toLowerCase().includes(needle));
  }, [items, filter]);

  return (
    <>
      <PageHeader
        title="Changes"
        description="Each Change ties what you intended to the repository state and the evidence gathered for it."
        actions={items.length > 0 ? newButton : null}
      />

      {list.isPending ? (
        <Section flush>
          <Skeleton lines={4} label="Loading Changes" />
        </Section>
      ) : list.isError && items.length === 0 ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} />
      ) : items.length === 0 ? (
        <Section>
          <EmptyState icon={<GitPullRequestArrow className="size-6" strokeWidth={1.5} aria-hidden="true" />} title="No Changes yet" action={newButton}>
            Create a Change for a Git repository to start recording your intent and the evidence for the work.
          </EmptyState>
        </Section>
      ) : (
        <div className="space-y-3">
          {items.length >= FILTER_THRESHOLD ? (
            <div className="relative max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-subtle" aria-hidden="true" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by title, repository or branch" aria-label="Filter Changes" className="h-9 pl-9" />
            </div>
          ) : null}
          <Section flush>
            {visible.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-muted-foreground">No Changes match “{filter}”.</p>
            ) : (
              <ul aria-label="Changes" className="divide-y">
                {visible.map((change) => (
                  <li key={change.id}>
                    <ChangeRow change={change} />
                  </li>
                ))}
              </ul>
            )}
          </Section>
          {list.hasNextPage ? (
            <div className="flex items-center gap-3">
              <Button variant="outline" size="sm" disabled={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>
                {list.isFetchingNextPage ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}
                Load more
              </Button>
              <span className="text-xs text-muted-foreground">
                {items.length} of {list.data?.pages.at(-1)?.total ?? "many"} loaded{filter ? ` · filter applies to loaded Changes only` : ""}
              </span>
            </div>
          ) : null}
          {list.isError ? <ErrorState error={list.error} onRetry={() => list.fetchNextPage()} /> : null}
        </div>
      )}

      <NewChangeDialog open={creating} onOpenChange={setCreating} returnFocusTo={opener} />
    </>
  );
}
