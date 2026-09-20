"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createLogger } = require("../logging.cjs");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "ca-log-"));

test("writes timestamped single-line entries and applies redaction", () => {
  const dir = tmp();
  const { log, file } = createLogger({
    dir,
    redact: (text) => text.replace("SECRET", "[redacted]"),
    now: () => new Date("2026-01-02T03:04:05Z"),
  });
  log("hello SECRET\nsecond line");
  assert.equal(fs.readFileSync(file, "utf8"), "2026-01-02T03:04:05.000Z hello [redacted] | second line\n");
});

test("logs errors with a stack and rotates once when the file grows", () => {
  const dir = tmp();
  const { log, file } = createLogger({ dir });
  log(new Error("boom"));
  assert.match(fs.readFileSync(file, "utf8"), /boom/);
  fs.writeFileSync(file, "x".repeat(1_100_000));
  log("after rotation");
  assert.ok(fs.existsSync(`${file}.1`));
  assert.match(fs.readFileSync(file, "utf8"), /after rotation/);
});

test("never throws when the directory cannot be written", () => {
  const blocker = path.join(tmp(), "file-not-dir");
  fs.writeFileSync(blocker, "");
  const { log } = createLogger({ dir: path.join(blocker, "nested") });
  assert.doesNotThrow(() => log("still fine"));
});
