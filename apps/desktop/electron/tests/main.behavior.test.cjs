"use strict";

// Loads the real electron/main.cjs against an Electron stub (the approach CML uses for its main process) and
// checks the behaviour that matters for security and lifecycle: window options, navigation rules, IPC guards,
// token handling, and shutdown ordering.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const os = require("node:os");
const path = require("node:path");

const MAIN = path.join(__dirname, "..", "main.cjs");
const TOKEN = "env-token-for-tests-1234567890";
const cleanups = [];
test.after(() => cleanups.forEach((fn) => fn()));

/** Load main.cjs fresh. Returns everything the stubbed Electron saw. */
function loadMain({ argv = [], env = {}, singleInstance = true, packaged = false } = {}) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "ca-main-"));
  cleanups.push(() => fs.rmSync(userData, { recursive: true, force: true }));

  const calls = { schemes: [], handles: {}, ipc: {}, windows: [], quit: 0, openExternal: [], appOn: {}, protocolHandle: [], dialog: [] };
  let readyCallback = null;
  const order = [];

  class FakeWebContents {
    constructor() {
      this.handlers = {};
      this.windowOpenHandler = null;
      this.loaded = [];
    }
    on(name, handler) {
      this.handlers[name] = handler;
    }
    setWindowOpenHandler(fn) {
      this.windowOpenHandler = fn;
    }
    send() {}
    isDestroyed() {
      return false;
    }
  }
  class FakeBrowserWindow {
    constructor(options) {
      this.options = options;
      this.webContents = new FakeWebContents();
      this.handlers = {};
      this.title = "";
      calls.windows.push(this);
    }
    static getAllWindows() {
      return calls.windows;
    }
    static fromWebContents() {
      return calls.windows[0] ?? null;
    }
    on(name, handler) {
      this.handlers[name] = handler;
    }
    once(name, handler) {
      this.handlers[name] = handler;
    }
    loadURL(url) {
      this.loaded.push(url);
    }
    setMenuBarVisibility() {}
    setTitle(title) {
      this.title = title;
    }
    show() {}
    isDestroyed() {
      return false;
    }
  }
  FakeBrowserWindow.prototype.loaded = undefined;
  Object.defineProperty(FakeBrowserWindow.prototype, "loaded", { get() { return (this._loaded ??= []); }, set(v) { this._loaded = v; } });

  const electron = {
    app: {
      isPackaged: packaged,
      setPath() {},
      getPath: () => userData,
      requestSingleInstanceLock: () => singleInstance,
      on: (name, handler) => {
        calls.appOn[name] = handler;
      },
      whenReady: () => ({ then: (cb) => { readyCallback = cb; } }),
      quit: () => {
        calls.quit += 1;
      },
    },
    BrowserWindow: FakeBrowserWindow,
    dialog: { showOpenDialog: async (...a) => (calls.dialog.push(a), { canceled: true, filePaths: [] }) },
    ipcMain: { handle: (channel, handler) => (calls.ipc[channel] = handler) },
    protocol: {
      registerSchemesAsPrivileged: (schemes) => {
        order.push("registerSchemes");
        calls.schemes.push(...schemes);
      },
      handle: (scheme, handler) => {
        order.push("protocol.handle");
        calls.protocolHandle.push([scheme, handler]);
      },
    },
    shell: { openExternal: (url) => calls.openExternal.push(url) },
    session: {
      defaultSession: {
        setPermissionRequestHandler: (handler) => (calls.permissionRequest = handler),
        setPermissionCheckHandler: (handler) => (calls.permissionCheck = handler),
      },
    },
  };

  const originalLoad = Module._load;
  Module._load = function (request, ...rest) {
    return request === "electron" ? electron : originalLoad.call(this, request, ...rest);
  };
  const originalArgv = process.argv;
  const originalEnv = {};
  for (const [key, value] of Object.entries(env)) {
    originalEnv[key] = process.env[key];
    process.env[key] = value;
  }
  const originalFetch = global.fetch;
  const fetches = [];
  let fetchOverride = null;
  global.fetch = async (url, init) => {
    fetches.push({ url: String(url), init });
    if (fetchOverride) return fetchOverride(url, init);
    return { ok: true, status: 200, text: async () => JSON.stringify({ status: "ok" }) };
  };
  const before = {
    uncaught: process.listeners("uncaughtException"),
    unhandled: process.listeners("unhandledRejection"),
    exit: process.listeners("exit"),
  };
  process.argv = [process.argv[0], "electron/main.cjs", ...argv];
  delete require.cache[require.resolve(MAIN)];
  try {
    require(MAIN);
  } finally {
    Module._load = originalLoad;
  }
  const restore = () => {
    process.argv = originalArgv;
    global.fetch = originalFetch;
    for (const [key, value] of Object.entries(originalEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    for (const [event, list] of [["uncaughtException", before.uncaught], ["unhandledRejection", before.unhandled], ["exit", before.exit]]) {
      for (const listener of process.listeners(event)) if (!list.includes(listener)) process.removeListener(event, listener);
    }
  };

  return {
    calls,
    order,
    fetches,
    userData,
    restore,
    setFetch: (fn) => (fetchOverride = fn),
    ready: async () => {
      await readyCallback?.();
      await new Promise((r) => setImmediate(r));
    },
    window: () => calls.windows[0],
  };
}

const trusted = (url = "app://app/changes") => ({ sender: {}, senderFrame: { url } });

async function withMain(options, fn) {
  const ctx = loadMain(options);
  try {
    await fn(ctx);
  } finally {
    ctx.restore();
  }
}

test("registers the app:// scheme as privileged before the app is ready", async () => {
  await withMain({}, async (ctx) => {
    assert.deepEqual(ctx.calls.schemes, [{ scheme: "app", privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
    assert.deepEqual(ctx.order, ["registerSchemes"]);
    await ctx.ready();
    assert.deepEqual(ctx.order, ["registerSchemes", "protocol.handle"]);
  });
});

test("creates a frameless, sandboxed window with the expected security options", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const { options } = ctx.window();
    assert.equal(options.frame, false);
    assert.equal(options.autoHideMenuBar, true);
    assert.equal(options.show, false);
    assert.equal(options.title, "Sentinel");
    assert.ok(options.minWidth >= 1024 && options.minHeight >= 680);
    assert.deepEqual(
      { ci: options.webPreferences.contextIsolation, ni: options.webPreferences.nodeIntegration, sb: options.webPreferences.sandbox, ws: options.webPreferences.webSecurity },
      { ci: true, ni: false, sb: true, ws: true },
    );
    assert.equal(path.basename(options.webPreferences.preload), "preload.cjs");
    for (const forbidden of ["nodeIntegrationInWorker", "nodeIntegrationInSubFrames", "enableRemoteModule", "webviewTag", "allowRunningInsecureContent"]) {
      assert.ok(!options.webPreferences[forbidden], forbidden);
    }
  });
});

test("production loads app://app/, development loads the Vite URL", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    assert.deepEqual(ctx.window()._loaded, ["app://app/"]);
  });
  await withMain({ argv: ["--dev"] }, async (ctx) => {
    await ctx.ready();
    assert.deepEqual(ctx.window()._loaded, ["http://localhost:5173"]);
    assert.equal(ctx.calls.protocolHandle.length, 0, "no protocol handler in dev");
  });
});

