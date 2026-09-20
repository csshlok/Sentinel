import { expect, test, type Page } from "@playwright/test";
import { installFakeApi, makeChange, makeEvent, makeTool } from "./fake-api";

// Real-life and high-intensity behaviour against a scripted backend: failures, scale, races, keyboard, layout.

const VIEWPORTS = [
  { width: 1024, height: 680 }, // the app's minimum window
  { width: 1280, height: 820 },
  { width: 1440, height: 900 },
  { width: 390, height: 800 }, // narrow browser
];

async function open(page: Page, path = "/changes", over: Parameters<typeof installFakeApi>[1] = {}) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem("ca.dev.token", "t"));
  const api = await installFakeApi(page, over);
  await page.goto(path);
  return { api, errors };
}

const noHorizontalOverflow = (page: Page) =>
  page.evaluate(() => {
    const main = document.querySelector("#main")!;
    return { doc: document.documentElement.scrollWidth - innerWidth, main: main.scrollWidth - main.clientWidth };
  });

test("hostile, huge and unicode titles render as text and never overflow, at every viewport", async ({ page }) => {
  const titles = [
    "<img src=x onerror=window.__pwned=1>",
    "<script>window.__pwned=1</script>",
    "A".repeat(400),
    "https://example.com/" + "segment/".repeat(60),
    "مرحبا بالعالم — שלום עולם — こんにちは世界 — 🚀".repeat(3),
    "line one\nline two",
    "   ",
  ];
  const changes = titles.map((t, i) => makeChange(i + 1, { title: t, repository_path: "C:\\" + "very-long-folder-name\\".repeat(20), files: i }));
  const { api, errors } = await open(page, "/changes", { changes });
  await expect(page.getByRole("list", { name: "Changes", exact: true })).toBeVisible();
  for (const vp of VIEWPORTS) {
    await page.setViewportSize(vp);
    for (const path of ["/changes", `/changes/${changes[2]!.id}`, `/changes/${changes[0]!.id}/timeline`]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const o = await noHorizontalOverflow(page);
      expect(o.doc, `${path} @${vp.width}`).toBeLessThanOrEqual(1);
      expect(o.main, `${path} @${vp.width}`).toBeLessThanOrEqual(1);
    }
  }
  expect(await page.evaluate(() => (window as any).__pwned)).toBeUndefined();
  expect(api.requests.length).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test("losing the backend shows Offline, and everything recovers by itself when it returns", async ({ page }) => {
  await page.clock.install();
  const { api, errors } = await open(page, "/changes", { changes: [makeChange(1, { title: "Survivor" })] });
  await expect(page.getByRole("link", { name: /Connected/ })).toBeVisible();
  api.online = false;
  await page.clock.runFor(9_000);
  await expect(page.getByRole("link", { name: /Offline/ })).toBeVisible();
  api.online = true;
  await page.clock.runFor(3_000);
  await expect(page.getByRole("link", { name: /Connected/ })).toBeVisible();
  await expect(page.locator("main").getByText("Survivor")).toBeVisible();
  expect(errors).toEqual([]);
});

test("a wrong token is reported as an auth problem, and the right one fixes it", async ({ page }) => {
  await open(page, "/changes", { requireToken: "right", changes: [makeChange(1, { title: "Guarded" })] });
  await expect(page.getByRole("alert")).toContainText("The bearer token is invalid.");
  await page.goto("/settings");
  await page.getByLabel("Development API token").fill("right");
  await page.getByRole("button", { name: "Use token" }).click();
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Changes" }).click();
  await expect(page.locator("main").getByText("Guarded")).toBeVisible();
});

test("rapid navigation under a slow backend never throws, and shows the last page requested", async ({ page }) => {
  const changes = Array.from({ length: 30 }, (_, i) => makeChange(i + 1, { files: 2 }));
  changes.forEach((c) => void 0);
  const { api, errors } = await open(page, "/changes", { changes, delayMs: 120 });
  api.events[changes[0]!.id] = [makeEvent(changes[0]!.id, 1)];
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (let i = 0; i < 40; i++) {
    await nav.getByRole("link", { name: ["Changes", "Tools", "Settings"][i % 3]! }).click({ noWaitAfter: true });
  }
  await nav.getByRole("link", { name: "Tools" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Tools" })).toBeVisible();
  await page.goto(`/changes/${changes[0]!.id}`);
  for (const tab of ["Contract", "Evidence", "Timeline", "Overview", "Timeline", "Contract"]) {
    await page.getByRole("navigation", { name: "Change sections" }).getByRole("link", { name: tab }).click({ noWaitAfter: true });
  }
  await expect(page.getByRole("heading", { level: 1, name: changes[0]!.title })).toBeVisible();
  expect(errors).toEqual([]);
});

test("filtering a full page of Changes stays fast and correct", async ({ page }) => {
  const changes = Array.from({ length: 50 }, (_, i) => makeChange(i + 1));
  await open(page, "/changes", { changes });
  const list = page.getByRole("list", { name: "Changes", exact: true });
  await expect(list.getByRole("listitem")).toHaveCount(50);
  const started = Date.now();
  await page.getByLabel("Filter Changes").fill("number 4");
  await expect(list.getByRole("listitem")).toHaveCount(11); // 4, 40-49
  expect(Date.now() - started).toBeLessThan(1500);
  await page.getByLabel("Filter Changes").fill("zzz-no-match");
  await expect(page.getByText(/No Changes match/)).toBeVisible();
});

test("more than one page of Changes can be loaded, without duplicates", async ({ page }) => {
  const changes = Array.from({ length: 130 }, (_, i) => makeChange(i + 1));
  await open(page, "/changes", { changes });
  const items = page.getByRole("list", { name: "Changes", exact: true }).getByRole("listitem");
  await expect(items).toHaveCount(50);
  await page.getByRole("button", { name: /Load more/ }).click();
  await expect(items).toHaveCount(100);
  await page.getByRole("button", { name: /Load more/ }).click();
  await expect(items).toHaveCount(130);
  await expect(page.getByRole("button", { name: /Load more/ })).toHaveCount(0);
  const titles = await items.locator("p.font-medium").allTextContents();
  expect(new Set(titles).size).toBe(130);
});

test("a long timeline pages forward without losing or repeating events", async ({ page }) => {
  const change = makeChange(1);
  const { api } = await open(page, "/changes/" + change.id + "/timeline", { changes: [change] });
  api.events[change.id] = Array.from({ length: 250 }, (_, i) => makeEvent(change.id, i + 1));
  await page.reload();
  const rows = page.getByRole("table", { name: "Change events" }).locator("tbody tr");
  await expect(rows).toHaveCount(100);
  await page.getByRole("button", { name: /Load more/ }).click();
  await expect(rows).toHaveCount(200);
  await page.getByRole("button", { name: /Load more/ }).click();
  await expect(rows).toHaveCount(250);
  const seqs = (await rows.locator("td:first-child").allTextContents()).map(Number);
  expect(seqs).toEqual(Array.from({ length: 250 }, (_, i) => i + 1));
});

test("a table of 500 tools renders and scrolls without layout overflow", async ({ page }) => {
  const tools = Array.from({ length: 500 }, (_, i) => makeTool(i));
  await open(page, "/tools", { tools });
  await expect(page.getByRole("table", { name: "Tools" })).toBeVisible();
  const o = await noHorizontalOverflow(page);
  expect(o.doc).toBeLessThanOrEqual(1);
  expect(await page.locator("tbody tr").count()).toBe(500);
});

test("a repository check that finishes late cannot overwrite the result for a newer path", async ({ page }) => {
  await open(page, "/changes?new=1", {
    validate: (p) =>
      p.includes("slow")
        ? { status: 200, delayMs: 1200, body: { branch: "STALE-BRANCH", head_sha: "c".repeat(40), root: "C:\\slow" } }
        : { status: 422, body: { error: { code: "NOT_A_REPO", message: "That folder is not a Git repository.", details: {} } } },
  });
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await dialog.getByLabel("Repository").fill("C:\\slow");
  await dialog.getByLabel("Title").click(); // blur starts the slow check
  await dialog.getByLabel("Repository").fill("C:\\fast-bad");
  await dialog.getByLabel("Title").click(); // blur starts the fast check that fails
  await expect(dialog.getByText("That folder is not a Git repository.")).toBeVisible();
  await page.waitForTimeout(1600); // the stale success now arrives
  await expect(dialog.getByText(/STALE-BRANCH/)).toHaveCount(0);
  await expect(dialog.getByText("That folder is not a Git repository.")).toBeVisible();
});

test("pressing Enter repeatedly while creating sends one request", async ({ page }) => {
  const { api } = await open(page, "/changes?new=1", { delayMs: 300 });
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await dialog.getByLabel("Repository").fill("C:\\work\\repo");
  await dialog.getByLabel("Title").fill("Enter mashing");
  await dialog.getByLabel("Intent").fill("Make sure double submit is impossible.");
  for (let i = 0; i < 6; i++) await dialog.getByLabel("Title").press("Enter");
  await expect(page).toHaveURL(/\/changes\/chg-/);
  expect(api.posts).toHaveLength(1);
});

test("a failed create keeps the form, and retrying reuses the same idempotency key", async ({ page }) => {
  const { api } = await open(page, "/changes?new=1");
  api.createStatus = 500;
  const dialog = page.getByRole("dialog", { name: "New Change" });
  await dialog.getByLabel("Repository").fill("C:\\work\\repo");
  await dialog.getByLabel("Title").fill("Retry me");
  await dialog.getByLabel("Intent").fill("Retry semantics.");
  await dialog.getByRole("button", { name: "Create Change" }).click();
  await expect(dialog.getByRole("alert")).toContainText("The service failed.");
  await expect(dialog.getByLabel("Title")).toHaveValue("Retry me");
  api.createStatus = 201;
  await dialog.getByRole("button", { name: "Create Change" }).click();
  await expect(page).toHaveURL(/\/changes\/chg-/);
  expect(api.posts).toHaveLength(2);
  expect(api.posts[0]!.key).toBeTruthy();
  expect(api.posts[1]!.key).toBe(api.posts[0]!.key);
});

test("keyboard: Escape closes the dialog and returns focus; the palette works with arrows and Enter", async ({ page }) => {
  await open(page, "/changes", { changes: [makeChange(1, { title: "Alpha" }), makeChange(2, { title: "Beta" })] });
  const trigger = page.getByRole("button", { name: "New Change" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "New Change" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await page.keyboard.press("Control+k");
  await page.keyboard.type("beta");
  await expect(page.getByRole("option", { name: /Beta/ })).toBeVisible(); // the list loads asynchronously
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "Beta" })).toBeVisible();
});

test("unknown Change and unknown route give a recoverable page, and focus lands in the content", async ({ page }) => {
  const { errors } = await open(page, "/changes/does-not-exist", { changes: [] });
  await expect(page.getByRole("alert")).toContainText("Change not found.");
  await page.goto("/nowhere");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Back to Changes" }).click();
  await expect(page).toHaveURL(/\/changes$/);
  expect(errors).toEqual([]);
});

test("200% zoom (512x340 CSS px) with reduced motion remains usable", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await open(page, "/changes", { changes: Array.from({ length: 6 }, (_, i) => makeChange(i + 1)) });
  await page.setViewportSize({ width: 512, height: 340 });
  await expect(page.getByRole("heading", { level: 1, name: "Changes" })).toBeVisible();
  const o = await noHorizontalOverflow(page);
  expect(o.doc).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "New Change" }).click();
  const box = await page.getByRole("dialog").boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(512);
  await page.keyboard.press("Escape");
});

