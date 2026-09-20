import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Reads the real tokens from app.css so a palette edit that breaks readability fails here rather than in someone's eyes.
const css = readFileSync(new URL("./app.css", import.meta.url), "utf8");

function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `missing ${selector}`);
  const body = css.slice(start, css.indexOf("\n}", start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1]!, m[2]!]));
}

const lin = (c: number) => (c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
const lum = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
};
const ratio = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

// [foreground token, background token, minimum ratio]. 4.5 for normal text (WCAG AA), 3 for large or non-text.
const PAIRS: [string, string, number][] = [
  ["text-primary", "bg-canvas", 4.5],
  ["text-primary", "bg-card", 4.5],
  ["text-body", "bg-card", 4.5],
  ["text-body", "bg-canvas", 4.5],
  ["text-muted", "bg-card", 4.5],
  ["text-muted", "bg-canvas", 4.5],
  ["text-muted", "bg-secondary", 4.5],
  ["text-subtle", "bg-canvas", 4.5],
  ["text-subtle", "bg-card", 4.5],
  ["primary-text", "primary", 4.5],
  ["text-body", "status-muted-bg", 4.5],
  ["text-body", "status-info-bg", 4.5],
  ["status-warn-ink", "status-warn-bg", 4.5],
  ["text-body", "status-error-bg", 4.5],
  // These are also used as text (`text-ok`, `text-warn`, `text-danger`), so they need the text ratio, not the non-text one.
  ["status-ok", "bg-card", 4.5],
  ["status-error", "bg-card", 4.5],
  ["status-warn", "bg-card", 4.5],
  ["primary", "bg-card", 3],
  ["border-strong", "bg-card", 1.3],
];

for (const [name, selector] of [["light", ":root"], ["dark", ':root[data-theme="dark"]']] as const) {
  test(`${name} theme: text and status colours meet contrast targets`, () => {
    const base = tokens(":root");
    const t = { ...base, ...(name === "dark" ? tokens(selector) : {}) };
    const failures = PAIRS.filter(([fg, bg, min]) => ratio(t[fg]!, t[bg]!) < min).map(([fg, bg, min]) => `${fg} on ${bg}: ${ratio(t[fg]!, t[bg]!).toFixed(2)} < ${min}`);
    assert.deepEqual(failures, []);
  });
}
