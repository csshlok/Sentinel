"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { CSP, createProtocolHandler, resolveAsset } = require("../app-protocol.cjs");

function fixture() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "ca-protocol-"));
  const root = path.join(base, "dist");
  fs.mkdirSync(path.join(root, "assets"), { recursive: true });
  fs.writeFileSync(path.join(root, "index.html"), "<!doctype html><title>x</title>");
  fs.writeFileSync(path.join(root, "assets", "app.js"), "console.log(1)");
  fs.writeFileSync(path.join(root, ".hidden"), "nope");
  fs.writeFileSync(path.join(base, "secret.txt"), "TOP SECRET");
  return { base, root };
}

const url = (p) => `app://app${p}`;

test("serves the index for the root and SPA routes", () => {
  const { root } = fixture();
  for (const route of ["/", "/changes", "/changes/abc-123/timeline", "/settings"]) {
    const result = resolveAsset(root, url(route));
    assert.equal(result.status, 200, route);
    assert.equal(path.basename(result.filePath), "index.html");
  }
});

test("serves real assets and 404s missing ones instead of falling back", () => {
  const { root } = fixture();
  assert.equal(resolveAsset(root, url("/assets/app.js")).status, 200);
  assert.equal(resolveAsset(root, url("/assets/missing.js")).status, 404);
  assert.equal(resolveAsset(root, url("/favicon.ico")).status, 404);
});

test("rejects path traversal in every encoding", () => {
  const { root } = fixture();
  const attempts = [
    "/../secret.txt",
    "/assets/../../secret.txt",
    "/%2e%2e/secret.txt",
    "/%2E%2E%2Fsecret.txt",
    "/assets/%2e%2e/%2e%2e/secret.txt",
    "/..%2fsecret.txt",
    "/assets\\..\\..\\secret.txt",
    "/%5c..%5csecret.txt",
    "/%00",
    "/assets/app.js%00.png",
  ];
  for (const attempt of attempts) {
    const result = resolveAsset(root, url(attempt));
    assert.notEqual(result.status, 200, `${attempt} must not be served`);
    assert.equal(result.filePath, undefined, attempt);
  }
});

test("rejects dotfiles, foreign hosts, other schemes and credentials", () => {
  const { root } = fixture();
  assert.equal(resolveAsset(root, url("/.hidden")).status, 403);
  assert.equal(resolveAsset(root, "app://evil/index.html").status, 400);
  assert.equal(resolveAsset(root, "file:///c:/windows/win.ini").status, 400);
  assert.equal(resolveAsset(root, "https://app/index.html").status, 400);
  assert.equal(resolveAsset(root, "app://user:pw@app/index.html").status, 400);
  assert.equal(resolveAsset(root, "not a url").status, 400);
});

test("does not follow a symlink that escapes the root", (t) => {
  const { base, root } = fixture();
  try {
    fs.symlinkSync(path.join(base, "secret.txt"), path.join(root, "assets", "link.txt"));
  } catch {
    t.skip("symlinks are not permitted in this environment");
    return;
  }
  assert.notEqual(resolveAsset(root, url("/assets/link.txt")).status, 200);
});

test("handler returns the CSP, nosniff and correct types; errors carry no file content", async () => {
  const { root } = fixture();
  const handle = createProtocolHandler({ rootDir: root });

  const ok = await handle({ url: url("/assets/app.js") });
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("content-type"), "text/javascript; charset=utf-8");
  assert.equal(ok.headers.get("content-security-policy"), CSP);
  assert.equal(ok.headers.get("x-content-type-options"), "nosniff");
  assert.equal(await ok.text(), "console.log(1)");

  const blocked = await handle({ url: url("/../secret.txt") });
  assert.notEqual(blocked.status, 200);
  assert.ok(!(await blocked.text()).includes("TOP SECRET"));
});

test("CSP forbids network, plugins, framing and inline scripts", () => {
  assert.match(CSP, /connect-src 'none'/);
  assert.match(CSP, /object-src 'none'/);
  assert.match(CSP, /frame-ancestors 'none'/);
  assert.match(CSP, /script-src 'self'(;|$)/);
  assert.ok(!/script-src[^;]*unsafe/.test(CSP));
});
