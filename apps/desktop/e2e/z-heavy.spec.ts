import { expect, test } from "@playwright/test";

// Heavy-use scenario against the REAL backend (started by global-setup with a throwaway DB and Git repo).
test.describe.configure({ mode: "serial" });
test.setTimeout(300_000);

const BASE = "http://127.0.0.1:8000";
const H = () => ({ Authorization: `Bearer ${process.env.CA_E2E_TOKEN}`, "Content-Type": "application/json" });
const key = () => crypto.randomUUID();
const post = (path: string, body?: unknown, k = key()) =>
  fetch(BASE + path, { method: "POST", headers: { ...H(), "Idempotency-Key": k }, body: body === undefined ? undefined : JSON.stringify(body) });
const get = (path: string) => fetch(BASE + path, { headers: H() });

const TOTAL = 130;
const metrics: Record<string, unknown> = {};
let seededIds: string[] = [];

async function inBatches<T>(n: number, size: number, fn: (i: number) => Promise<T>): Promise<T[]> {
  const out: T[] = [];
  for (let i = 0; i < n; i += size) out.push(...(await Promise.all(Array.from({ length: Math.min(size, n - i) }, (_, j) => fn(i + j)))));
  return out;
}

test("seed 130 real Changes in concurrent batches with no server errors", async () => {
  const repo = process.env.CA_E2E_REPO!;
  const t0 = Date.now();
  const responses = await inBatches(TOTAL, 10, (i) => post("/api/v1/changes", { title: `Heavy change ${String(i).padStart(3, "0")}`, intent: `Load scenario item ${i}`, repository_path: repo }));
  metrics.seedMs = Date.now() - t0;
  const statuses = responses.map((r) => r.status);
  expect(statuses.filter((s) => s >= 500), "server errors while seeding").toEqual([]);
  expect(new Set(statuses)).toEqual(new Set([201]));
  seededIds = (await Promise.all(responses.map((r) => r.json()))).map((c: any) => c.id);
  expect(new Set(seededIds).size).toBe(TOTAL);
});

test("25 parallel creates with the same idempotency key create exactly one Change", async () => {
  const k = key();
  const body = { title: "Idempotent storm", intent: "Same key, many requests", repository_path: process.env.CA_E2E_REPO };
  const rs = await Promise.all(Array.from({ length: 25 }, () => post("/api/v1/changes", body, k)));
  const codes = rs.map((r) => r.status);
  expect(codes.filter((c) => c >= 500)).toEqual([]);
  const ids = new Set((await Promise.all(rs.filter((r) => r.ok).map((r) => r.json()))).map((c: any) => c.id));
  metrics.stormStatuses = [...new Set(codes)].join(",");
  expect(ids.size, "one logical Change").toBe(1);
  const all: any[] = [];
  for (let offset = 0; ; offset += 50) {
    const page = (await (await get(`/api/v1/changes?limit=50&offset=${offset}`)).json()) as any;
    all.push(...page.items);
    if (page.items.length < 50) break;
  }
  expect(all.filter((c) => c.title === "Idempotent storm")).toHaveLength(1);
});

test("120 concurrent refreshes on one Change never error and keep the event chain ordered", async () => {
  const id = seededIds[0]!;
  const rs = await inBatches(120, 15, () => post(`/api/v1/changes/${id}/refresh`));
  expect(rs.map((r) => r.status).filter((s) => s >= 500)).toEqual([]);
  const events = ((await (await get(`/api/v1/changes/${id}/events?limit=1000`)).json()) as any).items as { seq: number; prev_event_hash: string | null; event_hash: string }[];
  metrics.eventsAfterRefreshStorm = events.length;
  expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1));
  for (let i = 1; i < events.length; i++) expect(events[i]!.prev_event_hash, `chain link ${i}`).toBe(events[i - 1]!.event_hash);
});