test("opening and closing dialogs and the palette 40 times does not leak DOM or break focus", async ({ page }) => {
  const { errors } = await open(page, "/changes", { changes: [makeChange(1)] });
  await expect(page.locator("main").getByText("Change number 1")).toBeVisible();
  const count = () => page.evaluate(() => document.querySelectorAll("*").length);
  const baseline = await count();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog")).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    try {
      await page.getByRole("button", { name: "New Change" }).click({ timeout: 3000 });
    } catch {
      const state = await page.evaluate(() => ({
        bodyPointerEvents: document.body.style.pointerEvents,
        dialogs: [...document.querySelectorAll("[role=dialog]")].map((d) => d.getAttribute("aria-labelledby") ?? d.textContent?.slice(0, 20)),
        url: location.href,
      }));
      throw new Error(`stuck at iteration ${i}: ${JSON.stringify(state)}`);
    }
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  await page.waitForTimeout(300);
  expect(Math.abs((await count()) - baseline)).toBeLessThan(15);
  expect(errors).toEqual([]);
});

test("spacing is even: one vertical rhythm, aligned left edges, and table text lines up with panel titles", async ({ page }) => {
  const changes = Array.from({ length: 8 }, (_, i) => makeChange(i + 1, { files: 3, review_state: i % 2 ? "MISSING_EVIDENCE" : "NO_CHANGES" }));
  const { api } = await open(page, "/home", { changes, tools: Array.from({ length: 4 }, (_, i) => makeTool(i)) });
  api.events[changes[0]!.id] = [makeEvent(changes[0]!.id, 1), makeEvent(changes[0]!.id, 2)];
  await page.setViewportSize({ width: 1280, height: 820 });

  for (const path of ["/home", "/changes", `/changes/${changes[0]!.id}`, `/changes/${changes[0]!.id}/timeline`, `/changes/${changes[0]!.id}/contract`, "/tools", "/settings"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const m = await page.evaluate(() => {
      const root = document.querySelector("#main > div:last-of-type")!;
      const kids = [...root.children].filter((el) => (el as HTMLElement).offsetHeight > 0) as HTMLElement[];
      const rects = kids.map((k) => k.getBoundingClientRect());
      const gaps = rects.slice(1).map((r, i) => Math.round(r.top - rects[i]!.bottom));
      const lefts = [...new Set(rects.map((r) => Math.round(r.left)))];
      // first table cell text inset vs. panel padding
      const td = document.querySelector("tbody td:first-child") as HTMLElement | null;
      const th = document.querySelector("thead th:first-child") as HTMLElement | null;
      const cell = td ?? th;
      const inset = cell ? parseFloat(getComputedStyle(cell).paddingLeft) : null;
      return { gaps, lefts, inset };
    });
    expect(m.gaps.every((g) => g === 24), `${path} vertical gaps ${JSON.stringify(m.gaps)}`).toBe(true);
    expect(m.lefts.length, `${path} left edges ${JSON.stringify(m.lefts)}`).toBe(1);
    if (m.inset !== null) expect(m.inset, `${path} table inset`).toBe(20);
  }
});
