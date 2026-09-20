"use strict";

const MAX_AUTO_RETRIES = 10;
const RETRY_SECONDS = 3;

const escapeHtml = (text) =>
  String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/**
 * A self-contained page shown when the app window can't load its renderer or the renderer process dies, so the user never sees a blank
 * window. It has no script and no remote content: the only behavior is a meta refresh back to the app, and only a fixed retry URL and a
 * short reason are interpolated (both escaped). The reason is a description string, never a path, token or log content.
 */
function buildRepairPage({ retryUrl, reason, attempt = 1 }) {
  const retrying = attempt <= MAX_AUTO_RETRIES;
  const refresh = retrying ? `<meta http-equiv="refresh" content="${RETRY_SECONDS};url=${escapeHtml(retryUrl)}">` : "";
  const message = retrying
    ? `Trying again in ${RETRY_SECONDS} seconds (attempt ${attempt} of ${MAX_AUTO_RETRIES}).`
    : "Automatic retries stopped. Close the app and open it again. If this keeps happening, check the logs folder under the app's data directory.";
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
${refresh}<title>Change Assurance</title>
<style>body{margin:0;display:grid;min-height:100vh;place-items:center;background:#fafaf8;color:#3d3c39;font:14px/1.5 "Segoe UI",system-ui,sans-serif}
main{max-width:34rem;padding:2rem}h1{font-size:1.25rem;color:#1a1916;margin:0 0 .5rem}p{margin:.4rem 0;color:#6b6a66}
@media (prefers-color-scheme:dark){body{background:#161513;color:#d6d3cc}h1{color:#f2f0eb}p{color:#a8a49c}}</style></head>
<body><main role="alert"><h1>The window couldn't load</h1><p>${escapeHtml(reason)}</p><p>${escapeHtml(message)}</p></main></body></html>`;
  return `data:text/html;charset=utf-8,${encodeURIComponent(html)}`;
}

module.exports = { buildRepairPage, MAX_AUTO_RETRIES, RETRY_SECONDS };
