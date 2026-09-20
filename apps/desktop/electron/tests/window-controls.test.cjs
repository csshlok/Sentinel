"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const {
  WINDOW_STATE_CHANNEL,
  attachWindowStateEvents,
  registerWindowControlHandlers,
  windowState,
} = require("../window-controls.cjs");

function fakeWindow(overrides = {}) {
  const win = new EventEmitter();
  Object.assign(
    win,
    {
      state: { maximized: false, fullScreen: false },
      calls: [],
      destroyed: false,
      isDestroyed() {
        return this.destroyed;
      },
      isMaximized() {
        return this.state.maximized;
      },
      isFullScreen() {
        return this.state.fullScreen;
      },
      minimize() {
        this.calls.push("minimize");
      },
      maximize() {
        this.calls.push("maximize");
        this.state.maximized = true;
      },
      unmaximize() {
        this.calls.push("unmaximize");
        this.state.maximized = false;
      },
      setFullScreen(value) {
        this.calls.push(`fullscreen:${value}`);
        this.state.fullScreen = value;
      },
      close() {
        this.calls.push("close");
      },
      webContents: {
        sent: [],
        isDestroyed: () => false,
        send(channel, payload) {
          this.sent.push([channel, payload]);
        },
      },
    },
    overrides,
  );
  return win;
}

function setup(windows) {
  const handlers = new Map();
  const ipcMain = { handle: (channel, handler) => handlers.set(channel, handler) };
  const BrowserWindow = { fromWebContents: (sender) => windows.get(sender) ?? null };
  // The real app wraps handlers with a sender-trust guard; here it is a pass-through.
  registerWindowControlHandlers({ ipcMain, BrowserWindow, guard: (handler) => handler });
  return handlers;
}

test("registers exactly the four window channels", () => {
  const handlers = setup(new Map());
  assert.deepEqual([...handlers.keys()].sort(), [
    "window:close",
    "window:get-state",
    "window:minimize",
    "window:toggle-maximize",
  ]);
});

test("each control acts only on the window that sent the request", async () => {
  const a = fakeWindow();
  const b = fakeWindow();
  const handlers = setup(new Map([["sender-a", a], ["sender-b", b]]));
  await handlers.get("window:minimize")({ sender: "sender-a" });
  await handlers.get("window:close")({ sender: "sender-b" });
  assert.deepEqual(a.calls, ["minimize"]);
  assert.deepEqual(b.calls, ["close"]);
});

test("toggle maximizes, restores, and leaves full screen first", async () => {
  const win = fakeWindow();
  const handlers = setup(new Map([["s", win]]));
  const toggle = handlers.get("window:toggle-maximize");
  assert.deepEqual(await toggle({ sender: "s" }), { maximized: true, fullScreen: false });
  assert.deepEqual(await toggle({ sender: "s" }), { maximized: false, fullScreen: false });
  win.state.fullScreen = true;
  await toggle({ sender: "s" });
  assert.deepEqual(win.calls.slice(-1), ["fullscreen:false"]);
});

test("missing, unknown, or destroyed senders are safe no-ops", async () => {
  const dead = fakeWindow({ destroyed: true });
  const handlers = setup(new Map([["dead", dead]]));
  assert.equal(await handlers.get("window:minimize")({ sender: "nobody" }), false);
  assert.equal(await handlers.get("window:close")({ sender: "dead" }), false);
  assert.equal(await handlers.get("window:minimize")({}), false);
  assert.deepEqual(await handlers.get("window:toggle-maximize")({ sender: "nobody" }), {
    maximized: false,
    fullScreen: false,
  });
  assert.deepEqual(dead.calls, []);
});

test("state changes are pushed on the fixed channel and skipped for destroyed windows", () => {
  const win = fakeWindow();
  attachWindowStateEvents(win);
  win.state.maximized = true;
  win.emit("maximize");
  assert.deepEqual(win.webContents.sent, [[WINDOW_STATE_CHANNEL, { maximized: true, fullScreen: false }]]);
  win.destroyed = true;
  win.emit("unmaximize");
  assert.equal(win.webContents.sent.length, 1);
  assert.deepEqual(windowState(null), { maximized: false, fullScreen: false });
});
