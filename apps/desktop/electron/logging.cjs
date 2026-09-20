"use strict";

const fs = require("node:fs");
const path = require("node:path");

const MAX_BYTES = 1_000_000;

/**
 * Small append-only logger with one rotation. Logging must never crash the app, so every failure is swallowed.
 * `redact` receives each line and returns the text that is actually written.
 */
function createLogger({ dir, name = "desktop.log", redact = (text) => text, now = () => new Date() }) {
  const file = path.join(dir, name);
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch {
    /* logging is best effort */
  }

  function rotateIfNeeded() {
    try {
      if (fs.statSync(file).size > MAX_BYTES) fs.renameSync(file, `${file}.1`);
    } catch {
      /* no file yet */
    }
  }

  function log(message) {
    try {
      rotateIfNeeded();
      const text = String(message instanceof Error ? (message.stack ?? message.message) : message);
      fs.appendFileSync(file, `${now().toISOString()} ${redact(text).replace(/\r?\n/g, " | ")}\n`);
    } catch {
      /* logging is best effort */
    }
  }

  return { log, file };
}

module.exports = { createLogger };
