"use strict";

/**
 * The only runtime description the renderer receives. It carries state, never secrets:
 * `hasToken` is a boolean, and the backend URL contains no credentials.
 */
function buildRuntimeStatus({ packaged, backend, token, git }) {
  return {
    ok: true,
    packaged: Boolean(packaged),
    backend: {
      mode: backend.mode,
      state: backend.state,
      url: backend.url,
      detail: backend.detail ?? null,
    },
    hasToken: Boolean(token),
    git: { available: Boolean(git?.available), version: git?.available ? String(git.version ?? "") : null },
  };
}

module.exports = { buildRuntimeStatus };
