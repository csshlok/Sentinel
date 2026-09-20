"use strict";

const fs = require("node:fs");
const path = require("node:path");

const SCHEME = "app";
const HOST = "app";

/** No network from the page: the renderer talks to the backend only through the IPC proxy. */
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join("; ");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".map": "application/json; charset=utf-8",
};

/**
 * Map a request URL to a file strictly inside `rootDir`.
 * Returns `{ status: 200, filePath }`, or `{ status: 400|403|404 }`. Never touches paths outside the root.
 * Extension-less paths are SPA routes and fall back to index.html; missing assets are a 404, not a fallback.
 */
function resolveAsset(rootDir, requestUrl, fsImpl = fs) {
  let url;
  try {
    url = new URL(requestUrl);
  } catch {
    return { status: 400 };
  }
  if (url.protocol !== `${SCHEME}:` || url.hostname !== HOST || url.username || url.password) {
    return { status: 400 };
  }

  let decoded;
  try {
    decoded = decodeURIComponent(url.pathname);
  } catch {
    return { status: 400 };
  }
  if (decoded.includes("\0") || decoded.includes("\\")) return { status: 400 };

  const segments = decoded.split("/").filter(Boolean);
  if (segments.some((segment) => segment === ".." || segment === "." || segment.startsWith("."))) {
    return { status: 403 };
  }

  const root = path.resolve(rootDir);
  const withinRoot = (candidate) => {
    const relative = path.relative(root, candidate);
    return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
  };
  const isFile = (candidate) => {
    try {
      // realpath defeats symlinks that point outside the root.
      const real = fsImpl.realpathSync(candidate);
      return withinRoot(real) && fsImpl.statSync(real).isFile() ? real : null;
    } catch {
      return null;
    }
  };

  const index = path.join(root, "index.html");
  if (segments.length === 0) {
    const real = isFile(index);
    return real ? { status: 200, filePath: real } : { status: 404 };
  }

  const candidate = path.join(root, ...segments);
  if (!withinRoot(candidate)) return { status: 403 };
  const real = isFile(candidate);
  if (real) return { status: 200, filePath: real };

  if (path.extname(segments[segments.length - 1]) === "") {
    const fallback = isFile(index);
    return fallback ? { status: 200, filePath: fallback } : { status: 404 };
  }
  return { status: 404 };
}

/** Build the `protocol.handle` callback. Responses are static, read-only, and carry the CSP. */
function createProtocolHandler({ rootDir, fsImpl = fs }) {
  return async function handle(request) {
    const resolved = resolveAsset(rootDir, request.url, fsImpl);
    const headers = {
      "Content-Security-Policy": CSP,
      "X-Content-Type-Options": "nosniff",
    };
    if (resolved.status !== 200) {
      return new Response(resolved.status === 404 ? "Not found" : "Forbidden", {
        status: resolved.status,
        headers: { ...headers, "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    const body = await fsImpl.promises.readFile(resolved.filePath);
    return new Response(body, {
      status: 200,
      headers: {
        ...headers,
        "Content-Type": MIME[path.extname(resolved.filePath).toLowerCase()] ?? "application/octet-stream",
      },
    });
  };
}

module.exports = { SCHEME, HOST, CSP, resolveAsset, createProtocolHandler };
