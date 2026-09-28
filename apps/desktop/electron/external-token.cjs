"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const STORE_DIRECTORY_NAME = "Sentinel";
const TOKEN_FILENAME = "api_token";

/**
 * The backend's default evidence-store directory, mirroring
 * `backend.app.core.evidence_store.default_store_directory`: %LOCALAPPDATA%\Sentinel,
 * falling back to <home>\AppData\Local\Sentinel when LOCALAPPDATA is unset or empty.
 */
function defaultStoreDirectory(env = process.env, home = os.homedir()) {
  const local = env.LOCALAPPDATA && env.LOCALAPPDATA.trim() ? env.LOCALAPPDATA : path.join(home, "AppData", "Local");
  return path.join(local, STORE_DIRECTORY_NAME);
}

/**
 * Where a separately started backend keeps its API token: next to its database. An explicit
 * CHANGE_ASSURANCE_DB_PATH wins; otherwise the default store. The legacy in-repository
 * `.change-assurance/` store is never read: the backend refuses to run against it until
 * `migrate-store`, which rotates the token, so its old token file is stale.
 */
function externalTokenPath(env = process.env, home = os.homedir()) {
  const dbPath = env.CHANGE_ASSURANCE_DB_PATH && env.CHANGE_ASSURANCE_DB_PATH.trim();
  if (dbPath) return path.join(path.dirname(path.resolve(dbPath)), TOKEN_FILENAME);
  return path.join(defaultStoreDirectory(env, home), TOKEN_FILENAME);
}

/** Development-only: the token of a backend that was started separately. Never logged. */
function readExternalToken({ env = process.env, home = os.homedir(), readFile = fs.readFileSync } = {}) {
  if (env.CHANGE_ASSURANCE_API_TOKEN) return env.CHANGE_ASSURANCE_API_TOKEN;
  try {
    return String(readFile(externalTokenPath(env, home), "utf8")).trim();
  } catch {
    return "";
  }
}

module.exports = { defaultStoreDirectory, externalTokenPath, readExternalToken };
