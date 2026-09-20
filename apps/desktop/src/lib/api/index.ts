import { createBrowserTransport } from "./browser-transport";
import type { Transport } from "./client";
import { createElectronTransport } from "./electron-transport";

export const transport: Transport = window.changeAssuranceDesktop
  ? createElectronTransport()
  : createBrowserTransport();

type Query = Record<string, string | number | boolean | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

/** Thin typed helpers over the transport. Services use these; components never call the transport directly. */
export const http = {
  get: <T>(path: string, opts: { query?: Query; signal?: AbortSignal } = {}) =>
    transport.request<T>({ method: "GET", path: withQuery(path, opts.query) }, opts.signal),
  post: <T>(path: string, body?: unknown, opts: { idempotencyKey?: string; signal?: AbortSignal } = {}) =>
    transport.request<T>(
      { method: "POST", path, body, idempotencyKey: opts.idempotencyKey },
      opts.signal,
    ),
  put: <T>(path: string, body: unknown, opts: { signal?: AbortSignal } = {}) =>
    transport.request<T>({ method: "PUT", path, body }, opts.signal),
};

/** One idempotency key per user intent; reuse it for retries of the same submission. */
export const newIdempotencyKey = (): string => crypto.randomUUID();
