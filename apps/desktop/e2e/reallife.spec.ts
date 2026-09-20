import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { appendFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Real-life usage: pull a real public repository from GitHub and drive Sentinel over it, against the real backend.
// Skipped (not failed) when there is no network, so an offline machine still runs the rest of the suite.
test.describe.configure({ mode: "serial" });

const REPO_URL = "https://github.com/csshlok/vthacks14";
let clone = "";
let cloned = false;
let changeId = "";

test.beforeAll(() => {
  try {
    const dir = mkdtempSync(join(tmpdir(), "sentinel-reallife-"));
    clone = join(dir, "vthacks14 clone");
    execFileSync("git", ["clone", "--depth", "1", "--quiet", REPO_URL, clone], { timeout: 120_000, stdio: "ignore" });
    execFileSync("git", ["config", "user.email", "e2e@example.invalid"], { cwd: clone });
    execFileSync("git", ["config", "user.name", "E2E"], { cwd: clone });
    cloned = true;
  } catch {
    cloned = false;
  }
});

// The real backend is shared with later specs (smoke expects an empty list), so this spec removes what it creates.
test.afterAll(async () => {
  if (!changeId) return;
  await fetch(`http://127.0.0.1:8000/api/v1/changes/${changeId}`, { method: "DELETE", headers: { Authorization: `Bearer ${process.env.CA_E2E_TOKEN}` } }).catch(() => undefined);
});

test("a cloned GitHub repository can be taken from creation to a verified trace", async ({ page }) => {
  test.skip(!cloned, "could not clone from GitHub (offline?)");
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript((t) => sessionStorage.setItem("ca.dev.token", t), process.env.CA_E2E_TOKEN!);

  // Walkthrough starts with nothing done, and the prompt is shown on Home.
  await page.goto("/home");
  await expect(page.getByText("New to Sentinel?")).toBeVisible();
  await page.getByRole("link", { name: "Take the walkthrough" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Walkthrough" })).toBeVisible();
  // Earlier specs share this backend and may have registered actors, so don't assert an exact starting count.
  const before = Number(/(\d) of 8/.exec(await page.getByRole("status").filter({ hasText: "steps detected" }).innerText())![1]);

  // Create a Change over the cloned repo.
  await page.goto("/changes?new=1");
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await dialog.getByLabel("Repository").fill(clone);
  await dialog.getByLabel("Title").fill("Real repo: try Sentinel on vthacks14");
  await expect(dialog.getByText(/Git repository ·/)).toBeVisible();
  await dialog.getByLabel("Intent").fill("Exercise the whole flow on a real repository pulled from GitHub.");
  await dialog.getByRole("button", { name: "Create Change" }).click();
  await expect(page).toHaveURL(/\/changes\/[^/]+$/);
  changeId = page.url().split("/").pop()!;
  await expect(page.getByRole("heading", { level: 1, name: "Real repo: try Sentinel on vthacks14" })).toBeVisible();

  // The new Change shows up in the sidebar's recent list.
  await expect(page.getByRole("list", { name: "Recent Changes" }).getByRole("link", { name: /Real repo/ })).toBeVisible();

  // Evidence: baseline, edit a real file, current, and the comparison sees the edit.
  await page.getByRole("navigation", { name: "Change sections" }).getByRole("link", { name: "Evidence", exact: true }).click();
  await page.getByRole("button", { name: "Capture baseline" }).click();
  await expect(page.getByRole("row", { name: /baseline/ })).toBeVisible();
  appendFileSync(join(clone, "README.md"), "\nedited during the Sentinel real-life test\n");
  await page.getByRole("button", { name: "Capture current" }).click();
  await expect(page.getByRole("table", { name: "Git checkpoints" }).getByRole("row")).toHaveCount(3);
  await expect(page.getByText("README.md").first()).toBeVisible();

  // Timeline verifies.
  await page.getByRole("navigation", { name: "Change sections" }).getByRole("link", { name: "Timeline", exact: true }).click();
  await expect(page.getByText(/Trace verified · \d+ events/)).toBeVisible();

  // The walkthrough now detects the Change.
  await page.goto("/walkthrough");
  await expect(page.getByRole("status").filter({ hasText: `${before + 1} of 8 steps detected as done` })).toBeVisible();
  expect(errors).toEqual([]);
});

test("Settings tells you what each capability is for and how to use the terminal UI", async ({ page }) => {
  await page.addInitScript((t) => sessionStorage.setItem("ca.dev.token", t), process.env.CA_E2E_TOKEN!);
  await page.goto("/settings");
  const terminal = page.locator("section", { hasText: "Terminal (TUI)" });
  await expect(terminal.getByLabel("3. Start the terminal UI")).toContainText("python -m backend.app.tui.app --api-url http://");
  await expect(terminal.getByLabel("2. Load the API token for this shell")).toContainText("CHANGE_ASSURANCE_API_TOKEN");
  expect(await terminal.innerText()).not.toContain(process.env.CA_E2E_TOKEN!); // the token itself is never shown
  const caps = page.getByRole("list", { name: "Capabilities" });
  await expect(caps.getByText(/Works with: Authority/).first()).toBeVisible();
  await expect(caps.getByText("Not available: Sentinel records the top-level run only.", { exact: false })).toBeVisible();
});
