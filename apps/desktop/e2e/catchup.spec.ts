import { expect, test, type Page } from "@playwright/test";
import { installFakeApi, makeChange } from "./fake-api";

// Phase 11: the boundary, workspace apply-back, confined checks, preset, Passport v2 and GitHub Check panels, against the fake backend.
const NOW = "2026-10-08T12:00:00Z";
const SID = "S-1-15-2-1-2-3-4-5-6-7";

async function open(page: Page, tab: string, over: Parameters<typeof installFakeApi>[1] = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem("ca.dev.token", "t"));
  const c = makeChange(1, { title: "Catch-up change", files: 1 });
  const api = await installFakeApi(page, { changes: [c], actors: [{ id: "actor-1", display_name: "Reviewer", kind: "HUMAN" }], ...over(c.id) });
  await page.goto(`/changes/${c.id}/${tab}`);
  return { api, errors, c };
}
type Over = (id: string) => Parameters<typeof installFakeApi>[1];

const run = (boundary: unknown) => ({
  id: "run-1", change_id: "x", adapter: "claude", status: "PASSED", started_at: NOW, completed_at: NOW, exit_code: 0, duration_ms: 10,
  stdout: "", stderr: "", output_truncated: false, limitations: [], descendant_control_available: true, restricted_token_applied: false,
  execution_boundary: boundary,
});

