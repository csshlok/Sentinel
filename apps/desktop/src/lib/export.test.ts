import assert from "node:assert/strict";
import { test } from "node:test";
import { exportFileName } from "./export.ts";

test("file names are lowercase, hyphenated and bounded", () => {
  assert.equal(exportFileName("Passport", "1A2B3C4D-5E6F-7890-ABCD-EF0123456789"), "passport-1a2b3c4d.json");
  assert.equal(exportFileName("trace", "x"), "trace-x.json");
});

test("hostile or empty input still yields a safe name", () => {
  assert.equal(exportFileName("../../evil", "..\\..\\x"), "evil-x.json");
  assert.equal(exportFileName("", ""), "export-data.json");
  assert.match(exportFileName("a b", "c/d"), /^[a-z0-9-]+\.json$/);
});