test("the UI pages through every real Change without duplicates, and stays fast", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript((t) => sessionStorage.setItem("ca.dev.token", t), process.env.CA_E2E_TOKEN!);
  const t0 = Date.now();
  await page.goto("/changes");
  const items = page.getByRole("list", { name: "Changes" }).getByRole("listitem");
  await expect(items).toHaveCount(50);
  metrics.firstPageMs = Date.now() - t0;
  while (await page.getByRole("button", { name: /Load more/ }).count()) {
    const before = await items.count();
    await page.getByRole("button", { name: /Load more/ }).click();
    await expect.poll(() => items.count()).toBeGreaterThan(before);
  }
  const total = await items.count();
  expect(total).toBeGreaterThanOrEqual(TOTAL + 1);
  const titles = await items.locator("p.font-medium").allTextContents();
  expect(new Set(titles.filter((t) => t.startsWith("Heavy change"))).size).toBe(TOTAL);
  const f0 = Date.now();
  await page.getByLabel("Filter Changes").fill("Heavy change 12");
  await expect(items).toHaveCount(10); // 120-129
  metrics.filterMs = Date.now() - f0;
  expect(metrics.filterMs as number).toBeLessThan(2000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});

test("the change with 100+ events pages through its whole real timeline in order", async ({ page }) => {
  await page.addInitScript((t) => sessionStorage.setItem("ca.dev.token", t), process.env.CA_E2E_TOKEN!);
  await page.goto(`/changes/${seededIds[0]}/timeline`);
  const rows = page.getByRole("table", { name: "Change events" }).locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  while (await page.getByRole("button", { name: /Load more/ }).count()) {
    const before = await rows.count();
    await page.getByRole("button", { name: /Load more/ }).click();
    await expect.poll(() => rows.count()).toBeGreaterThan(before);
  }
  const seqs = (await rows.locator("td:first-child").allTextContents()).map(Number);
  expect(seqs).toEqual(seqs.map((_, i) => i + 1));
  metrics.timelineRows = seqs.length;
});

test("60-second soak: random navigation and concurrent API load, memory stays bounded, zero errors", async ({ page }) => {
  const errors: string[] = [];
  const serverErrors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => r.url().includes("/api/v1/") && r.status() >= 500 && serverErrors.push(`${r.status()} ${r.url()}`));
  await page.addInitScript((t) => sessionStorage.setItem("ca.dev.token", t), process.env.CA_E2E_TOKEN!);
  await page.goto("/home");
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const heap = async () => {
    await cdp.send("HeapProfiler.collectGarbage");
    const { metrics: m } = (await cdp.send("Performance.getMetrics")) as any;
    return Math.round(m.find((x: any) => x.name === "JSHeapUsedSize").value / 1048576);
  };
  const paths = ["/home", "/changes", "/tools", "/settings", ...seededIds.slice(0, 12).flatMap((id) => [`/changes/${id}`, `/changes/${id}/contract`, `/changes/${id}/evidence`, `/changes/${id}/timeline`])];
  await page.waitForLoadState("networkidle");
  const baseline = await heap();
  const samples = [baseline];
  const end = Date.now() + 60_000;
  let nav = 0;
  let nextSample = Date.now() + 15_000;
  // background API pressure while the UI is being used
  let stop = false;
  const pressure = (async () => {
    while (!stop) await Promise.all(Array.from({ length: 6 }, (_, i) => get(`/api/v1/changes/${seededIds[i]}`)));
  })();
  while (Date.now() < end) {
    const p = paths[Math.floor(Math.random() * paths.length)]!;
    await page.evaluate((to) => { history.pushState({}, "", to); dispatchEvent(new PopStateEvent("popstate")); }, p);
    await page.waitForTimeout(150);
    nav += 1;
    if (Date.now() > nextSample) { samples.push(await heap()); nextSample = Date.now() + 15_000; }
  }
  stop = true;
  await pressure;
  await page.goto("/home");
  await page.waitForLoadState("networkidle");
  samples.push(await heap());
  metrics.soak = { navigations: nav, heapMB: samples };
  expect(serverErrors).toEqual([]);
  expect(errors).toEqual([]);
  expect(samples.at(-1)!, `heap samples ${samples}`).toBeLessThan(baseline * 2 + 25);
  console.log("HEAVY METRICS " + JSON.stringify(metrics));
});