test("pop-ups are always denied and only https links reach the system browser", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const open = ctx.window().webContents.windowOpenHandler;
    for (const url of ["https://example.com/docs", "http://example.com", "file:///C:/Windows/win.ini", "javascript:alert(1)", "app://app/x", "data:text/html,<script>1</script>", "ms-msdt:/id"]) {
      assert.deepEqual(open({ url }), { action: "deny" }, url);
    }
    assert.deepEqual(ctx.calls.openExternal, ["https://example.com/docs"]);
  });
});

test("navigation away from the app origin is blocked", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const navigate = ctx.window().webContents.handlers["will-navigate"];
    const attempt = (url) => {
      let prevented = false;
      navigate({ preventDefault: () => (prevented = true) }, url);
      return prevented;
    };
    assert.equal(attempt("app://app/settings"), false);
    for (const url of ["https://evil.example/", "http://localhost:5173/", "file:///C:/x.html", "app://other/x", "javascript:1"]) {
      assert.equal(attempt(url), true, url);
    }
  });
});

test("the window title cannot be changed by page content", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const win = ctx.window();
    let prevented = false;
    win.handlers["page-title-updated"]({ preventDefault: () => (prevented = true) });
    assert.equal(prevented, true);
    assert.equal(win.title, "Sentinel");
  });
});

