import { Bot, Compass, GitBranch, GitPullRequestArrow, House, Settings, Users, Wrench, type LucideIcon } from "lucide-react";

export interface NavItem { to: string; label: string; icon: LucideIcon }
export interface NavGroup { heading: string; items: NavItem[] }

/** Every destination here is a real screen. Groups keep global surfaces apart from the per-Change workspace. */
export const NAV_GROUPS: NavGroup[] = [
  { heading: "Workspace", items: [{ to: "/home", label: "Home", icon: House }, { to: "/changes", label: "Changes", icon: GitPullRequestArrow }, { to: "/walkthrough", label: "Walkthrough", icon: Compass }] },
  { heading: "Control", items: [{ to: "/agents", label: "Agents", icon: Bot }, { to: "/actors", label: "Actors", icon: Users }, { to: "/tools", label: "Tools", icon: Wrench }] },
  { heading: "Integrations", items: [{ to: "/github", label: "GitHub", icon: GitBranch }] },
  { heading: "System", items: [{ to: "/settings", label: "Settings", icon: Settings }] },
];
export const NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

export interface CapabilityLink { to: string; label: string; where: string }

const inChange = (where: string): CapabilityLink => ({ to: "/changes", label: "Open Changes", where });

/**
 * Where each backend capability is used in the app. Capabilities that act on a specific Change live inside that Change's tabs, so they
 * link to the Changes list. An id not listed here has no link, and Settings says so instead of implying a screen exists.
 */
export const CAPABILITY_LINKS: Record<string, CapabilityLink> = {
  change_lifecycle: inChange("Overview tab: state changes, verification, cancel"),
  git_inspection: inChange("Overview tab: repository summary and changed files"),
  git_checkpoints: inChange("Evidence tab: checkpoints, compare, fork"),
  environment_passports: inChange("Evidence tab: environment and drift"),
  dependency_tracking: inChange("Evidence tab: dependency changes"),
  legacy_verification: inChange("Overview tab: Run verification"),
  assurance: inChange("Assurance tab: plan, run, evaluate"),
  recovery: inChange("Recovery tab: preview and execute"),
  change_passport: inChange("Passport tab: build and export"),
  event_journal: inChange("Timeline tab: events and inspector"),
  replay: inChange("Timeline tab: trace verification and export"),
  agent_launcher: { to: "/agents", label: "Open Agents", where: "Agents: adapters, live runs, launch on a Change" },
  identity_and_policy: { to: "/actors", label: "Open Actors", where: "Actors: register actors. Authority tab: delegations" },
  credential_broker: { to: "/github", label: "Open GitHub", where: "GitHub: connection. Delivery tab: grants" },
  provider_outcomes: { to: "/github", label: "Open GitHub", where: "GitHub: outcomes across Changes" },
  tool_registry: { to: "/tools", label: "Open Tools", where: "Tools: manifests and trust decisions" },
};
