import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { PageHeader, Section } from "@/components/product";
import { cn } from "@/lib/utils";
import { actorListQuery, githubStatusQuery } from "@/services/actions";
import { changeListQuery } from "@/services/changes";

export const WALKTHROUGH_KEY = "ca.walkthrough-seen.v1";

interface Step { title: string; why: string; where: string; to: string; action: string; done?: boolean }

/** A guided path through the product, in the order the work actually happens. Steps mark themselves done from real data where the API allows. */
export function WalkthroughPage() {
  const changes = useQuery(changeListQuery());
  const actors = useQuery(actorListQuery());
  const github = useQuery(githubStatusQuery());
  const firstChange = changes.data?.items[0]?.id;
  const inChange = (tab: string) => (firstChange ? { to: `/changes/${firstChange}/${tab}`, action: `Open ${tab}` } : { to: "/changes", action: "Create a Change first" });

  const steps: Step[] = [
    { title: "Create a Change", why: "A Change ties what you intended to the repository state, so everything after it has something to be checked against.", where: "Changes → New Change. Pick a Git repository and describe the intent.", to: "/changes?new=1", action: "New Change", done: (changes.data?.total ?? 0) > 0 },
    { title: "Register who can act", why: "Nothing happens on a Change without an actor holding authority. Register yourself and any agent.", where: "Actors → Create actor.", to: "/actors", action: "Open Actors", done: (actors.data?.total ?? 0) > 0 },
    { title: "Delegate authority", why: "A delegation gives an actor specific scopes for a limited time. A Change can't become Active without one.", where: "A Change → Authority → Delegate authority.", ...inChange("authority") },
    { title: "Capture a baseline, then current", why: "Two Git checkpoints let Sentinel show exactly what moved, and give Assurance and Recovery something to work from.", where: "A Change → Evidence → Capture baseline, do the work, Capture current.", ...inChange("evidence") },
    { title: "Run an agent (optional)", why: "Launch or record a top-level agent against the Change. Sentinel records the run, not what the agent spawns.", where: "Agents → pick a Change → Launch agent.", to: "/agents", action: "Open Agents" },
    { title: "Plan and run assurance", why: "Checks from the evidence, and an honest answer to what is proven and what is not.", where: "A Change → Assurance → Create plan → Run checks.", ...inChange("assurance") },
    { title: "Connect GitHub and deliver", why: "Open a pull request through a scoped grant, and track CI for the exact commit.", where: "GitHub → Connect; then a Change → Delivery.", to: "/github", action: "Open GitHub", done: github.data?.configured === true },
    { title: "Verify the trace and export the passport", why: "Check the record wasn't altered, then export a summary you can hand to someone else.", where: "A Change → Timeline (verify) and Passport (build, export).", ...inChange("passport") },
  ];
  const doneCount = steps.filter((s) => s.done).length;

  return (
    <>
      <PageHeader title="Walkthrough" description="The path from an idea to an exported passport, one step at a time. Steps tick themselves off when Sentinel can tell they're done." />
      <p className="text-sm text-muted-foreground" role="status">{doneCount} of {steps.length} steps detected as done</p>
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.title}>
            <Section>
              <div className="flex items-start gap-4">
                <span className={cn("mt-0.5 grid size-7 shrink-0 place-items-center rounded-full border text-sm", s.done ? "border-ok bg-[var(--status-ok-bg)] text-ok" : "text-muted-foreground")} aria-hidden="true">
                  {s.done ? <Check className="size-4" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">{s.title}{s.done ? <span className="sr-only"> (done)</span> : null}</h2>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">{s.why}</p>
                  <p className="mt-1 text-[13px] text-muted-foreground"><span className="font-medium text-foreground">Where:</span> {s.where}</p>
                </div>
                <Link to={s.to} className="shrink-0 rounded-md border px-3 py-1.5 text-sm hover:bg-accent">{s.action}</Link>
              </div>
            </Section>
          </li>
        ))}
      </ol>
    </>
  );
}
