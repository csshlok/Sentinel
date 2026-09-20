"use strict";

const WINDOW_STATE_CHANNEL = "window:state-changed";

function windowState(window) {
  const usable = Boolean(window && !window.isDestroyed());
  return {
    maximized: usable && window.isMaximized(),
    fullScreen: usable && window.isFullScreen(),
  };
}

/** Controls always act on the window that sent the request, never on "the" main window. */
function resolveSenderWindow(BrowserWindow, event) {
  const sender = event?.sender;
  if (!sender) return null;
  const window = BrowserWindow.fromWebContents(sender);
  return window && !window.isDestroyed() ? window : null;
}

function sendWindowState(window) {
  if (!window || window.isDestroyed() || window.webContents.isDestroyed()) return;
  window.webContents.send(WINDOW_STATE_CHANNEL, windowState(window));
}

function attachWindowStateEvents(window) {
  const notify = () => sendWindowState(window);
  for (const name of ["maximize", "unmaximize", "enter-full-screen", "leave-full-screen"]) window.on(name, notify);
}

/** `guard` wraps a handler with the caller's sender-trust check and safe error mapping. */
function registerWindowControlHandlers({ ipcMain, BrowserWindow, guard }) {
  const on = (channel, handler) => ipcMain.handle(channel, guard(handler));

  on("window:get-state", (event) => windowState(resolveSenderWindow(BrowserWindow, event)));
  on("window:minimize", (event) => {
    const window = resolveSenderWindow(BrowserWindow, event);
    if (!window) return false;
    window.minimize();
    return true;
  });
  on("window:toggle-maximize", (event) => {
    const window = resolveSenderWindow(BrowserWindow, event);
    if (!window) return windowState(null);
    if (window.isFullScreen()) window.setFullScreen(false);
    else if (window.isMaximized()) window.unmaximize();
    else window.maximize();
    return windowState(window);
  });
  on("window:close", (event) => {
    const window = resolveSenderWindow(BrowserWindow, event);
    if (!window) return false;
    window.close();
    return true;
  });
}

module.exports = {
  WINDOW_STATE_CHANNEL,
  attachWindowStateEvents,
  registerWindowControlHandlers,
  resolveSenderWindow,
  sendWindowState,
  windowState,
};
