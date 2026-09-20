"use strict";

/** Convert any thrown value into a stable, secret-free error the renderer can show. */
function toSafeError(error, fallbackCode = "internal_error") {
  const code = typeof error?.code === "string" ? error.code : fallbackCode;
  const message =
    code === fallbackCode
      ? "The desktop shell could not complete the request."
      : String(error?.message || "The request failed.");
  return { ok: false, error: { code, message } };
}

class BridgeError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

module.exports = { toSafeError, BridgeError };
