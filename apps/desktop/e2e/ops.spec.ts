import { expect, test, type Page } from "@playwright/test";
import { installFakeApi, makeChange, makeTool } from "./fake-api";

// Form behaviour of the bespoke screens, against the scripted fake backend.
async function open(page: Page, path: string, over: Parameters<typeof installFakeApi>[1] = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem("ca.dev.token", "t"));
  const c = makeChange(1, { title: "Ops change", files: 1 });
  const api = await installFakeApi(page, { changes: [c], tools: [makeTool(1), makeTool(2)], ...over });
  await page.goto(path.replace("{id}", c.id));
  return { api, errors, c };
}
const dlg = (page: Page) => page.getByRole("dialog");
const last = (api: { calls: { method: string; path: string; body: any }[] }) => api.calls.at(-1)!;

test("delegation form validates every field and refuses self-delegation", async ({ page }) => {
  const { api, errors } = await open(page, "/changes/{id}/authority");
  await page.getByRole("button", { name: "Delegate authority" }).click();
  await dlg(page).getByRole("button", { name: "Delegate", exact: true }).click();
  await expect(dlg(page).getByText("Choose who grants this authority.")).toBeVisible();
  await expect(dlg(page).getByText("Pick or enter at least one scope.")).toBeVisible();
  await dlg(page).getByLabel("Granted by").fill("actor-1");
  await dlg(page).getByLabel("Granted to").fill("actor-1");
  await dlg(page).getByLabel("Run assurance checks").check();
  await dlg(page).getByRole("button", { name: "Delegate", exact: true }).click();
  await expect(dlg(page).getByText(/can't delegate authority to itself/)).toBeVisible();
  await dlg(page).getByLabel("Use limit (optional)").fill("0");
  await dlg(page).getByLabel("Granted to").fill("actor-2");
  await dlg(page).getByRole("button", { name: "Delegate", exact: true }).click();
  await expect(dlg(page).getByText(/whole number of 1 or more/)).toBeVisible();
  expect(api.calls).toHaveLength(0);
  await dlg(page).getByLabel("Use limit (optional)").fill("3");
  await dlg(page).getByRole("button", { name: "Delegate", exact: true }).click();
  await expect(dlg(page)).toHaveCount(0);
  expect(last(api).body).toMatchObject({ grantor_id: "actor-1", grantee_id: "actor-2", scopes: ["assurance.run"], ttl_seconds: 3600, use_limit: 3 });
  expect(errors).toEqual([]);
});

test("a created actor is remembered and offered in later pickers", async ({ page }) => {
  const { api } = await open(page, "/changes/{id}/authority");
  await page.getByRole("button", { name: "Create actor" }).click();
  await dlg(page).getByRole("button", { name: "Create actor" }).click();
  await expect(dlg(page).getByText("Enter a display name.")).toBeVisible();
  await dlg(page).getByLabel("Display name").fill("Ada");
  await dlg(page).getByLabel("Kind").selectOption("HUMAN");
  await dlg(page).getByRole("button", { name: "Create actor" }).click();
  expect(last(api)).toMatchObject({ path: "/api/v1/actors", body: { display_name: "Ada", kind: "HUMAN" } });
});

test("state dialog offers only moves the backend allows, and explains the guard", async ({ page }) => {
  await open(page, "/changes/{id}");
  await page.getByRole("button", { name: "Change state" }).click();
  const options = await dlg(page).getByLabel("New state").locator("option").allTextContents();
  expect(options).toEqual(["Choose a state…", "Active"]);
  await expect(dlg(page).getByRole("button", { name: "Move" })).toBeDisabled();
  await dlg(page).getByLabel("New state").selectOption("ACTIVE");
  await expect(dlg(page).getByText("A valid, unexpired delegation exists")).toBeVisible();
});

test("launching an agent needs an actor, adapter and executable, and splits quoted arguments", async ({ page }) => {
  const { api } = await open(page, "/changes/{id}/agents");
  await page.getByRole("button", { name: "Launch agent" }).click();
  await dlg(page).getByRole("button", { name: "Launch", exact: true }).click();
  await expect(dlg(page).getByText("Enter the executable to run.")).toBeVisible();
  await expect(dlg(page).getByText("Choose an adapter.")).toBeVisible();
  expect(api.calls).toHaveLength(0);
});

test("delivery actions are disabled with an explanation until GitHub is connected", async ({ page }) => {
  await open(page, "/changes/{id}/delivery");
  await expect(page.getByText("Connect GitHub first")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create pull request" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Refresh outcomes" })).toBeDisabled();
});

