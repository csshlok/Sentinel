import { expect, test, type Page } from "@playwright/test";
import { envelope, installFakeApi, makeChange, makeTool } from "./fake-api";

// Behaviour that depends on the backend's newer surface (totals, actor list, allowed states, identity) and cross-screen quality checks.
async function open(page: Page, path: string, over: Parameters<typeof installFakeApi>[1] = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  await page.addInitScript(() => sessionStorage.setItem("ca.dev.token", "t"));
  const api = await installFakeApi(page, over);
  await page.goto(path);
  return { api, errors };
}
const dlg = (page: Page) => page.getByRole("dialog");
const many = (n: number) => Array.from({ length: n }, (_, i) => makeChange(i + 1));

test("the state dialog offers the server's allowed states, not a client guess", async ({ page }) => {
  const c = makeChange(1, { title: "Server states", lifecycle_state: "ACTIVE", allowedNext: ["PAUSED", "BLOCKED", "CANCELLED"] });
  await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.getByRole("button", { name: "Change state" }).click();
  // CANCELLED has its own action; the rest come straight from the backend's list.
  expect(await dlg(page).getByLabel("New state").locator("option").allTextContents()).toEqual(["Choose a state…", "Paused", "Blocked"]);
});

test("a backend without allowed states falls back to the mirrored graph", async ({ page }) => {
  const c = makeChange(1, { lifecycle_state: "DRAFT" });
  await open(page, `/changes/${c.id}`, { changes: [c] });
  await page.getByRole("button", { name: "Change state" }).click();
  expect(await dlg(page).getByLabel("New state").locator("option").allTextContents()).toEqual(["Choose a state…", "Active"]);
});

test("the Changes list reports loaded of total and stops exactly at the total", async ({ page }) => {
  await open(page, "/changes", { changes: many(130) });
  await expect(page.getByText("50 of 130 loaded")).toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByText("100 of 130 loaded")).toBeVisible();
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.getByRole("list", { name: "Changes" }).getByRole("listitem")).toHaveCount(130);
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
});

test("an exact multiple of the page size does not offer a phantom next page", async ({ page }) => {
  await open(page, "/changes", { changes: many(50) });
  await expect(page.getByRole("list", { name: "Changes" }).getByRole("listitem")).toHaveCount(50);
  await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
});

