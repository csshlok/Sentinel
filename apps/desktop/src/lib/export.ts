/** A predictable, filesystem-safe file name like `passport-1a2b3c4d.json`. */
export function exportFileName(kind: string, id: string): string {
  const clean = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${clean(kind) || "export"}-${clean(id).slice(0, 8) || "data"}.json`;
}

export type SaveResult = { kind: "saved"; where: string } | { kind: "downloaded" } | { kind: "cancelled" };

/**
 * Saves the server's JSON exactly as received (re-indented, key order kept). In the desktop app the user picks the location in a native
 * dialog; in a plain browser it becomes a download. The renderer never names a filesystem path itself.
 */
export async function saveJsonExport(suggestedName: string, data: unknown): Promise<SaveResult> {
  const content = JSON.stringify(data, null, 2);
  const bridge = window.changeAssuranceDesktop;
  if (bridge?.exports) {
    const result = await bridge.exports.saveJson({ suggestedName, content });
    if (!result.ok) throw new Error(result.error.message);
    return result.path ? { kind: "saved", where: result.path } : { kind: "cancelled" };
  }
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  Object.assign(document.createElement("a"), { href: url, download: suggestedName }).click();
  URL.revokeObjectURL(url);
  return { kind: "downloaded" };
}
