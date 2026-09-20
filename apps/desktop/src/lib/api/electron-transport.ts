import {
  ApiError,
  assertApiPath,
  kindFromBridgeCode,
  unwrapEnvelope,
  withAbort,
  type ApiRequest,
  type Transport,
} from "./client";

/** Requests go through the main-process proxy; the bearer token never reaches this code. */
export function createElectronTransport(): Transport {
  const bridge = window.changeAssuranceDesktop;
  if (!bridge) throw new Error("Electron bridge is unavailable.");
  return {
    kind: "electron",
    async request<T>(input: ApiRequest, signal?: AbortSignal): Promise<T> {
      assertApiPath(input.path);
      const result = await withAbort(bridge.api.request(input), signal);
      if (!result.ok) {
        throw new ApiError(kindFromBridgeCode(result.error.code), result.error.code, result.error.message);
      }
      return unwrapEnvelope<T>(result.status, result.body);
    },
  };
}