test("registers exactly the expected IPC channels", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    assert.deepEqual(Object.keys(ctx.calls.ipc).sort(), [
      "api:request",
      "diagnostics:open-logs",
      "exports:save-json",
      "repositories:select-folder",
      "runtime:get-status",
      "runtime:restart-backend",
      "window:close",
      "window:get-state",
      "window:minimize",
      "window:toggle-maximize",
    ]);
  });
});

test("every IPC handler rejects an untrusted sender without doing any work", async () => {
  await withMain({ env: { CHANGE_ASSURANCE_API_TOKEN: TOKEN } }, async (ctx) => {
    await ctx.ready();
    const fetchesBefore = ctx.fetches.length;
    const hostile = [undefined, "", "https://evil.example/", "file:///C:/x.html", "app://app.evil.example/", "http://localhost:5173/", "app://appx/"];
    for (const [channel, handler] of Object.entries(ctx.calls.ipc)) {
      for (const url of hostile) {
        const result = await handler({ sender: {}, senderFrame: url === undefined ? undefined : { url } }, { method: "GET", path: "/api/v1/health" });
        assert.equal(result.ok, false, `${channel} ${url}`);
        assert.equal(result.error.code, "untrusted_sender", `${channel} ${url}`);
      }
    }
    assert.equal(ctx.fetches.length, fetchesBefore, "no request may leave the process for an untrusted sender");
    assert.equal(ctx.calls.dialog.length, 0);
  });
});

test("the token is injected only in main and never returned to the page", async () => {
  await withMain({ env: { CHANGE_ASSURANCE_API_TOKEN: TOKEN } }, async (ctx) => {
    await ctx.ready();
    ctx.fetches.length = 0;
    const result = await ctx.calls.ipc["api:request"](trusted(), { method: "GET", path: "/api/v1/capabilities" });
    assert.equal(result.ok, true);
    const call = ctx.fetches.at(-1);
    assert.equal(call.url, "http://127.0.0.1:8000/api/v1/capabilities");
    assert.equal(call.init.headers.Authorization, `Bearer ${TOKEN}`);
    assert.ok(!JSON.stringify(result).includes(TOKEN));
    const status = await ctx.calls.ipc["runtime:get-status"](trusted());
    assert.equal(status.hasToken, true);
    assert.ok(!JSON.stringify(status).includes(TOKEN));
  });
});

test("the proxy rejects non-API paths and unsupported methods through IPC", async () => {
  await withMain({ env: { CHANGE_ASSURANCE_API_TOKEN: TOKEN } }, async (ctx) => {
    await ctx.ready();
    ctx.fetches.length = 0;
    assert.equal((await ctx.calls.ipc["api:request"](trusted(), { method: "GET", path: "/etc/passwd" })).error.code, "forbidden_path");
    assert.equal((await ctx.calls.ipc["api:request"](trusted(), { method: "PATCH", path: "/api/v1/health" })).error.code, "forbidden_method");
    assert.equal((await ctx.calls.ipc["api:request"](trusted(), undefined)).ok, false);
    assert.equal(ctx.fetches.length, 0);
  });
});

test("IPC errors are safe: a throwing handler never leaks its message", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    ctx.setFetch(async () => {
      throw new Error("ECONNREFUSED C:\\secret\\path token=abc");
    });
    const result = await ctx.calls.ipc["api:request"](trusted(), { method: "GET", path: "/api/v1/health" });
    assert.equal(result.ok, false);
    assert.equal(result.error.code, "backend_unreachable");
    assert.ok(!JSON.stringify(result).includes("secret"));
  });
});

test("the folder picker returns only a path or null", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const result = await ctx.calls.ipc["repositories:select-folder"](trusted());
    assert.deepEqual(result, { ok: true, path: null });
    assert.equal(ctx.calls.dialog.length, 1);
    assert.deepEqual(ctx.calls.dialog[0][1].properties, ["openDirectory"]);
  });
});

