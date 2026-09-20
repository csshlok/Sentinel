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

module.exports = { createApiProxy, parseLoopbackBase };
