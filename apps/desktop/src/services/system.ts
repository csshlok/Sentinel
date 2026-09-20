import { queryOptions } from "@tanstack/react-query";
import { http } from "../lib/api";
import type { BackendIdentity, CapabilitiesResponse, Health, SigningPublicKeyResponse } from "../lib/api/types";

export const systemKeys = {
  health: ["system", "health"] as const,
  capabilities: ["system", "capabilities"] as const,
  runtime: ["system", "runtime"] as const,
  signingKey: ["system", "signing-key"] as const,
};

/** Polled while the window is visible; the shell derives the connection indicator from this. */
export const healthQuery = () =>
  queryOptions({
    queryKey: systemKeys.health,
    queryFn: ({ signal }) => http.get<Health>("/api/v1/health", { signal }),
    // Poll faster while the backend is down so a managed backend that is still starting is picked up quickly.
    refetchInterval: (query) => (query.state.status === "error" ? 2_000 : 8_000),
    refetchIntervalInBackground: false,
    retry: false,
  });

export const capabilitiesQuery = () =>
  queryOptions({
    queryKey: systemKeys.capabilities,
    queryFn: ({ signal }) => http.get<CapabilitiesResponse>("/api/v1/capabilities", { signal }),
    retry: false,
  });

/** Desktop-only runtime state (managed backend, packaging). Absent in a plain browser. */
export const runtimeQuery = () =>
  queryOptions({
    queryKey: systemKeys.runtime,
    queryFn: async () => {
      const bridge = window.changeAssuranceDesktop;
      if (!bridge) return null;
      const result = await bridge.runtime.getStatus();
      return result.ok ? result : null;
    },
    // Cheap local IPC call: keep polling even when the window is hidden so a starting backend is never shown stale.
    refetchInterval: 4_000,
    refetchIntervalInBackground: true,
  });

/** Which backend process answered: name, API version, per-process instance id and start time. No secrets or paths. */
export const identityQuery = () =>
  queryOptions({
    queryKey: ["system", "identity"] as const,
    queryFn: ({ signal }) => http.get<BackendIdentity>("/api/v1/system/backend-identity", { signal }),
    retry: false,
  });

/** This operator's Ed25519 public key, so a signed Passport export can be shown alongside who could have signed it. */
export const signingKeyQuery = () =>
  queryOptions({
    queryKey: systemKeys.signingKey,
    queryFn: ({ signal }) => http.get<SigningPublicKeyResponse>("/api/v1/identity/signing-key", { signal }),
    retry: false,
  });
