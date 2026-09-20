import { expect, test, type Page } from "@playwright/test";

// The suite is order-dependent on purpose: unauthenticated checks first, then one authenticated flow.
test.describe.configure({ mode: "serial" });

const primaryNav = (page: Page) => page.getByRole("navigation", { name: "Primary" });

function trackPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function signIn(page: Page) {
  await page.goto("/settings");
  await page.getByLabel("Development API token").fill(process.env.CA_E2E_TOKEN!);
  await page.getByRole("button", { name: "Use token" }).click();
  await expect(page.getByRole("link", { name: /Connected/ })).toBeVisible();
}

test("loads and shows real backend health without a token", async ({ page }) => {
  const errors = trackPageErrors(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/home$/);
  await expect(page).toHaveTitle("Sentinel");
  await expect(page.getByRole("heading", { level: 1, name: "Home" })).toBeVisible();

  // Health is an open route, so the service is reachable but the session is not signed in.
  await expect(page.getByRole("link", { name: /Not signed in/ })).toBeVisible();
  await primaryNav(page).getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText(/Reachable · API/)).toBeVisible();
  expect(errors).toEqual([]);
});

test("unauthenticated routes show the authentication message, not a generic failure", async ({ page }) => {
  const errors = trackPageErrors(page);
  await page.goto("/changes");
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Authentication required");
  await expect(alert).toContainText("A bearer token is required.");
  await expect(alert.getByRole("link", { name: "Settings" })).toBeVisible();

  await page.goto("/tools");
  await expect(page.getByRole("alert")).toContainText("Authentication required");
  expect(errors).toEqual([]);
});

test("navigation moves between pages and updates the URL, heading and focus", async ({ page }) => {
  const errors = trackPageErrors(page);
  await page.goto("/changes");
  const nav = primaryNav(page);

  await nav.getByRole("link", { name: "Tools" }).click();
  await expect(page).toHaveURL(/\/tools$/);
  await expect(page.getByRole("heading", { level: 1, name: "Tools" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Tools" })).toHaveAttribute("aria-current", "page");

  await nav.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.locator("#main")).toBeFocused();

  await page.goto("/does-not-exist");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("authenticated flow: token, empty state, validate, create, workspace tabs", async ({ page }) => {
  const errors = trackPageErrors(page);
  const token = process.env.CA_E2E_TOKEN!;
  const repo = process.env.CA_E2E_REPO!;

  await signIn(page);
  await expect(page.getByRole("list", { name: "Capabilities" })).toBeVisible();

  // The token must not be rendered or persisted beyond the tab's session storage.
  expect(await page.locator("body").innerHTML()).not.toContain(token);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(token);
  expect(page.url()).not.toContain(token);

  await primaryNav(page).getByRole("link", { name: "Changes" }).click();
  await expect(page.getByRole("heading", { name: "No Changes yet" })).toBeVisible();

  await page.getByRole("button", { name: "New Change" }).click();
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await expect(dialog).toBeVisible();

  // Inline validation before anything is sent.
  await dialog.getByRole("button", { name: "Create Change" }).click();
  await expect(dialog.getByText("Enter the repository path.")).toBeVisible();
  await expect(dialog.getByText("Enter a short title for this Change.")).toBeVisible();
  await expect(dialog.getByText("Describe the intended outcome.")).toBeVisible();

  // The repository is checked as soon as the field loses focus.
  await dialog.getByLabel("Repository").fill(repo);
  await dialog.getByLabel("Title").fill("E2E smoke change");
  await expect(dialog.getByText(/Git repository ·/)).toBeVisible();
  await dialog.getByLabel("Intent").fill("Prove the desktop UI drives the real backend.");
  await dialog.getByRole("button", { name: "Create Change" }).click();

  await expect(page).toHaveURL(/\/changes\/[^/]+$/);
  await expect(page.getByRole("heading", { level: 1, name: "E2E smoke change" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Lifecycle" })).toBeVisible();

  const tabs = page.getByRole("navigation", { name: "Change sections" });
  await tabs.getByRole("link", { name: "Contract" }).click();
  await expect(page.getByRole("button", { name: "Edit contract" })).toBeVisible();
  await tabs.getByRole("link", { name: "Evidence" }).click();
  await expect(page.getByRole("heading", { name: "Git checkpoints" })).toBeVisible();
  await tabs.getByRole("link", { name: "Timeline" }).click();
  await expect(page.getByText("change.created")).toBeVisible();

  await primaryNav(page).getByRole("link", { name: "Changes" }).click();
  await expect(page.getByRole("list", { name: "Changes", exact: true }).getByText("E2E smoke change")).toBeVisible();
  expect(errors).toEqual([]);
});

test("command palette opens with Ctrl+K and jumps to a Change or a page", async ({ page }) => {
  const errors = trackPageErrors(page);
  await signIn(page);
  await page.goto("/tools");
  await expect(page.getByRole("heading", { level: 1, name: "Tools" })).toBeVisible(); // the shortcut listener exists once the shell has mounted

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Search" });
  await expect(palette).toBeVisible();
  await palette.getByPlaceholder(/Search Changes/).fill("E2E smoke");
  await palette.getByRole("option", { name: /E2E smoke change/ }).click();
  await expect(page).toHaveURL(/\/changes\/[^/]+$/);
  await expect(page.getByRole("heading", { level: 1, name: "E2E smoke change" })).toBeVisible();

  await page.keyboard.press("Control+k");
  await palette.getByRole("option", { name: /Settings/ }).click();
  await expect(page).toHaveURL(/\/settings$/);
  expect(errors).toEqual([]);
});

test("?new=1 opens the create dialog and closing it clears the address", async ({ page }) => {
  await signIn(page);
  await page.goto("/changes?new=1");
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/changes$/);
});

test("an invalid repository shows an error next to the field", async ({ page }) => {
  await signIn(page);
  await primaryNav(page).getByRole("link", { name: "Changes" }).click();
  await page.getByRole("button", { name: "New Change" }).click();
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await dialog.getByLabel("Repository").fill("Z:\\definitely\\not\\a\\repo");
  await dialog.getByLabel("Title").click();
  await expect(dialog.getByRole("status").locator(".text-danger")).toBeVisible();
});
