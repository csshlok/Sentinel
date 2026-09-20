"use strict";

const { spawnSync } = require("node:child_process");

/** Command line and image path of a live process, or null when it does not exist. Windows only. */
function describeProcess(pid) {
  if (process.platform !== "win32" || !Number.isInteger(pid) || pid <= 0) return null;
  const script = `$p = Get-CimInstance Win32_Process -Filter "ProcessId=${pid}"; if ($p) { $p.CommandLine }`;
  const result = spawnSync("powershell", ["-NoProfile", "-NonInteractive", "-Command", script], {
    encoding: "utf8",
    windowsHide: true,
    timeout: 8_000,
  });
  const commandLine = (result.stdout ?? "").trim();
  return commandLine ? { commandLine } : null;
}

/** The backend shells out to `git`; report whether it is installed so the UI can say so instead of failing obscurely. */
function detectGit() {
  const result = spawnSync("git", ["--version"], { encoding: "utf8", windowsHide: true, timeout: 5_000 });
  const version = (result.stdout ?? "").trim().replace(/^git version\s+/i, "");
  return result.status === 0 && version ? { available: true, version } : { available: false, version: null };
}

/**
 * Terminate one process and everything it started. Needed on Windows because a Python launcher shim or a virtual
 * environment's python.exe starts the real interpreter as a child, and killing only the parent would orphan it.
 * The pid must be one this app started (or verified as its own stale backend).
 */
function killTree(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  if (process.platform === "win32") {
    const result = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, timeout: 10_000 });
    return result.status === 0;
  }
  try {
    process.kill(pid, "SIGKILL");
    return true;
  } catch {
    return false;
  }
}

module.exports = { describeProcess, detectGit, killTree };
