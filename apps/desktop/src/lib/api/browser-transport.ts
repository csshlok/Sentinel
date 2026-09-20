import {
  ApiError,
  assertApiPath,
  unwrapEnvelope,
  type ApiRequest,
  type Transport,
} from "./client";

const TOKEN_KEY = "ca.dev.token";
// Same-origin: the Vite dev server proxies /api to the backend, so CORS is not involved.
const BASE_URL = "";

/** Development-only token holder for running the renderer in a plain browser. Electron never uses this. */
export const devToken = {
  get: () => sessionStorage.getItem(TOKEN_KEY) ?? "",
  set: (value: string) => sessionStorage.setItem(TOKEN_KEY, value.trim()),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export function createBrowserTransport(): Transport {
  return {
    kind: "browser",
    async request<T>(input: ApiRequest, signal?: AbortSignal): Promise<T> {
      assertApiPath(input.path);
      const headers: Record<string, string> = { Accept: "application/json" };
      if (input.body !== undefined) headers["Content-Type"] = "application/json";
      if (input.idempotencyKey) headers["Idempotency-Key"] = input.idempotencyKey;
      const token = devToken.get();
      if (token) headers.Authorization = `Bearer ${token}`;

      const timeout = AbortSignal.timeout(input.timeoutMs ?? 15_000);
      let response: Response;
      try {
        response = await fetch(BASE_URL + input.path, {
          method: input.method,
          headers,
          body: input.body === undefined ? undefined : JSON.stringify(input.body),
          signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        });
      } catch (cause) {
        if (signal?.aborted) throw new ApiError("aborted", "aborted", "The request was cancelled.");
        if ((cause as Error)?.name === "TimeoutError") {
          throw new ApiError("timeout", "backend_timeout", "The backend did not respond in time.");
        }
        throw new ApiError("offline", "backend_unreachable", "The backend is not reachable.");
      }
      const text = await response.text();
      let body: unknown = null;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          throw new ApiError("server", "invalid_response", "The backend returned a non-JSON response.");
        }
      }
      return unwrapEnvelope<T>(response.status, body);
    },
  };
}
