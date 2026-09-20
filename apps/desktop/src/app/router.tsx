import { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, createRoute, createRouter, lazyRouteComponent, redirect } from "@tanstack/react-router";
import { AppShell } from "@/components/AppShell";
import { ChangesPage } from "@/features/changes/ChangesPage";
import { HomePage } from "@/features/home/HomePage";
import {
  ChangeWorkspace,
  ContractTab,
  OverviewTab,
} from "@/features/changes/ChangeWorkspace";
import { NotFound } from "@/features/NotFound";

// Each screen beyond the first paint is its own chunk, loaded when its route is first visited.
const lazy = lazyRouteComponent;

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: AppShell,
  notFoundComponent: NotFound,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/home" });
  },
});

const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/home", component: HomePage });

// `?new=1` opens the create dialog, so "New Change" is deep-linkable from the command palette and elsewhere.
const changesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/changes",
  component: ChangesPage,
  validateSearch: (search: Record<string, unknown>): { new?: true } =>
    search.new === true || search.new === "1" || search.new === 1 ? { new: true } : {},
});

const changeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/changes/$changeId",
  component: ChangeWorkspace,
});
const overviewRoute = createRoute({ getParentRoute: () => changeRoute, path: "/", component: OverviewTab });
const contractRoute = createRoute({ getParentRoute: () => changeRoute, path: "contract", component: ContractTab });
const evidenceRoute = createRoute({ getParentRoute: () => changeRoute, path: "evidence", component: lazy(() => import("@/features/evidence/EvidenceTab"), "EvidenceTab") });
const timelineRoute = createRoute({ getParentRoute: () => changeRoute, path: "timeline", component: lazy(() => import("@/features/timeline/TimelineTab"), "TimelineTab") });

const extra = [["assurance", lazy(() => import("@/features/assurance/AssuranceTab"), "AssuranceTab")], ["agents", lazy(() => import("@/features/agents/AgentsTab"), "AgentsTab")], ["delivery", lazy(() => import("@/features/delivery/DeliveryTab"), "DeliveryTab")], ["authority", lazy(() => import("@/features/authority/AuthorityTab"), "AuthorityTab")], ["recovery", lazy(() => import("@/features/recovery/RecoveryTab"), "RecoveryTab")], ["passport", lazy(() => import("@/features/passport/PassportTab"), "PassportTab")]] as const;
const extraRoutes = extra.map(([path, component]) => createRoute({ getParentRoute: () => changeRoute, path, component }));

const toolsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/tools", component: lazy(() => import("@/features/tools/ToolsPage"), "ToolsPage") });
const toolDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: "/tools/$toolId", component: lazy(() => import("@/features/tools/ToolDetailPage"), "ToolDetailPage") });
const walkthroughRoute = createRoute({ getParentRoute: () => rootRoute, path: "/walkthrough", component: lazy(() => import("@/features/workspace/WalkthroughPage"), "WalkthroughPage") });
const actorsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/actors", component: lazy(() => import("@/features/workspace/ActorsPage"), "ActorsPage") });
const agentsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/agents", component: lazy(() => import("@/features/workspace/AgentsPage"), "AgentsPage") });
const githubRoute = createRoute({ getParentRoute: () => rootRoute, path: "/github", component: lazy(() => import("@/features/workspace/GithubPage"), "GithubPage") });
const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: lazy(() => import("@/features/settings/SettingsPage"), "SettingsPage") });

const routeTree = rootRoute.addChildren([
  indexRoute,
  homeRoute,
  changesRoute,
  changeRoute.addChildren([overviewRoute, contractRoute, evidenceRoute, ...extraRoutes, timelineRoute]),
  toolsRoute,
  toolDetailRoute,
  walkthroughRoute,
  actorsRoute,
  agentsRoute,
  githubRoute,
  settingsRoute,
]);

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: false, refetchOnWindowFocus: true },
  },
});

export const router = createRouter({ routeTree, context: { queryClient }, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
