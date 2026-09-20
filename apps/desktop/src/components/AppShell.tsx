import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { LoaderCircle, Search } from "lucide-react";
import { SentinelMark } from "@/components/SentinelMark";
import { useEffect, useRef, useState } from "react";
import { CommandPalette } from "@/components/CommandPalette";
import { Button } from "@/components/ui/button";
import { EmptyState, StatusLabel } from "@/components/product";
import { WindowChrome } from "@/components/WindowChrome";
import { ApiError } from "@/lib/api/client";
import type { StatusInfo } from "@/lib/status";
import { cn } from "@/lib/utils";
import { capabilitiesQuery, healthQuery, runtimeQuery } from "@/services/system";
import { NAV_GROUPS, NAV_ITEMS } from "@/lib/nav";
import { lifecycleInfo } from "@/lib/status";
import { changeListQuery } from "@/services/changes";



/** Reachability comes from the open health route; authentication from an authenticated route. */
function useConnection(): StatusInfo {
  const queryClient = useQueryClient();
  const health = useQuery(healthQuery());
  const caps = useQuery(capabilitiesQuery());

  // When the backend comes back (or finishes starting), refetch everything that failed while it was down.
  const wasDown = useRef(false);
  useEffect(() => {
    if (health.isError) wasDown.current = true;
    else if (health.isSuccess && wasDown.current) {
      wasDown.current = false;
      void queryClient.invalidateQueries();
    }
  }, [health.isError, health.isSuccess, queryClient]);

  if (health.isPending) return { label: "Connecting", tone: "neutral" };
  if (health.isError) return { label: "Offline", tone: "danger" };
  if (caps.error instanceof ApiError && caps.error.kind === "auth") return { label: "Not signed in", tone: "warn" };
  if (caps.isError) return { label: "Service error", tone: "danger" };
  return { label: "Connected", tone: "ok" };
}

const navClass = "flex h-[34px] items-center gap-2.5 rounded-md border border-transparent px-2.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground";

const DOT: Record<string, string> = { ok: "bg-ok", warn: "bg-warn", danger: "bg-danger", info: "bg-info", neutral: "bg-[var(--status-muted)]" };

