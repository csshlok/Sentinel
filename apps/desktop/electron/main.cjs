"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, dialog, ipcMain, protocol, session, shell } = require("electron");
const { createApiProxy } = require("./api-proxy.cjs");
const { HOST, SCHEME, createProtocolHandler } = require("./app-protocol.cjs");
const { createBackendRuntime } = require("./backend-runtime.cjs");
const { toSafeError, BridgeError } = require("./ipc-errors.cjs");
const { createLogger } = require("./logging.cjs");
const { describeProcess, detectGit, killTree } = require("./process-tools.cjs");
const { createDescriptorStore } = require("./runtime-descriptor.cjs");
const { selectFolder, saveJson } = require("./native-dialogs.cjs");
const { buildRepairPage } = require("./repair-page.cjs");
const { buildRuntimeStatus } = require("./runtime-status.cjs");
const { attachWindowStateEvents, registerWindowControlHandlers } = require("./window-controls.cjs");

const APP_TITLE = "Change Assurance";

// An isolated profile for tests and smoke runs. Must be set before the app is ready.
if (process.env.CHANGE_ASSURANCE_USER_DATA_DIR) {
  app.setPath("userData", path.resolve(process.env.CHANGE_ASSURANCE_USER_DATA_DIR));
}

// Registered before `ready`, as required for a custom scheme with fetch/storage support.
protocol.registerSchemesAsPrivileged([
  { scheme: SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

const DEV_RENDERER_URL =
  process.env.ELECTRON_RENDERER_URL || (process.argv.includes("--dev") ? "http://localhost:5173" : "");
const APP_ORIGIN = `${SCHEME}://${HOST}/`;
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

// Desktop log: lifecycle events and the reason for any exit. Never contains the API token.
const desktopLog = createLogger({ dir: path.join(app.getPath("userData"), "logs") });
const log = desktopLog.log;
process.on("uncaughtException", (error) => log(`uncaughtException ${error?.stack ?? error}`));
process.on("unhandledRejection", (error) => log(`unhandledRejection ${error instanceof Error ? error.stack : String(error)}`));
process.on("exit", (code) => log(`process exit code=${code}`));
log(`start argv=${process.argv.slice(1).filter((a) => !a.startsWith("--remote-debugging")).join(" ")} packaged=${app.isPackaged}`);

/** Development-only: read the backend's own token file when it was started separately. */
function readExternalToken() {
  if (process.env.CHANGE_ASSURANCE_API_TOKEN) return process.env.CHANGE_ASSURANCE_API_TOKEN;
  const dbPath =
    process.env.CHANGE_ASSURANCE_DB_PATH ||
    path.join(REPO_ROOT, ".change-assurance", "change_assurance.sqlite3");
  try {
    return fs.readFileSync(path.join(path.dirname(dbPath), "api_token"), "utf8").trim();
  } catch {
    return "";
  }
}

/** Packaged builds ship `resources/backend`; development uses the repository itself. */
function backendLayout() {
  if (app.isPackaged) {
    const root = path.join(process.resourcesPath, "backend");
    const python = path.join(root, "python", "python.exe");
    const source = path.join(root, "src");
    if (fs.existsSync(python) && fs.existsSync(path.join(source, "backend", "app", "main.py"))) {
      return { command: python, cwd: source };
    }
    return null;
  }
  if (!fs.existsSync(path.join(REPO_ROOT, "backend", "app", "main.py"))) return null;
  return { command: process.env.CHANGE_ASSURANCE_PYTHON || "python", cwd: REPO_ROOT };
}

/**
 * Development: external by default so a manually started Uvicorn is never disturbed; `--manage-backend` opts in.
 * Packaged: managed when a bundled backend exists, otherwise external (and Settings says so).
 */
function shouldManageBackend() {
  if (process.argv.includes("--manage-backend") || process.env.CHANGE_ASSURANCE_MANAGE_BACKEND === "1") return true;
  return app.isPackaged && backendLayout() !== null;
}

function createRuntime() {
  if (!shouldManageBackend()) {
    return createBackendRuntime({
      mode: "external",
      externalUrl: process.env.CHANGE_ASSURANCE_API_URL || "http://127.0.0.1:8000",
      readExternalToken,
    });
  }
  const dataDir = path.join(app.getPath("userData"), "state");
  fs.mkdirSync(dataDir, { recursive: true });
  const backendLog = createLogger({ dir: path.join(app.getPath("userData"), "logs"), name: "backend.log" });
  const layout = backendLayout();
  return createBackendRuntime({
    mode: "managed",
    command: layout?.command,
    args: ["-s", "-m", "uvicorn", "backend.app.main:app"],
    cwd: layout?.cwd,
    dataDir,
    log: (text) => backendLog.log(text),
    descriptor: createDescriptorStore(path.join(dataDir, "backend-runtime.json")),
    describeProcess,
    killTree,
  });
}

const runtime = createRuntime();
const apiProxy = createApiProxy({ getBaseUrl: runtime.getBaseUrl, getToken: runtime.getToken });

function isTrustedSender(event) {
  const url = event.senderFrame?.url ?? "";
  return DEV_RENDERER_URL ? url.startsWith(DEV_RENDERER_URL) : url.startsWith(APP_ORIGIN);
}

/** Every handler checks the sender and maps any failure to a safe, stable error. */
function guarded(handler) {
  return async (event, ...args) => {
    try {
      if (!isTrustedSender(event)) throw new BridgeError("untrusted_sender", "Request came from an untrusted page.");
      return await handler(event, ...args);
    } catch (error) {
      return toSafeError(error);
    }
  };
}

// Detected once at startup: the backend shells out to git, so the UI can explain a missing install.
const gitInfo = detectGit();
log(`git available=${gitInfo.available}`);

function runtimeStatus() {
  return buildRuntimeStatus({ packaged: app.isPackaged, backend: runtime.getStatus(), token: runtime.getToken(), git: gitInfo });
}

function registerIpc() {
  ipcMain.handle("api:request", guarded((_event, input) => apiProxy(input)));
  ipcMain.handle("runtime:get-status", guarded(() => runtimeStatus()));
  ipcMain.handle(
    "runtime:restart-backend",
    guarded(async () => {
      log("backend restart requested");
      await runtime.restart();
      return runtimeStatus();
    }),
  );
  ipcMain.handle(
    "repositories:select-folder",
    guarded((event) => selectFolder({ dialog, window: BrowserWindow.fromWebContents(event.sender) })),
  );
  ipcMain.handle(
    "diagnostics:open-logs",
    guarded(async () => {
      const dir = path.join(app.getPath("userData"), "logs");
      const failure = await shell.openPath(dir); // resolves to "" on success, or an error message
      return failure ? { ok: false, error: { code: "open_failed", message: "The logs folder couldn't be opened." } } : { ok: true };
    }),
  );
  ipcMain.handle(
    "exports:save-json",
    guarded((event, input) =>
      saveJson({ dialog, window: BrowserWindow.fromWebContents(event.sender), writeFile: require("node:fs/promises").writeFile }, input),
    ),
  );
  registerWindowControlHandlers({ ipcMain, BrowserWindow, guard: guarded });
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    title: APP_TITLE,
    backgroundColor: "#fafaf8",
    autoHideMenuBar: true,
    // Frameless: the renderer draws an auto-hiding drag bar with window controls.
    frame: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  attachWindowStateEvents(window);
  window.setMenuBarVisibility(false);

  const allowed = (url) => (DEV_RENDERER_URL ? url.startsWith(DEV_RENDERER_URL) : url.startsWith(APP_ORIGIN));
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (!allowed(url)) event.preventDefault();
  });
  window.on("page-title-updated", (event) => {
    event.preventDefault();
    window.setTitle(APP_TITLE);
  });
  window.once("ready-to-show", () => window.show());

  // If the renderer can't load or its process dies, show a repair page that retries, instead of leaving a blank window.
  const rendererUrl = DEV_RENDERER_URL || APP_ORIGIN;
  let repairAttempt = 0;
  const showRepair = (reason) => {
    repairAttempt += 1;
    if (!window.isDestroyed()) window.loadURL(buildRepairPage({ retryUrl: rendererUrl, reason, attempt: repairAttempt }));
  };
  window.webContents.on("did-fail-load", (_e, code, description, url, isMainFrame) => {
    log(`renderer did-fail-load code=${code} ${description} ${url}`);
    // -3 is a cancelled navigation (for example a redirect); the repair page itself is a data: URL.
    if (isMainFrame && code !== -3 && !String(url).startsWith("data:")) showRepair("The app's interface didn't load.");
  });
  window.webContents.on("render-process-gone", (_e, details) => {
    log(`renderer gone reason=${details.reason} exitCode=${details.exitCode}`);
    if (details.reason !== "clean-exit") showRepair("The app's interface stopped unexpectedly.");
  });
  window.webContents.on("did-finish-load", () => {
    if (!window.webContents.getURL().startsWith("data:")) repairAttempt = 0;
  });
  window.on("closed", () => log("window closed"));

  window.loadURL(DEV_RENDERER_URL || APP_ORIGIN);
  return window;
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  log("second instance detected: quitting (single-instance lock held by another process)");
  app.quit();
} else {
  app.on("second-instance", () => {
    log("second-instance event: focusing existing window");
    const [existing] = BrowserWindow.getAllWindows();
    if (existing) {
      if (existing.isMinimized()) existing.restore();
      existing.focus();
    }
  });
  app.on("child-process-gone", (_e, details) => log(`child process gone type=${details.type} reason=${details.reason}`));

  let stopping = false;
  app.on("before-quit", (event) => {
    log(`before-quit stopping=${stopping}`);
    if (stopping) return;
    stopping = true;
    event.preventDefault();
    runtime.stop().finally(() => app.quit());
  });

  app.whenReady().then(() => {
    log("app ready");
    if (!DEV_RENDERER_URL) {
      protocol.handle(SCHEME, createProtocolHandler({ rootDir: path.join(__dirname, "..", "dist") }));
    }
    // No web permission is ever granted: the renderer needs none, and a compromised page must not be able to ask.
    session?.defaultSession?.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    session?.defaultSession?.setPermissionCheckHandler(() => false);
    registerIpc();
    void runtime.start();
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
  app.on("window-all-closed", () => {
    log("window-all-closed: quitting");
    app.quit();
  });
}
