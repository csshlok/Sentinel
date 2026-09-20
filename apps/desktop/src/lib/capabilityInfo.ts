export interface CapabilityInfo {
  /** What you would use it for, in plain words. */
  purpose: string;
  /** What it needs or works alongside. */
  worksWith: string;
}

/**
 * Plain-language guidance for every capability the backend reports. The backend gives an id and a state; this says what the capability is
 * for and what to use it with. Unknown ids get no invented text.
 */
export const CAPABILITY_INFO: Record<string, CapabilityInfo> = {
  change_lifecycle: { purpose: "Move a Change from Draft to Active to verified, with each step checked.", worksWith: "Authority (a delegation) before Active; Assurance before Locally verified." },
  git_inspection: { purpose: "See what changed in the repository: branch, HEAD and changed files.", worksWith: "Git installed on this computer; Refresh on a Change." },
  legacy_verification: { purpose: "Run one command (for example your tests) in the repository and record the result.", worksWith: "A delegation with the change.legacy_verify scope." },
  git_checkpoints: { purpose: "Capture a baseline and later checkpoints, compare them, or fork a new Change from one.", worksWith: "Evidence tab. Recovery and Assurance both use checkpoints." },
  agent_launcher: { purpose: "Start or record a top-level AI agent run, then pause, resume or stop it.", worksWith: "Actors and delegations (agent.launch); an installed adapter such as Claude." },
  environment_passports: { purpose: "Record the environment a change was made in and show drift from the baseline.", worksWith: "Evidence tab, after capturing a baseline and a current checkpoint." },
  dependency_tracking: { purpose: "List dependency changes between baseline and now, with version movement.", worksWith: "Evidence tab; a repository with a supported package manifest." },
  assurance: { purpose: "Plan checks from the evidence, run them, and see what is proven and what is not.", worksWith: "Evidence first; a delegation with assurance.run to run the checks." },
  identity_and_policy: { purpose: "Register who can act and give them scoped, time-limited authority.", worksWith: "Actors page; each Change's Authority tab." },
  credential_broker: { purpose: "Give one actor use of your GitHub connection for chosen scopes, for a limited time.", worksWith: "GitHub connection; the Delivery tab of a Change." },
  provider_outcomes: { purpose: "Track pull requests and CI results for the exact commit.", worksWith: "GitHub connection and a grant; the Delivery tab." },
  recovery: { purpose: "Preview and apply a revert on a dedicated branch, with your explicit approval.", worksWith: "A baseline checkpoint; a delegation with recovery.execute; contract allows recovery." },
  change_passport: { purpose: "Build and export a summary of intent, authority, evidence and outcomes.", worksWith: "Passport tab; most useful after evidence and assurance exist." },
  cli_and_terminal_ui: { purpose: "Use Sentinel from a terminal, with the same service and data as this app.", worksWith: "The Terminal card below shows the exact commands." },
  event_journal: { purpose: "A hash-chained record of everything that happened on a Change.", worksWith: "Timeline tab and its event inspector." },
  replay: { purpose: "Check that the recorded events were not altered, and export the trace.", worksWith: "Timeline tab. It verifies the record; it does not re-run anything." },
  tool_registry: { purpose: "See which tools agents used and record approve or deny decisions.", worksWith: "Tools page; agent runs register their executables." },
  process_supervisor: { purpose: "Would track every process an agent starts.", worksWith: "Not available: Sentinel records the top-level run only." },
  filesystem_tracker: { purpose: "Would attribute each file write to an actor.", worksWith: "Not available: Sentinel compares Git checkpoints instead." },
};