/** The five most recently updated Changes, so any of them is one click away from anywhere. */
function RecentChanges() {
  const list = useQuery(changeListQuery());
  const items = (list.data?.items ?? []).slice(0, 5);
  if (items.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5" aria-label="Recent Changes">
      {items.map((c) => (
        <li key={c.id}>
          <Link to="/changes/$changeId" params={{ changeId: c.id }} className="flex h-7 items-center gap-2 rounded-md px-2.5 pl-6 text-[13px] text-muted-foreground hover:bg-accent hover:text-foreground" activeProps={{ className: "flex h-7 items-center gap-2 rounded-md bg-accent px-2.5 pl-6 text-[13px] text-foreground", "aria-current": "page" }} title={`${c.title} · ${lifecycleInfo(c.lifecycle_state).label}`}>
            <span className={cn("size-1.5 shrink-0 rounded-full", DOT[lifecycleInfo(c.lifecycle_state).tone])} aria-hidden="true" />
            <span className="min-w-0 truncate">{c.title}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Managed-backend startup and failure, shown instead of the page so nothing renders against a dead service. */
function ServiceGate() {
  const runtime = useQuery(runtimeQuery());
  const queryClient = useQueryClient();
  const [restarting, setRestarting] = useState(false);
  const backend = runtime.data?.backend;

  if (backend?.mode !== "managed") return null;
  if (backend.state === "starting" || backend.state === "idle") {
    return (
      <EmptyState icon={<LoaderCircle className="size-6 animate-spin" aria-hidden="true" />} title="Starting the local service">
        This only takes a moment.
      </EmptyState>
    );
  }
  if (backend.state === "failed" || backend.state === "exited") {
    return (
      <EmptyState
        title="The local service isn't running"
        action={
          <Button
            disabled={restarting}
            onClick={async () => {
              setRestarting(true);
              await window.changeAssuranceDesktop?.runtime.restartBackend();
              await queryClient.invalidateQueries();
              setRestarting(false);
            }}
          >
            {restarting ? "Restarting…" : "Try again"}
          </Button>
        }
      >
        {backend.detail ?? "It stopped unexpectedly."} Your data is stored on this computer and is not affected.
      </EmptyState>
    );
  }
  return null;
}

export function AppShell() {
  const connection = useConnection();
  const runtime = useQuery(runtimeQuery());
  const mainRef = useRef<HTMLElement>(null);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Move focus to the content region after navigation so keyboard and screen-reader users land in the new view.
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    mainRef.current?.scrollTo({ top: 0 });
  }, [pathname]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const backend = runtime.data?.backend;
  const gated = backend?.mode === "managed" && backend.state !== "ready";

  return (
    <div className="flex h-full bg-background">
      <a href="#main" className="sr-only rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[200]">
        Skip to content
      </a>
      <WindowChrome />

      <aside className="app-sidebar hidden w-[var(--sidebar-width)] min-w-[var(--sidebar-width)] flex-col border-r bg-sidebar md:flex">
        <div className="px-4 pb-2 pt-10">
          <Link to="/home" className="flex items-center gap-2 rounded-sm px-1 text-[var(--text-primary)]" aria-label="Sentinel home">
            <SentinelMark className="size-6 text-primary" />
            <span className="text-[15px] font-semibold tracking-[-0.01em]">Sentinel</span>
          </Link>
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="mt-4 flex h-8 w-full items-center gap-2 rounded-md border border-input bg-card px-3 text-left text-[13px] text-subtle transition-colors hover:bg-accent hover:text-foreground"
          >
            <Search className="size-3.5" strokeWidth={1.5} aria-hidden="true" />
            <span className="min-w-0 flex-1">Search</span>
            <kbd className="text-[11px]">Ctrl K</kbd>
          </button>
        </div>

        <nav className="flex-1 space-y-4 overflow-y-auto px-4 pt-2" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <div key={group.heading}>
              <p className="mb-1 px-2.5 text-[11px] font-medium uppercase tracking-wide text-subtle">{group.heading}</p>
              <div className="space-y-0.5">
                {group.items.map(({ to, label, icon: Icon }) => (
                  <Link key={to} to={to} className={navClass} activeProps={{ className: cn(navClass, "bg-accent font-medium text-accent-foreground"), "aria-current": "page" }}>
                    <Icon className="size-4" strokeWidth={1.5} aria-hidden="true" />
                    {label}
                  </Link>
                ))}
              </div>
              {group.heading === "Workspace" ? <RecentChanges /> : null}
            </div>
          ))}
        </nav>

        <div className="border-t p-4">
          <Link to="/settings" className="flex flex-col gap-1.5 rounded-md p-1 hover:bg-accent" aria-live="polite">
            <StatusLabel status={connection} className="self-start" />
            <span className="px-0.5 text-xs text-muted-foreground">
              {backend ? (backend.mode === "managed" ? "Local service · managed" : "Local service · external") : "Local service · browser dev"}
            </span>
          </Link>
        </div>
      </aside>

      <main id="main" ref={mainRef} tabIndex={-1} className="min-w-0 flex-1 overflow-y-auto focus:outline-none">
        {/* Small screens (browser development only): a compact top nav replaces the sidebar. */}
        <nav className="quiet-scroll flex items-center gap-1 overflow-x-auto border-b bg-sidebar px-3 py-2 md:hidden" aria-label="Primary">
          {NAV_ITEMS.map(({ to, label }) => (
            <Link key={to} to={to} className="shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent" activeProps={{ className: "shrink-0 whitespace-nowrap rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground", "aria-current": "page" }}>
              {label}
            </Link>
          ))}
          <span className="ml-auto shrink-0 pl-2"><StatusLabel status={connection} /></span>
        </nav>
        <div className="mx-auto w-full max-w-[1040px] space-y-6 px-6 pb-12 pt-10 md:px-8">
          {gated ? <ServiceGate /> : <Outlet />}
        </div>
      </main>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
