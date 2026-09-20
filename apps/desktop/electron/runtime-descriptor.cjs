"use strict";

const fs = require("node:fs");
const path = require("node:path");

/**
 * A tiny record of the managed backend this app started, so a later launch can find and reap it if the app
 * crashed or was force-killed. It holds only non-secret identity data (never the token).
 */
function createDescriptorStore(file, fsImpl = fs) {
  function read() {
    try {
      const value = JSON.parse(fsImpl.readFileSync(file, "utf8"));
      const valid =
        Number.isInteger(value?.pid) && value.pid > 0 && Number.isInteger(value?.port) && value.port > 0 && typeof value?.marker === "string";
      return valid ? { pid: value.pid, port: value.port, marker: value.marker } : null;
    } catch {
      return null; // missing or malformed: treat as no descriptor
    }
  }

  function write({ pid, port, marker }) {
    try {
      fsImpl.mkdirSync(path.dirname(file), { recursive: true });
      const temp = `${file}.tmp`;
      fsImpl.writeFileSync(temp, JSON.stringify({ pid, port, marker }));
      fsImpl.renameSync(temp, file);
    } catch {
      /* best effort: the app still works without a descriptor */
    }
  }

  function clear() {
    try {
      fsImpl.rmSync(file, { force: true });
    } catch {
      /* best effort */
    }
  }

  return { read, write, clear };
}

module.exports = { createDescriptorStore };