test("a run card names its observed AppContainer boundary exactly as the CLI does", async ({ page }) => {
  const box = { kind: "APPCONTAINER", profile: "sentinel.ws.abc", package_sid: SID, integrity_rid: "0x1000", capabilities: ["internetClient"], job_verified: true, verified_at: NOW, workspace_drive: "Z:" };
  const { errors } = await open(page, "agents", ((id) => ({ lists: { agents: { [id]: [run(box)] } } })) as Over);
  await expect(page.getByTestId("run-boundary")).toHaveText("Boundary: AppContainer (capabilities: internetClient; integrity low; Job verified; workspace drive Z:)");
  await expect(page.getByText(SID).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a reduced-token run is never presented as a sandbox", async ({ page }) => {
  const { errors } = await open(page, "agents", ((id) => ({ lists: { agents: { [id]: [run({ kind: "RESTRICTED_TOKEN", job_verified: false })] } } })) as Over);
  await expect(page.getByTestId("run-boundary")).toContainText("not a sandbox");
  await expect(page.getByText("Reduced token only", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

const workspace = (state = "READY") => ({
  id: "ws-1", change_id: "x", state, profile_name: "sentinel.ws.abc", package_sid: SID, base_sha: "a".repeat(40), base_branch: "main",
  sealed_sha: null, applied_sha: null, created_at: NOW, updated_at: NOW, credential_staged: false, limitations: ["Only committed files are present."], runs: [],
});
const preview = { change_id: "x", workspace_id: "ws-1", base_sha: "a".repeat(40), sealed_sha: "c".repeat(40), fast_forward_possible: true, approval_token: "tok-123",
  changed_paths: [{ status: "M", path: "calc.py", old_mode: "100644", new_mode: "100644", flags: [] }, { status: "A", path: ".github/workflows/ci.yml", old_mode: "000000", new_mode: "100644", flags: ["ci"] }],
  commits: [{ sha: "c".repeat(40), author: "Agent", subject: "Fix add" }], commits_truncated: false, patch: "diff --git a/calc.py b/calc.py", patch_truncated: false, limitations: [], user_branch: "main", user_head: "a".repeat(40) };

test("no workspace yet is explained, not shown as an error", async ({ page }) => {
  const { errors } = await open(page, "agents", (() => ({})) as Over);
  await expect(page.getByTestId("workspace-empty")).toContainText("never edits your repository directly");
  expect(errors).toEqual([]);
});

test("preview then apply sends the preview's approval token with the approving actor", async ({ page }) => {
  const { api, errors } = await open(page, "agents", ((id) => ({ workspaces: { [id]: workspace() }, previews: { [id]: preview } })) as Over);
  await page.getByRole("button", { name: "Preview changes" }).click();
  const shown = page.getByTestId("workspace-preview");
  await expect(shown.getByText(".github/workflows/ci.yml")).toBeVisible();
  await expect(shown.getByText("ci", { exact: true })).toBeVisible();
  await expect(shown.getByText("Ready to apply")).toBeVisible();
  await page.getByRole("button", { name: "Apply to my repository" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(dialog.getByText("Choose the actor who is approving this.")).toBeVisible();
  expect(api.calls.filter((c) => c.path === "workspace/apply")).toHaveLength(0);
  await dialog.getByLabel("Approved by").selectOption("actor-1");
  await dialog.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.calls.find((c) => c.path === "workspace/apply")!.body).toEqual({ actor_id: "actor-1", approval_token: "tok-123" });
  await expect(page.getByText("Applied", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("a preview that cannot fast-forward offers no apply", async ({ page }) => {
  const refused = { ...preview, fast_forward_possible: false, approval_token: null, refusal_reason: "Your branch moved since the workspace was created." };
  const { errors } = await open(page, "agents", ((id) => ({ workspaces: { [id]: workspace() }, previews: { [id]: refused } })) as Over);
  await page.getByRole("button", { name: "Preview changes" }).click();
  await expect(page.getByText("Your branch moved since the workspace was created.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply to my repository" })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("check runs show the observed boundary and flag an unconfined run", async ({ page }) => {
  const checks = [
    { id: "cr-1", change_id: "x", state: "CLEANED", boundary: "APPCONTAINER", network: false, exit_code: 0, timed_out: false, created_at: NOW },
    { id: "cr-2", change_id: "x", state: "CLEANED", boundary: "UNCONFINED", network: null, exit_code: 1, timed_out: false, created_at: NOW },
  ];
  const preset = { change_id: "x", decision: "DENY", freshness: "CURRENT", preset_name: "strict", preset_version: "1", change_type: "code", denials: ["confined_checks is FAIL"] };
  const { errors } = await open(page, "assurance", ((id) => ({ checkRuns: { [id]: checks }, presets: { [id]: preset } })) as Over);
  await expect(page.getByText("Confined (AppContainer)")).toBeVisible();
  await expect(page.getByText("Unconfined (opt-in)")).toBeVisible();
  await expect(page.getByText("1 check run ran unconfined")).toBeVisible();
  await expect(page.getByTestId("preset-denials")).toContainText("confined_checks is FAIL");
  await expect(page.getByText("Denied", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("issuing Passport v2 shows the signed boundary and execution-bearing changes", async ({ page }) => {
  const issued = {
    payload: { change_id: "x", change_revision: 1, lifecycle_state: "ACTIVE", risk_level: "LOW", journal_event_count: 12, journal_integrity: "PASS", launch_records: [], issued_at: NOW,
      execution_boundary: "MIXED", confined_checks: "PASS", runs_later: "PRESENT", policy_decision: "ALLOW", execution_bearing_changes: [{ path: "package.json", category: "npm-scripts" }], limitations: ["Agent runs used different boundaries; not every run was in a verified AppContainer."], diff_coverage: { diff_exercised: "UNKNOWN" } },
    payload_digest: "e".repeat(64), signer_fingerprint: "SHA256:abcd", signer_public_spki_b64: "AAAA", signer_provider: "SOFTWARE", signer_identity: "Sentinel Passport v2 ES256", signature_b64: "BBBB",
  };
  const { errors } = await open(page, "passport", ((id) => ({ passportV2: { [id]: issued } })) as Over);
  await page.getByRole("button", { name: "Issue signed passport" }).click();
  const v2 = page.getByTestId("passport-v2");
  await expect(v2.getByText("Mixed (not every launch was boxed)")).toBeVisible();
  await expect(v2.getByText("package.json")).toBeVisible();
  await expect(v2.getByText("SHA256:abcd")).toBeVisible();
  // A plain browser has no native bridge: saving the bundle explains where it works instead.
  await page.getByRole("button", { name: "Save bundle" }).click();
  await expect(page.getByText(/needs the desktop app/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("GitHub Check without an installed App offers install, App creation and the lesser fallback", async ({ page }) => {
  const published = { state: "PUBLISHED", presentation: "COMMIT_STATUS_LESSER", repository: "octo/repo", pr_number: 7, head_sha: "f".repeat(40), execution_boundary: "APPCONTAINER", checks_passed: true, diff_exercised: "PASS", freshness: "CURRENT" };
  const { api, errors } = await open(page, "delivery", (() => ({
    githubCheck: (decline: boolean) => (decline ? published : { state: "GITHUB_APP_NOT_INSTALLED", presentation: "CHECK_RUN", repository: "octo/repo", installation_url: "https://github.com/apps/sentinel-octo/installations/new" }),
  })) as Over);
  await page.route("**/api/v1/providers/github/status", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ provider: "github", configured: true }) }));
  await page.reload();
  await page.getByRole("button", { name: "Publish Check" }).click();
  const prompt = page.getByTestId("github-app-not-installed");
  await expect(prompt.getByRole("link", { name: "Install the App on this repository" })).toHaveAttribute("href", /^https:\/\/github\.com\/apps\//);
  await expect(prompt.getByLabel("GitHub owner")).toHaveValue("octo");
  await prompt.getByRole("button", { name: "Decline and publish a commit status" }).click();
  await expect(page.getByTestId("github-check-published")).toContainText("Published as a commit status");
  expect(api.calls.filter((c) => c.path === "providers/github/checks")).toHaveLength(2);
  expect(errors).toEqual([]);
});
