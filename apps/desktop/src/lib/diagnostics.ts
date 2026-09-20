import type { RuntimeStatus } from "../types/desktop";

interface Cap {
  id: string;
  state: string;
}

/**
 * A short, paste-able summary for bug reports. It is built from an allowlist of fields: versions, modes, states. It never includes a
 * token, a repository path, the backend URL, or anything from a Change, so it is safe to share.
 */
export function buildDiagnostics(input: {
  interfaceKind: "browser" | "desktop";
  api: string | null;
  reachable: boolean;
  runtime: RuntimeStatus | null;
  capabilities: Cap[];
}): string {
  const r = input.runtime;
  const lines = [
    `Interface: ${input.interfaceKind}`,
    `Service reachable: ${input.reachable ? "yes" : "no"}`,
    `API version: ${input.api ?? "unknown"}`,
    ...(r
      ? [
          `Build: ${r.packaged ? "packaged" : "development"}`,
          `Backend mode: ${r.backend.mode}`,
          `Backend state: ${r.backend.state}`,
          `Git: ${r.git.available ? (r.git.version ?? "found") : "not found"}`,
        ]
      : []),
    ...(input.capabilities.length ? ["Capabilities:", ...input.capabilities.map((c) => `  ${c.id}: ${c.state}`)] : []),
  ];
  return lines.join("\n");
}
