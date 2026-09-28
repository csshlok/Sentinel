"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const { test } = require("node:test");
const { defaultStoreDirectory, externalTokenPath, readExternalToken } = require("../external-token.cjs");

const HOME = path.join("C:", "Users", "dev");

test("the default store mirrors the backend: LOCALAPPDATA\\Sentinel", () => {
  const local = path.join("C:", "Users", "dev", "AppData", "Local");
  assert.equal(defaultStoreDirectory({ LOCALAPPDATA: local }, HOME), path.join(local, "Sentinel"));
});

test("an unset or empty LOCALAPPDATA falls back to <home>\\AppData\\Local\\Sentinel", () => {
  const expected = path.join(HOME, "AppData", "Local", "Sentinel");
  assert.equal(defaultStoreDirectory({}, HOME), expected);
  assert.equal(defaultStoreDirectory({ LOCALAPPDATA: "  " }, HOME), expected);
});

test("CHANGE_ASSURANCE_DB_PATH wins and the token sits next to that database", () => {
  const db = path.resolve("D:/stores/custom/change_assurance.sqlite3");
  assert.equal(externalTokenPath({ CHANGE_ASSURANCE_DB_PATH: db, LOCALAPPDATA: "C:/x" }, HOME), path.join(path.dirname(db), "api_token"));
});

test("the legacy in-repository .change-assurance token is never read", () => {
  const read = [];
  readExternalToken({ env: { LOCALAPPDATA: "C:/L" }, home: HOME, readFile: (p) => { read.push(p); throw new Error("missing"); } });
  assert.equal(read.length, 1);
  assert.ok(!read[0].includes(".change-assurance"), read[0]);
  assert.equal(read[0], path.join("C:/L", "Sentinel", "api_token"));
});

test("an explicit token wins without touching the file system", () => {
  let touched = false;
  const token = readExternalToken({ env: { CHANGE_ASSURANCE_API_TOKEN: "tok" }, readFile: () => { touched = true; return ""; } });
  assert.equal(token, "tok");
  assert.equal(touched, false);
});

test("the token file is trimmed; a missing file yields an empty token", () => {
  assert.equal(readExternalToken({ env: { LOCALAPPDATA: "C:/L" }, readFile: () => "abc\r\n" }), "abc");
  assert.equal(readExternalToken({ env: { LOCALAPPDATA: "C:/L" }, readFile: () => { throw new Error("ENOENT"); } }), "");
});
