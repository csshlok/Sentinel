import assert from "node:assert/strict";
import { test } from "node:test";
import { isThemePreference, resolveTheme } from "./theme.ts";

test("an explicit choice ignores the system setting", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
});

test("system follows the operating system", () => {
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
});

test("only known preferences are accepted from storage", () => {
  assert.equal(isThemePreference("dark"), true);
  for (const bad of ["", "auto", null, undefined, 1, {}]) assert.equal(isThemePreference(bad), false);
});
