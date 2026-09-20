import { Link } from "@tanstack/react-router";
import { Bot, GitBranch, GitPullRequestArrow, Users, Wrench, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Notice, Section } from "@/components/product";
import { Button } from "@/components/ui/button";
import { WALKTHROUGH_KEY } from "@/features/workspace/WalkthroughPage";

const TILES: { to: string; title: string; text: string; icon: LucideIcon }[] = [
  { to: "/changes", title: "Changes", text: "Create a Change, capture evidence, verify, and export a passport.", icon: GitPullRequestArrow },
  { to: "/agents", title: "Agents", text: "Launch, attach, pause and stop top-level agent runs.", icon: Bot },
  { to: "/actors", title: "Actors", text: "Register people, agents and services, then delegate authority.", icon: Users },
  { to: "/tools", title: "Tools", text: "Review tool manifests and record trust decisions.", icon: Wrench },
  { to: "/github", title: "GitHub", text: "Connect once, then open and track pull requests.", icon: GitBranch },
];

/** Entry points to everything Sentinel can do. Each tile opens a real screen; nothing here is a status or a metric. */
function seen(): boolean {
  try { return localStorage.getItem(WALKTHROUGH_KEY) === "1"; } catch { return true; }
}

/** A one-time prompt for new users. Dismissing it, or opening the walkthrough, means it is not shown again. */
function WalkthroughPrompt() {
  const [hidden, setHidden] = useState(seen);
  const dismiss = () => { try { localStorage.setItem(WALKTHROUGH_KEY, "1"); } catch { /* it just shows again next time */ } setHidden(true); };
  if (hidden) return null;
  return (
    <Notice title="New to Sentinel?" action={<div className="flex gap-2"><Button asChild size="sm" onClick={dismiss}><Link to="/walkthrough">Take the walkthrough</Link></Button><Button size="sm" variant="ghost" onClick={dismiss}>Dismiss</Button></div>}>
      A short guided path from creating a Change to exporting a passport.
    </Notice>
  );
}

export function ControlCenter() {
  return (
    <>
    <WalkthroughPrompt />
    <Section title="Control center" description="Everything Sentinel can do for a repository, from one place.">
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {TILES.map(({ to, title, text, icon: Icon }) => (
          <li key={to}>
            <Link to={to} className="flex h-full gap-3 rounded-lg border p-3.5 transition-colors hover:bg-accent focus-visible:bg-accent">
              <Icon className="mt-0.5 size-4 shrink-0 text-primary" strokeWidth={1.75} aria-hidden="true" />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-[var(--text-primary)]">{title}</span>
                <span className="mt-0.5 block text-[13px] leading-5 text-muted-foreground">{text}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Section>
    </>
  );
}
