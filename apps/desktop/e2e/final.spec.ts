import { expect, test, type Page } from "@playwright/test";
import { appendFileSync, readFileSync } from "node:fs";

// The whole retained workflow driven through the real UI against the real backend and a disposable Git repository.
test.describe.configure({ mode: "serial" });

const BASE = "http://127.0.0.1:8000";
const H = () => ({ Authorization: `Bearer ${process.env.CA_E2E_TOKEN}`, "Content-Type": "application/json" });
const api = async (method: string, path: string, body?: unknown) => {
  const r = await fetch(BASE + path, { method, headers: { ...H(), "Idempotency-Key": crypto.randomUUID() }, body: body === undefined ? undefined : JSON.stringify(body) });
  const t = await r.text();
  return { status: r.status, body: t ? JSON.parse(t) : null };
};

let id = "";
let page: Page;
const errors: string[] = [];
const dlg = () => page.getByRole("dialog");
/** Selects the option whose visible text matches (selectOption itself only takes exact labels). */
async function pick(select: import("@playwright/test").Locator, match: RegExp) {
  const label = (await select.locator("option").allTextContents()).find((t) => match.test(t));
  if (!label) throw new Error(`no option matching ${match}`);
  await select.selectOption({ label });
}
const tab = (name: string) => page.getByRole("navigation", { name: "Change sections" }).getByRole("link", { name, exact: true });

test.beforeAll(async ({ browser }) => {
  const c = await api("POST", "/api/v1/changes", { title: "End to end", intent: "Drive the whole workflow through the UI", repository_path: process.env.CA_E2E_REPO });
  expect(c.status).toBe(201);
  id = c.body.id;
  const ctx = await browser.newContext();
  page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  await page.addInitScript((t) => sessionStorage.setItem("ca.dev.token", t), process.env.CA_E2E_TOKEN!);
  await page.goto(`/changes/${id}/authority`);
});
test.afterAll(async () => {
  await page.context().close();
  await api("DELETE", `/api/v1/changes/${id}`);
});

test("authority: create two actors and delegate scopes between them", async () => {
  for (const [name, kind] of [["Ada Lovelace", "HUMAN"], ["Build agent", "AGENT"]] as const) {
    await page.getByRole("button", { name: "Create actor" }).click();
    await dlg().getByLabel("Display name").fill(name);
    await dlg().getByLabel("Kind").selectOption(kind);
    await dlg().getByRole("button", { name: "Create actor" }).click();
    await expect(dlg()).toHaveCount(0);
  }
  await expect(page.getByText("Ada Lovelace · human")).toBeVisible();
  await page.getByRole("button", { name: "Delegate authority" }).click();
  await pick(dlg().getByLabel("Granted by"), /Ada/);
  await pick(dlg().getByLabel("Granted to"), /Build agent/);
  await dlg().getByLabel("Run assurance checks").check();
  await dlg().getByLabel("Fork the Change").check();
  await dlg().getByLabel("Launch a top-level agent").check();
  await dlg().getByRole("button", { name: "Delegate", exact: true }).click();
  await expect(dlg()).toHaveCount(0);
  const row = page.getByRole("row", { name: /Build agent/ });
  await expect(row).toContainText("Active");
  await expect(row).toContainText("assurance.run");
});

test("state: Draft moves to Active now that authority exists", async () => {
  await tab("Overview").click();
  await page.getByRole("button", { name: "Change state" }).click();
  await dlg().getByLabel("New state").selectOption("ACTIVE");
  await dlg().getByRole("button", { name: "Move" }).click();
  await expect(dlg()).toHaveCount(0);
  await expect(page.locator("main header").first().getByText("Active", { exact: true })).toBeVisible();
});