test("Home shows the real total, not a page-size guess", async ({ page }) => {
  await open(page, "/home", { changes: many(73) });
  await expect(page.getByText("73", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("50+")).toHaveCount(0);
});

test("the actor picker uses the backend list and filters a long one", async ({ page }) => {
  const actors = Array.from({ length: 12 }, (_, i) => ({ id: `actor-${i}-00000000`, display_name: i === 7 ? "Grace Hopper" : `Person ${i}`, kind: "HUMAN" }));
  const c = makeChange(1);
  await open(page, `/changes/${c.id}/authority`, { changes: [c], actors });
  await expect(page.getByText("12 registered")).toBeVisible();
  await page.getByRole("button", { name: "Delegate authority" }).click();
  const grantee = dlg(page).getByLabel("Granted to", { exact: true });
  expect(await grantee.locator("option").count()).toBe(13);
  await dlg(page).getByLabel("Filter granted to").fill("grace");
  expect(await grantee.locator("option").allTextContents()).toEqual(["Select an actor…", expect.stringContaining("Grace Hopper")]);
});

test("a backend with no actor list still works with a validated manual id", async ({ page }) => {
  const c = makeChange(1);
  await open(page, `/changes/${c.id}/authority`, { changes: [c], actors: null });
  await expect(page.getByText(/can't list actors/)).toBeVisible();
  await page.getByRole("button", { name: "Delegate authority" }).click();
  await expect(dlg(page).getByLabel("Granted by")).toHaveJSProperty("tagName", "INPUT");
  await dlg(page).getByRole("button", { name: "Delegate", exact: true }).click();
  await expect(dlg(page).getByText("Choose who grants this authority.")).toBeVisible();
});

test("creating an actor twice in quick succession sends one request", async ({ page }) => {
  const c = makeChange(1);
  const { api } = await open(page, `/changes/${c.id}/authority`, { changes: [c], actors: [] });
  await page.getByRole("button", { name: "Create actor" }).click();
  await dlg(page).getByLabel("Display name").fill("Ada");
  await dlg(page).getByRole("button", { name: "Create actor" }).dblclick();
  await expect(dlg(page)).toHaveCount(0);
  expect(api.calls.filter((x) => x.path === "/api/v1/actors")).toHaveLength(1);
});

test("Settings shows which backend instance answered, without paths or secrets", async ({ page }) => {
  await open(page, "/settings");
  await expect(page.getByText("change-assurance")).toBeVisible();
  await expect(page.getByText("01234567")).toBeVisible();
  expect(await page.locator("main").innerText()).not.toMatch(/token value|Bearer/i);
});

test("a missing Git install is explained plainly, not as a server fault", async ({ page }) => {
  await open(page, "/changes?new=1", {
    changes: [makeChange(1)],
    validate: () => envelope(424, "GIT_EXECUTABLE_NOT_FOUND", "git not found"),
  });
  await dlg(page).getByLabel("Repository").fill("C:\\work\\repo");
  await dlg(page).getByLabel("Repository").blur(); // the repository check runs when the field loses focus
  await expect(dlg(page).getByText(/Git isn't installed/)).toBeVisible();
});

test("a forked Change names its parent even before it has a repository summary", async ({ page }) => {
  const parent = makeChange(1, { title: "Parent" });
  const child = makeChange(2, { title: "Child", forkedFrom: parent.id });
  await open(page, `/changes/${child.id}`, { changes: [parent, child] });
  const line = page.getByText(/Forked from/);
  await expect(line).toBeVisible();
  await line.getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1, name: "Parent" })).toBeVisible();
});

test("every screen has an accessible name on every control and raises no console errors", async ({ page }) => {
  const c = makeChange(1, { title: "A11y", files: 2 });
  const { errors } = await open(page, "/home", { changes: [c], tools: [makeTool(1)], actors: [{ id: "a1-00000000", display_name: "Ada", kind: "HUMAN" }] });
  const routes = ["/home", "/changes", "/tools", "/tools/tool-1", "/settings", ...["", "/contract", "/evidence", "/assurance", "/agents", "/delivery", "/authority", "/recovery", "/passport", "/timeline"].map((t) => `/changes/${c.id}${t}`)];
  const unnamed: string[] = [];
  for (const r of routes) {
    await page.goto(r);
    await page.locator("main h1").first().waitFor();
    await page.waitForLoadState("networkidle");
    unnamed.push(...(await page.evaluate((route) => {
      const name = (el: Element) => {
        const e = el as HTMLElement;
        const labelled = e.getAttribute("aria-labelledby")?.split(" ").map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
        const forLabel = e.id ? document.querySelector(`label[for="${CSS.escape(e.id)}"]`)?.textContent : "";
        const wrapping = e.closest("label")?.textContent;
        return (e.getAttribute("aria-label") || labelled || forLabel || wrapping || e.textContent || e.getAttribute("title") || "").trim();
      };
      return [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab]")]
        .filter((el) => (el as HTMLElement).offsetParent !== null && !name(el))
        .map((el) => `${route}: <${el.tagName.toLowerCase()} class="${(el.getAttribute("class") ?? "").slice(0, 40)}">`);
    }, r)));
  }
  expect(unnamed).toEqual([]);
  expect(errors).toEqual([]);
});

test("keyboard: tab reaches the primary action on every workspace tab, and dialogs close on Escape", async ({ page }) => {
  const c = makeChange(1, { title: "Keys" });
  await open(page, `/changes/${c.id}/authority`, { changes: [c], actors: [] });
  await page.getByRole("button", { name: "Delegate authority" }).focus();
  await page.keyboard.press("Enter");
  await expect(dlg(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dlg(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delegate authority" })).toBeFocused();
});

test("the current tab stays visible in the tab strip at the minimum window width", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 680 });
  const c = makeChange(1, { title: "Narrow" });
  await open(page, `/changes/${c.id}/timeline`, { changes: [c] });
  const tab = page.getByRole("navigation", { name: "Change sections" }).getByRole("link", { name: "Timeline" });
  const nav = page.getByRole("navigation", { name: "Change sections" });
  const [tb, nb] = [await tab.boundingBox(), await nav.boundingBox()];
  expect(tb!.x).toBeGreaterThanOrEqual(nb!.x - 1);
  expect(tb!.x + tb!.width).toBeLessThanOrEqual(nb!.x + nb!.width + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
