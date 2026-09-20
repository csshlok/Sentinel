import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { GitPullRequestArrow, House, LoaderCircle, Search, Settings, ShieldCheck, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CommandPalette } from "@/components/CommandPalette";
import { Button } from "@/components/ui/button";
import { EmptyState, StatusLabel } from "@/components/product";
import { WindowChrome } from "@/components/WindowChrome";
import { ApiError } from "@/lib/api/client";
import type { StatusInfo } from "@/lib/status";
import { cn } from "@/lib/utils";
import { capabilitiesQuery, healthQuery, runtimeQuery } from "@/services/system";

const NAV = [
  { to: "/home", label: "Home", icon: House },
  { to: "/changes", label: "Changes", icon: GitPullRequestArrow },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

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
          <Link to="/home" className="flex items-center gap-2 rounded-sm px-1 text-[var(--text-primary)]" aria-label="Change Assurance home">
            <ShieldCheck className="size-[18px] text-primary" strokeWidth={1.75} aria-hidden="true" />
            <span className="text-[15px] font-semibold tracking-[-0.01em]">Change Assurance</span>
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

        <nav className="flex-1 space-y-1 px-4 pt-2" aria-label="Primary">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} className={navClass} activeProps={{ className: cn(navClass, "bg-accent font-medium text-accent-foreground"), "aria-current": "page" }}>
              <Icon className="size-4" strokeWidth={1.5} aria-hidden="true" />
              {label}
            </Link>
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
        <nav className="flex items-center gap-1 border-b bg-sidebar px-3 py-2 md:hidden" aria-label="Primary">
          {NAV.map(({ to, label }) => (
            <Link key={to} to={to} className="rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent" activeProps={{ className: "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground", "aria-current": "page" }}>
              {label}
            </Link>
          ))}
          <span className="ml-auto"><StatusLabel status={connection} /></span>
        </nav>
        <div className="mx-auto w-full max-w-[1040px] space-y-6 px-6 pb-12 pt-10 md:px-8">
          {gated ? <ServiceGate /> : <Outlet />}
        </div>
      </main>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
