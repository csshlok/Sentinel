import { guardText } from "../lifecycle.ts";

// Transport-neutral request contract. Nothing in this file touches Electron, the DOM, or the token.

export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

export interface ApiRequest {
  method: HttpMethod;
  path: string;
  body?: unknown;
  idempotencyKey?: string;
  timeoutMs?: number;
}

export interface Transport {
  readonly kind: "electron" | "browser";
  request<T>(input: ApiRequest, signal?: AbortSignal): Promise<T>;
}

/**
 * Why a request failed, in terms the UI can act on.
 * `auth` is a rejected or missing credential, distinct from `offline` (nothing answered)
 * and `unsupported` (the backend answered but reports the capability as unavailable).
 */
export type ApiErrorKind =
  | "auth"
  | "offline"
  | "timeout"
  | "not_found"
  | "conflict"
  | "validation"
  | "server"
  | "bridge"
  | "aborted"
  | "unknown";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly code: string;
  readonly status: number | undefined;
  /** Backend `error.details`, e.g. `missing_requirements` or validation `errors`. */
  readonly details: Record<string, unknown> | undefined;

  constructor(kind: ApiErrorKind, code: string, message: string, status?: number, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

/** Human-readable lines for the parts of `error.details` the backend documents (guard requirements, field errors). */
export function errorDetailLines(error: unknown): string[] {
  const d = error instanceof ApiError ? error.details : undefined;
  if (!d) return [];
  const out: string[] = [];
  const missing = d.missing_requirements;
  if (Array.isArray(missing) && missing.length) out.push(`Missing: ${missing.map((m) => `${guardText(String(m))} (${m})`).join("; ")}`);
  const errs = d.errors;
  if (Array.isArray(errs)) for (const e of errs.slice(0, 5)) out.push(`${Array.isArray((e as any).location) ? (e as any).location.join(".") + ": " : ""}${(e as any).message ?? "invalid"}`);
  return out;
}

const API_PREFIX = "/api/v1/";

/** Reject anything that is not a plain `/api/v1/...` path before it reaches a transport. */
export function assertApiPath(path: string): void {
  if (
    typeof path !== "string" ||
    !path.startsWith(API_PREFIX) ||
    path.includes("..") ||
    path.includes("//") ||
    path.includes("\\") ||
    /[\s#]/.test(path)
  ) {
    throw new ApiError("bridge", "invalid_path", "Only plain /api/v1 paths are allowed.");
  }
}

const BRIDGE_CODES: Record<string, ApiErrorKind> = {
  backend_unreachable: "offline",
  backend_timeout: "timeout",
};

export function kindFromBridgeCode(code: string): ApiErrorKind {
  return BRIDGE_CODES[code] ?? "bridge";
}

export function kindFromStatus(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

/** Stable backend codes where the raw message isn't the most useful thing to show. */
export const KNOWN_CODE_MESSAGES: Record<string, string> = {
  GIT_EXECUTABLE_NOT_FOUND: "Git isn't installed or isn't on this computer's PATH. Install Git, then try again.",
};

/** Return the body for 2xx; otherwise throw a normalized error from the `{error:{code,message}}` envelope. */
export function unwrapEnvelope<T>(status: number, body: unknown): T {
  if (status >= 200 && status < 300) return body as T;
  const envelope = (body as { error?: { code?: unknown; message?: unknown; details?: unknown } } | null)?.error;
  const code = typeof envelope?.code === "string" ? envelope.code : "http_error";
  const message =
    typeof envelope?.message === "string" ? envelope.message : `The request failed (${status}).`;
  const details = envelope?.details && typeof envelope.details === "object" ? (envelope.details as Record<string, unknown>) : undefined;
  throw new ApiError(kindFromStatus(status), code, KNOWN_CODE_MESSAGES[code] ?? message, status, details);
}

/** Reject with an `aborted` error when the caller's signal fires before the transport settles. */
export function withAbort<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new ApiError("aborted", "aborted", "The request was cancelled."));
    if (signal.aborted) return abort();
    signal.addEventListener("abort", abort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}