test("evidence: capture, compare, and fork from a checkpoint", async () => {
  await tab("Evidence").click();
  await page.getByRole("button", { name: "Capture baseline" }).click();
  await expect(page.getByRole("row", { name: /baseline/ })).toBeVisible();
  appendFileSync(`${process.env.CA_E2E_REPO}/README.md`, "\nchanged by the e2e run\n");
  await page.getByRole("button", { name: "Capture current" }).click();
  await expect(page.getByRole("table", { name: "Git checkpoints" }).getByRole("row")).toHaveCount(3);
  await expect(page.getByText("README.md").first()).toBeVisible(); // the comparison lists the changed file
  await page.getByRole("row", { name: /baseline/ }).getByRole("button", { name: "Fork from here" }).click();
  await pick(dlg().getByLabel("Forked by"), /Build agent/);
  await dlg().getByLabel("New title").fill("Fork of the e2e change");
  await dlg().getByLabel("New intent").fill("Try the other approach");
  await dlg().getByRole("button", { name: "Create fork" }).click();
  await expect(page.getByRole("heading", { name: "Fork of the e2e change" })).toBeVisible();
  await expect(page.getByText("Forked from")).toBeVisible();
  await page.goto(`/changes/${id}/evidence`);
  await expect(page.getByRole("link", { name: "Fork of the e2e change" })).toBeVisible();
});

test("assurance: a plan is created and gaps are shown, never a fake pass", async () => {
  await tab("Assurance").click();
  await page.getByRole("button", { name: /Create plan|Re-plan/ }).click();
  await expect(page.getByText("Planned checks")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Evaluation" })).toBeVisible();
  await expect(page.getByText("Missing", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/^Passed$/)).toHaveCount(0);
});

test("timeline: chain verifies, and an event opens its inspector", async () => {
  await tab("Timeline").click();
  await expect(page.getByText(/Trace verified · \d+ events/)).toBeVisible();
  await page.getByRole("button", { name: "change.created" }).click();
  await expect(page.getByLabel("Event payload")).toBeVisible();
  await expect(page.getByText(/no re-run|isn't a re-run/)).toBeVisible();
});

test("passport: build, view, and export exactly what the server holds", async () => {
  await tab("Passport").click();
  await page.getByRole("button", { name: "Build passport" }).click();
  await expect(page.getByText("Change passport")).toBeVisible();
  await expect(page.getByText(/Trace verified|Not checked/)).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export JSON" }).click()]);
  const saved = JSON.parse(readFileSync(await download.path(), "utf8"));
  const server = (await api("GET", `/api/v1/changes/${id}/passport`)).body;
  expect(saved).toEqual(server);
  expect(download.suggestedFilename()).toMatch(/^passport-[a-z0-9]+\.json$/);
});

test("recovery: preview is separate from execution and never claims recovery happened", async () => {
  await tab("Recovery").click();
  await page.getByRole("button", { name: /Preview recovery/ }).click();
  await expect(page.getByText(/Recovery plan|Preview failed/).first()).toBeVisible();
  await expect(page.getByText(/^Recovered$/)).toHaveCount(0);
  await expect(page.getByText(/There is no general undo/)).toBeVisible();
});

test("delivery and agents show honest empty states", async () => {
  await tab("Delivery").click();
  await expect(page.getByText("Connect GitHub first")).toBeVisible();
  await expect(page.getByText("No outcomes recorded")).toBeVisible();
  await tab("Agents").click();
  await expect(page.getByText("No agent runs")).toBeVisible();
  await expect(page.getByText(/doesn't observe descendant processes/)).toBeVisible();
});

test("the workflow raised no page or console errors, and no token reached the page", async () => {
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(process.env.CA_E2E_TOKEN!);
  expect(await page.locator("body").innerText()).not.toContain(process.env.CA_E2E_TOKEN!);
});

test("delete removes the Change and returns to the list", async () => {
  const forks = (await api("GET", `/api/v1/changes/${id}/forks`)).body.items as { id: string }[];
  for (const f of forks) await api("DELETE", `/api/v1/changes/${f.id}`); // the fork made earlier must not leak into other specs
  await page.goto(`/changes/${id}`);
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await dlg().getByRole("button", { name: "Delete Change" }).click();
  await expect(page).toHaveURL(/\/changes$/);
  expect((await api("GET", `/api/v1/changes/${id}`)).status).toBe(404);
});
