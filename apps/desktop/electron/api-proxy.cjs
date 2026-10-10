"use strict";

const { BridgeError } = require("./ipc-errors.cjs");

const ALLOWED_METHODS = new Set(["GET", "POST", "PUT", "DELETE"]);
const API_PREFIX = "/api/v1/";
const MAX_BODY_BYTES = 1_048_576;
const MAX_RESPONSE_BYTES = 8_388_608;
const DEFAULT_TIMEOUT_MS = 15_000;
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

/** Accept only an http loopback base URL with no credentials, path, or query. */
function parseLoopbackBase(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new BridgeError("invalid_backend_url", "Backend URL is not valid.");
  }
  if (
    url.protocol !== "http:" ||
    !LOOPBACK_HOSTS.has(url.hostname) ||
    url.username ||
    url.password ||
    (url.pathname !== "/" && url.pathname !== "")
  ) {
    throw new BridgeError("invalid_backend_url", "Backend must be a plain loopback HTTP address.");
  }
  return url.origin;
}

/**
 * Build the only function through which the renderer reaches the backend.
 * The bearer token lives in this closure and is never returned or logged.
 */
function createApiProxy({ getBaseUrl, getToken, fetchImpl = fetch }) {
  return async function request(input) {
    const baseUrl = getBaseUrl();
    if (!baseUrl) throw new BridgeError("backend_unreachable", "The backend is not running.");
    const origin = parseLoopbackBase(baseUrl);
    const { method, path, body, idempotencyKey, timeoutMs } = input ?? {};
    if (!ALLOWED_METHODS.has(method)) {
      throw new BridgeError("forbidden_method", "HTTP method is not allowed.");
    }
    if (typeof path !== "string" || !path.startsWith(API_PREFIX) || path.includes("..") || path.includes("//")) {
      throw new BridgeError("forbidden_path", "Only /api/v1 paths are allowed.");
    }

    const headers = { Accept: "application/json" };
    let payload;
    if (body !== undefined) {
      payload = JSON.stringify(body);
      if (Buffer.byteLength(payload) > MAX_BODY_BYTES) {
        throw new BridgeError("request_too_large", "Request body is too large.");
      }
      headers["Content-Type"] = "application/json";
    }
    if (typeof idempotencyKey === "string" && /^[\w.:-]{1,128}$/.test(idempotencyKey)) {
      headers["Idempotency-Key"] = idempotencyKey;
    }
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    const signal = AbortSignal.timeout(Math.min(Number(timeoutMs) || DEFAULT_TIMEOUT_MS, 60_000));
    let response;
    try {
      response = await fetchImpl(origin + path, { method, headers, body: payload, signal, redirect: "error" });
    } catch (cause) {
      const timedOut = cause?.name === "TimeoutError" || cause?.name === "AbortError";
      throw new BridgeError(
        timedOut ? "backend_timeout" : "backend_unreachable",
        timedOut ? "The backend did not respond in time." : "The backend is not reachable.",
      );
    }

    const text = await response.text();
    if (text.length > MAX_RESPONSE_BYTES) {
      throw new BridgeError("response_too_large", "Backend response is too large.");
    }
    let parsed = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new BridgeError("invalid_response", "Backend returned a non-JSON response.");
      }
    }
    return { ok: true, status: response.status, body: parsed };
  };
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BUNDLE_MEDIA_TYPE = "application/vnd.sentinel.passport+zip";
const MAX_BUNDLE_BYTES = 32 * 1024 * 1024;

/**
 * Fetch one Change's Passport v2 bundle (a zip) in the main process. Only this fixed route is reachable, the token stays in
 * this closure, and the bytes never pass through the renderer. A JSON error envelope is returned as `{ ok: false, error }`.
 */
function createBundleFetch({ getBaseUrl, getToken, fetchImpl = fetch }) {
  return async function fetchBundle(changeId) {
    if (typeof changeId !== "string" || !UUID_PATTERN.test(changeId)) {
      throw new BridgeError("invalid_request", "That is not a Change id.");
    }
    const baseUrl = getBaseUrl();
    if (!baseUrl) throw new BridgeError("backend_unreachable", "The backend is not running.");
    const origin = parseLoopbackBase(baseUrl);
    const headers = { Accept: `${BUNDLE_MEDIA_TYPE}, application/json` };
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    let response;
    try {
      response = await fetchImpl(`${origin}/api/v1/changes/${changeId}/passport/v2/bundle`, {
        method: "POST", headers, signal: AbortSignal.timeout(60_000), redirect: "error",
      });
    } catch (cause) {
      const timedOut = cause?.name === "TimeoutError" || cause?.name === "AbortError";
      throw new BridgeError(
        timedOut ? "backend_timeout" : "backend_unreachable",
        timedOut ? "The backend did not respond in time." : "The backend is not reachable.",
      );
    }
    const type = (response.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
    // Refuse a declared oversize body before buffering anything; the length is re-checked after reading.
    const declared = Number(response.headers.get("content-length"));
    if (Number.isFinite(declared) && declared > MAX_BUNDLE_BYTES) {
      throw new BridgeError("response_too_large", "The bundle is too large.");
    }
    const bytes = Buffer.from(await response.arrayBuffer());
    if (bytes.length > MAX_BUNDLE_BYTES) throw new BridgeError("response_too_large", "The bundle is too large.");
    if (response.ok && type === BUNDLE_MEDIA_TYPE) return { ok: true, bytes };
    let message = "The backend did not return a Passport bundle.";
    try {
      const envelope = JSON.parse(bytes.toString("utf8"));
      if (typeof envelope?.error?.message === "string") message = envelope.error.message;
    } catch {
      // keep the generic message: a non-JSON body is never shown to the user
    }
    return { ok: false, error: { code: "bundle_unavailable", message: message.slice(0, 500) } };
  };
}

module.exports = { createApiProxy, createBundleFetch, parseLoopbackBase, BUNDLE_MEDIA_TYPE, UUID_PATTERN };
