import { expect, test, type Page } from "@playwright/test";
import { installFakeApi, makeChange, makeEvent } from "./fake-api";

async function open(page: Page, path: string, over: Parameters<typeof installFakeApi>[1] = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem("ca.dev.token", "t"));
  const api = await installFakeApi(page, over);
  await page.goto(path);
  return { api, errors };
}
const change = () => makeChange(1, { title: "Surface change", files: 2 });
const tab = (page: Page, name: string) => page.getByRole("navigation", { name: "Change sections" }).getByRole("link", { name });

test("changing state moves the Change and sends the bumped revision next time", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.getByRole("button", { name: "Change state" }).click();
  await page.getByLabel("New state").selectOption("ACTIVE");
  await page.getByLabel("Reason (optional)").fill("Starting work");
  await page.getByRole("button", { name: "Move" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(api.calls.at(-1)).toMatchObject({ path: "transition", body: { target_state: "ACTIVE", expected_revision: 1, reason: "Starting work" } });
  await page.getByRole("button", { name: "Change state" }).click();
  await page.getByLabel("New state").selectOption("PAUSED");
  await page.getByRole("button", { name: "Move" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(api.calls.at(-1)!.body.expected_revision).toBe(2);
});

test("a stale revision is explained in the dialog and nothing changes", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.getByRole("button", { name: "Change state" }).click();
  await page.getByLabel("New state").selectOption("ACTIVE");
  c.revision = 9; // someone else changed it
  await page.getByRole("button", { name: "Move" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("modified by someone else");
  expect(c.lifecycle_state).toBe("DRAFT");
  expect(api.calls).toHaveLength(1);
});

test("cancelling a Change disables further actions", async ({ page }) => {
  const c = change();
  await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.getByRole("button", { name: "Cancel Change" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel Change" }).click();
  await expect(page.getByRole("button", { name: "Change state" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Run verification" })).toBeDisabled();
});

test("verification needs a command, splits arguments, and sends them", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.getByRole("button", { name: "Run verification" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  await page.getByLabel("Command").fill("pytest");
  await page.getByLabel("Arguments").fill("-q   tests/unit");
  await page.getByRole("dialog").getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(api.calls.at(-1)).toMatchObject({ path: "verify", body: { executable: "pytest", args: ["-q", "tests/unit"] } });
});

test("refresh cannot be double-fired while it is running", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}`, { changes: [c], delayMs: 250 });
  const btn = page.getByRole("button", { name: "Refresh" });
  await btn.click();
  await btn.click({ force: true }).catch(() => {});
  await expect(btn).toBeEnabled();
  expect(api.calls.filter((x) => x.path === "refresh")).toHaveLength(1);
});

test("editing the contract saves clean arrays with the current revision", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}/contract`, { changes: [c] });
  await page.getByRole("button", { name: "Edit contract" }).click();
  await page.getByLabel("Allowed paths").fill("src/**\n\n  docs/**  \n");
  await page.getByLabel("Required checks").fill("pytest");
  await page.getByLabel("Max risk").selectOption("HIGH");
  await page.getByRole("button", { name: "Save contract" }).click();
  await expect(page.getByRole("button", { name: "Edit contract" })).toBeVisible();
  const body = api.calls.at(-1)!.body;
  expect(body.expected_revision).toBe(1);
  expect(body.contract).toMatchObject({ allowed_paths: ["src/**", "docs/**"], required_checks: ["pytest"], max_risk: "HIGH" });
  await expect(page.getByText("docs/**")).toBeVisible();
});

test("a contract conflict keeps the user's draft and explains what happened", async ({ page }) => {
  const c = change();
  await open(page, `/changes/${c.id}/contract`, { changes: [c] });
  await page.getByRole("button", { name: "Edit contract" }).click();
  await page.getByLabel("Forbidden paths").fill("secrets/**");
  c.revision = 5;
  await page.getByRole("button", { name: "Save contract" }).click();
  await expect(page.getByRole("alert")).toContainText("updated elsewhere");
  await expect(page.getByLabel("Forbidden paths")).toHaveValue("secrets/**");
});

test("capturing evidence shows the capture's limitations", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}/evidence`, { changes: [c] });
  await page.getByRole("button", { name: "Capture baseline" }).click();
  await expect(page.getByText(/file writes are not attributed/)).toBeVisible();
  expect(api.calls.at(-1)!.path).toBe("evidence/baseline");
});

test("passport: empty state, build, digest, limitations and export", async ({ page }) => {
  const c = change();
  await open(page, `/changes/${c.id}/passport`, { changes: [c] });
  await expect(page.getByRole("heading", { name: "No passport yet" })).toBeVisible();
  await page.getByRole("button", { name: "Build passport" }).click();
  await expect(page.getByText("dddddddddddddddd")).toBeVisible();
  await expect(page.getByText("No replay verification.")).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export JSON" }).click()]);
  expect(download.suggestedFilename()).toBe(`passport-${c.id}.json`);
});

test("read-only surfaces show honest empty states and real data when present", async ({ page }) => {
  const c = change();
  const { api, errors } = await open(page, `/changes/${c.id}/agents`, { changes: [c] });
  await expect(page.getByRole("heading", { name: "No agent runs" })).toBeVisible();
  await tab(page, "Delivery").click();
  await expect(page.getByRole("heading", { name: "No outcomes" })).toBeVisible();
  await tab(page, "Authority").click();
  await expect(page.getByRole("heading", { name: "No one has authority yet" })).toBeVisible();
  await tab(page, "Recovery").click();
  await expect(page.getByRole("heading", { name: "No recovery plan" })).toBeVisible();
  await tab(page, "Assurance").click();
  await expect(page.getByText("No baseline checkpoint.")).toBeVisible();
  api.lists.agents = { [c.id]: [{ id: "a1", change_id: c.id, adapter: "claude", status: "PASSED", started_at: "2026-09-19T12:00:00Z", exit_code: 0, stdout: "", stderr: "", limitations: [], output_truncated: false, descendant_control_available: false }] };
  await page.goto(`/changes/${c.id}/agents`);
  await expect(page.getByRole("heading", { name: "claude run" })).toBeVisible();
  await expect(page.getByText("Exited cleanly")).toBeVisible();
  expect(errors).toEqual([]);
});

test("trace verification reports the result without re-executing anything", async ({ page }) => {
  const c = change();
  const { api } = await open(page, `/changes/${c.id}/timeline`, { changes: [c] });
  api.events[c.id] = [makeEvent(c.id, 1), makeEvent(c.id, 2)];
  await page.reload();
  await expect(page.getByText("Trace verified · 2 events")).toBeVisible();
  await page.getByRole("button", { name: "Verify again" }).click();
  await expect(page.getByText("Trace verified · 2 events")).toBeVisible();
});

test("every workspace tab fits at the minimum window and never throws", async ({ page }) => {
  const c = change();
  const { errors } = await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.setViewportSize({ width: 1024, height: 680 });
  for (const t of ["Overview", "Contract", "Evidence", "Assurance", "Agents", "Delivery", "Authority", "Recovery", "Passport", "Timeline"]) {
    await tab(page, t).click();
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), t).toBeLessThanOrEqual(1);
  }
  expect(errors).toEqual([]);
});
