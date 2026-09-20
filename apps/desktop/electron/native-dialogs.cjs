"use strict";

const path = require("node:path");

/** Folder picker. Returns the selected path or null; the renderer never gets general filesystem access. */
async function selectFolder({ dialog, window }) {
  const result = await dialog.showOpenDialog(window, {
    title: "Select a Git repository",
    properties: ["openDirectory"],
  });
  if (result.canceled || result.filePaths.length === 0) return { ok: true, path: null };
  return { ok: true, path: result.filePaths[0] };
}

const MAX_EXPORT_BYTES = 32 * 1024 * 1024;

/** Reduces a suggested name to a plain `.json` file name: no directories, no reserved characters, bounded length. */
function safeJsonName(suggested) {
  const base = path
    .basename(String(suggested ?? "").replace(/\\/g, "/"))
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .replace(/^\.+/, "");
  const stem = (base.replace(/\.json$/i, "") || "export").slice(0, 100);
  return `${stem}.json`;
}

/**
 * Saves a JSON document the renderer already holds, to a location the *user* picks in a native dialog. The renderer supplies content and
 * a suggested name only; it never chooses the path, so it can't write anywhere the user didn't select. Returns `{ path: null }` on cancel.
 */
async function saveJson({ dialog, window, writeFile }, input) {
  if (typeof input !== "object" || input === null || typeof input.content !== "string") {
    return { ok: false, error: { code: "invalid_request", message: "Nothing to save." } };
  }
  if (Buffer.byteLength(input.content, "utf8") > MAX_EXPORT_BYTES) {
    return { ok: false, error: { code: "too_large", message: "That export is too large to save from here." } };
  }
  const result = await dialog.showSaveDialog(window, {
    title: "Save export",
    defaultPath: safeJsonName(input.suggestedName),
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (result.canceled || !result.filePath) return { ok: true, path: null };
  const target = /\.json$/i.test(result.filePath) ? result.filePath : `${result.filePath}.json`;
  await writeFile(target, input.content, "utf8");
  return { ok: true, path: target };
}

module.exports = { selectFolder, saveJson, safeJsonName, MAX_EXPORT_BYTES };
