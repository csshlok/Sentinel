import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { GitPullRequestArrow, Plus } from "lucide-react";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState, Facts, PageHeader, Section, Skeleton, StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import type { ChangeView } from "@/lib/api/types";
import { PAGE_SIZE, changeListQuery } from "@/services/changes";
import { capabilitiesQuery, healthQuery, runtimeQuery } from "@/services/system";
import { toolListQuery } from "@/services/tools";
import { ChangeRow } from "@/features/changes/ChangesPage";

const NEEDS_ATTENTION = new Set(["MISSING_EVIDENCE", "FAILED_VERIFICATION"]);

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-[var(--text-primary)]">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

const STEPS = [
  { title: "Pick a repository", body: "Choose a local Git repository. It is only read, never modified." },
  { title: "Say what the work should achieve", body: "Your intent is recorded so later evidence can be compared against it." },
  { title: "Review what actually changed", body: "See the repository state, verification result and event timeline in one place." },
];

export function HomePage() {
  const changes = useQuery(changeListQuery());
  const tools = useQuery(toolListQuery());
  const caps = useQuery(capabilitiesQuery());
  const health = useQuery(healthQuery());
  const runtime = useQuery(runtimeQuery());

  if (changes.isPending) {
    return (
      <>
        <PageHeader title="Home" />
        <Section flush>
          <Skeleton lines={5} label="Loading overview" />
        </Section>
      </>
    );
  }
  if (changes.isError) {
    return (
      <>
        <PageHeader title="Home" />
        <ErrorState error={changes.error} onRetry={() => changes.refetch()} />
      </>
    );
  }

  const items: ChangeView[] = changes.data.items;
  const total = changes.data.total;
  const more = typeof total === "number" ? "" : items.length >= PAGE_SIZE ? "+" : "";
  const attention = items.filter((c) => NEEDS_ATTENTION.has(c.review_state));
  const ready = items.filter((c) => c.review_state === "READY_FOR_HUMAN_REVIEW");
  const toolItems = tools.data?.items ?? [];
  const available = caps.data?.items.filter((c) => c.state === "AVAILABLE").length;
  const newChange = (
    <Button asChild>
      <Link to="/changes" search={{ new: true }}>
        <Plus /> New Change
      </Link>
    </Button>
  );

  return (
    <>
      <PageHeader title="Home" description="Where your Changes stand right now." actions={items.length > 0 ? newChange : null} />

      {items.length === 0 ? (
        <>
          <Section>
            <EmptyState icon={<GitPullRequestArrow className="size-6" strokeWidth={1.5} aria-hidden="true" />} title="Start with your first Change" action={newChange}>
              A Change ties what you intended to the repository state and the evidence gathered for it.
            </EmptyState>
          </Section>
          <Section title="How it works">
            <ol className="grid gap-5 sm:grid-cols-3">
              {STEPS.map((step, i) => (
                <li key={step.title} className="min-w-0">
                  <p className="text-xs font-medium text-muted-foreground">Step {i + 1}</p>
                  <p className="mt-1 font-medium text-[var(--text-primary)]">{step.title}</p>
                  <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{step.body}</p>
                </li>
              ))}
            </ol>
          </Section>
        </>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-6 lg:grid-cols-4">
            <Stat label="Changes" value={typeof total === "number" ? String(total) : `${items.length}${more}`} />
            <Stat label="Need attention" value={String(attention.length)} hint="Missing evidence or failed verification" />
            <Stat label="Ready for review" value={String(ready.length)} />
            <Stat label="Tools seen" value={tools.isSuccess ? String(toolItems.length) : "—"} />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Needs attention" flush>
              {attention.length === 0 ? (
                <p className="px-5 py-4 text-sm text-muted-foreground">Nothing needs attention right now.</p>
              ) : (
                <ul className="divide-y" aria-label="Changes that need attention">
                  {attention.slice(0, 5).map((c) => (
                    <li key={c.id}>
                      <ChangeRow change={c} stacked />
                    </li>
                  ))}
                </ul>
              )}
            </Section>
            <Section title="Recent Changes" action={<Link to="/changes" className="text-[13px] text-muted-foreground underline underline-offset-2 hover:text-foreground">View all</Link>} flush>
              <ul className="divide-y" aria-label="Recent Changes">
                {items.slice(0, 5).map((c) => (
                  <li key={c.id}>
                    <ChangeRow change={c} stacked />
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </>
      )}

      <Section title="Local service" action={<Link to="/settings" className="text-[13px] text-muted-foreground underline underline-offset-2 hover:text-foreground">Settings</Link>}>
        <Facts
          items={[
            {
              label: "Status",
              value: health.isError ? <StatusLabel status={{ label: "Not reachable", tone: "danger" }} /> : <StatusLabel status={{ label: "Reachable", tone: "ok" }} />,
            },
            { label: "Capabilities", value: caps.data ? `${available} of ${caps.data.items.length} available` : "—" },
            ...(runtime.data ? [{ label: "Mode", value: runtime.data.backend.mode === "managed" ? "Managed by this app" : "External" }] : []),
          ]}
        />
      </Section>
    </>
  );
}