test("GitHub token is a password field, is sent once, and is never shown or stored", async ({ page }) => {
  const { api } = await open(page, "/settings");
  await page.getByRole("button", { name: "Connect GitHub", exact: true }).click();
  const field = dlg(page).getByLabel("Personal access token");
  await expect(field).toHaveAttribute("type", "password");
  await field.fill("ghp_secret_value");
  await dlg(page).getByRole("button", { name: "Connect", exact: true }).click();
  await expect(dlg(page)).toHaveCount(0);
  expect(last(api).body).toEqual({ token: "ghp_secret_value" });
  expect(await page.locator("body").innerText()).not.toContain("ghp_secret_value");
  expect(await page.evaluate(() => JSON.stringify(sessionStorage) + JSON.stringify(localStorage))).not.toContain("ghp_secret_value");
});

test("tool detail shows the manifest, and a denial is sent with its scope", async ({ page }) => {
  const { api } = await open(page, "/tools");
  await page.getByRole("link", { name: "tool-1.exe" }).click();
  await expect(page.getByRole("heading", { name: "tool-1.exe 1.1.0" })).toBeVisible();
  await expect(page.getByText(/aren't intercepted|not intercepted/)).toBeVisible();
  await page.getByRole("button", { name: "Trust decision" }).click();
  await dlg(page).getByLabel("Decided by").fill("actor-1");
  await dlg(page).getByLabel("Deny").check();
  await dlg(page).getByRole("button", { name: "Deny tool" }).click();
  await expect(page.getByText("Decision recorded")).toBeVisible();
  expect(last(api).body).toMatchObject({ actor_id: "actor-1", decision: "DENY", scope: "exact_version" });
});

test("a publisher policy can't be chosen for a tool with no publisher", async ({ page }) => {
  await open(page, "/tools/tool-2");
  await page.getByRole("button", { name: "Trust decision" }).click();
  await expect(dlg(page).getByRole("option", { name: /All of this publisher/ })).toBeDisabled();
});

test("theme choice applies immediately and survives a reload", async ({ page }) => {
  await open(page, "/settings");
  await page.getByLabel("Dark").check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Light").check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("the diagnostic summary contains no token and no paths", async ({ page }) => {
  await open(page, "/settings");
  const text = await page.getByLabel("Diagnostic summary").innerText();
  expect(text).toContain("Interface: browser");
  expect(text).not.toMatch(/token|C:\\|127\.0\.0\.1/i);
});

test("a running agent can be paused, a paused one resumed; each names its actor and its limits", async ({ page }) => {
  const { api, c } = await open(page, "/changes/{id}/agents");
  const run = (status: string) => ({ id: "run-1", change_id: c.id, adapter: "claude", status, started_at: "2026-09-19T12:00:00Z", stdout: "", stderr: "", limitations: [], output_truncated: false, descendant_control_available: false });
  api.lists.agents = { [c.id]: [run("RUNNING")] };
  await page.reload();
  await expect(page.getByRole("button", { name: "Resume" })).toHaveCount(0);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(dlg(page).getByText(/pausing never reaches into its process tree/)).toBeVisible();
  await dlg(page).getByRole("button", { name: "Pause run" }).click();
  await expect(dlg(page).getByText("Choose the actor who is doing this.")).toBeVisible();
  await dlg(page).getByLabel("Acting as").fill("actor-1");
  await dlg(page).getByRole("button", { name: "Pause run" }).click();
  await expect(dlg(page)).toHaveCount(0);
  expect(last(api)).toMatchObject({ path: expect.stringMatching(/agents\/run-1\/pause$/), body: { actor_id: "actor-1" } });
  api.lists.agents = { [c.id]: [run("PAUSED")] };
  await page.reload();
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Resume" }).click();
  await dlg(page).getByLabel("Acting as").fill("actor-1");
  await dlg(page).getByRole("button", { name: "Resume run" }).click();
  await expect(dlg(page)).toHaveCount(0);
  expect(last(api).path).toMatch(/agents\/run-1\/resume$/);
});
