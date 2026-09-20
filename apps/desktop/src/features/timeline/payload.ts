const SENSITIVE = /token|secret|password|credential|authorization|api[_-]?key/i;
const MAX_DEPTH = 6;
const MAX_STRING = 500;

/**
 * A display copy of an event payload: credential-looking keys are hidden, long strings are cut, and nesting is bounded. The stored
 * payload and any export are never altered; this only limits what the inspector prints.
 */
export function displayPayload(value: unknown, depth = 0): unknown {
  if (value === null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") return value.length > MAX_STRING ? `${value.slice(0, MAX_STRING)}… (${value.length} characters)` : value;
  if (depth >= MAX_DEPTH) return "[nested value omitted]";
  if (Array.isArray(value)) return value.slice(0, 50).map((v) => displayPayload(v, depth + 1));
  if (typeof value === "object" && value !== undefined) {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, SENSITIVE.test(k) ? "[hidden]" : displayPayload(v, depth + 1)]));
  }
  return String(value);
}

// Values of the backend's RestorationClass. Wording stays literal: "exact" says how a recorded effect could be restored, not that recovery happened.
const RESTORATION: Record<string, string> = {
  exact: "Can be restored exactly",
  conditional: "Can be restored under conditions",
  compensating: "Can be compensated, not restored",
  stageable: "Can be staged for review",
  none: "Can't be undone",
  unknown: "Restorability unknown",
};
export const restorationText = (cls: string) => RESTORATION[cls] ?? cls.replace(/_/g, " ");