test("quit waits for the backend to stop exactly once, then quits", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    let prevented = 0;
    const event = { preventDefault: () => (prevented += 1) };
    ctx.calls.appOn["before-quit"](event);
    assert.equal(prevented, 1, "first quit request is deferred");
    await new Promise((r) => setImmediate(r));
    assert.equal(ctx.calls.quit, 1, "app.quit is called after the backend stopped");
    ctx.calls.appOn["before-quit"](event);
    assert.equal(prevented, 1, "the follow-up quit is not deferred again");
  });
});

test("a second instance quits immediately and creates no window", async () => {
  await withMain({ singleInstance: false }, async (ctx) => {
    assert.equal(ctx.calls.quit, 1);
    assert.equal(ctx.calls.windows.length, 0);
    assert.equal(ctx.calls.appOn["before-quit"], undefined);
  });
});

test("a second-instance signal focuses and restores the existing window", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const win = ctx.window();
    const seen = [];
    win.isMinimized = () => true;
    win.restore = () => seen.push("restore");
    win.focus = () => seen.push("focus");
    ctx.calls.appOn["second-instance"]();
    assert.deepEqual(seen, ["restore", "focus"]);
  });
});

test("closing the last window quits the app", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    ctx.calls.appOn["window-all-closed"]();
    assert.equal(ctx.calls.quit, 1);
  });
});

test("a desktop log records lifecycle events and never the token", async () => {
  await withMain({ env: { CHANGE_ASSURANCE_API_TOKEN: TOKEN } }, async (ctx) => {
    await ctx.ready();
    await ctx.calls.ipc["api:request"](trusted(), { method: "GET", path: "/api/v1/health" });
    ctx.calls.appOn["window-all-closed"]();
    const log = fs.readFileSync(path.join(ctx.userData, "logs", "desktop.log"), "utf8");
    assert.match(log, /app ready/);
    assert.match(log, /window-all-closed/);
    assert.ok(!log.includes(TOKEN));
  });
});

test("development uses an external backend and never spawns a process", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const status = await ctx.calls.ipc["runtime:get-status"](trusted());
    assert.equal(status.backend.mode, "external");
    assert.equal(status.packaged, false);
    assert.equal(status.backend.url, "http://127.0.0.1:8000");
  });
});

test("every web permission request and check is denied", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    assert.equal(typeof ctx.calls.permissionRequest, "function");
    for (const permission of ["media", "geolocation", "notifications", "clipboard-read", "midi", "openExternal", "fullscreen"]) {
      let granted = "unset";
      ctx.calls.permissionRequest({}, permission, (allowed) => (granted = allowed));
      assert.equal(granted, false, permission);
      assert.equal(ctx.calls.permissionCheck({}, permission), false, permission);
    }
  });
});

test("a renderer that fails to load or crashes shows the repair page, with bounded retries", async () => {
  await withMain({}, async (ctx) => {
    await ctx.ready();
    const win = ctx.calls.windows[0];
    const wc = win.webContents;
    const before = win.loaded.length;
    wc.handlers["did-fail-load"]({}, -105, "NAME_NOT_RESOLVED", "app://app/", true);
    assert.equal(win.loaded.length, before + 1);
    assert.match(win.loaded.at(-1), /^data:text\/html/);
    // A cancelled navigation, a subframe failure and the repair page's own URL never trigger another repair.
    wc.handlers["did-fail-load"]({}, -3, "ABORTED", "app://app/", true);
    wc.handlers["did-fail-load"]({}, -105, "x", "app://app/x", false);
    wc.handlers["did-fail-load"]({}, -105, "x", "data:text/html,abc", true);
    assert.equal(win.loaded.length, before + 1);
    wc.handlers["render-process-gone"]({}, { reason: "crashed", exitCode: 1 });
    assert.equal(win.loaded.length, before + 2);
    wc.handlers["render-process-gone"]({}, { reason: "clean-exit", exitCode: 0 });
    assert.equal(win.loaded.length, before + 2);
  });
});
