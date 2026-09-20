"use strict";

// Sandboxed preload: only `electron` is required. Expose a frozen, narrow API and nothing else.
const { contextBridge, ipcRenderer } = require("electron");

const WINDOW_STATE_CHANNEL = "window:state-changed";

const api = Object.freeze({
  request: (input) => ipcRenderer.invoke("api:request", input),
});

const runtime = Object.freeze({
  getStatus: () => ipcRenderer.invoke("runtime:get-status"),
  restartBackend: () => ipcRenderer.invoke("runtime:restart-backend"),
});

const repositories = Object.freeze({
  selectFolder: () => ipcRenderer.invoke("repositories:select-folder"),
});

const diagnostics = Object.freeze({
  openLogs: () => ipcRenderer.invoke("diagnostics:open-logs"),
});

const exportsApi = Object.freeze({
  saveJson: (input) => ipcRenderer.invoke("exports:save-json", input),
});

const windowControls = Object.freeze({
  getState: () => ipcRenderer.invoke("window:get-state"),
  minimize: () => ipcRenderer.invoke("window:minimize"),
  toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
  close: () => ipcRenderer.invoke("window:close"),
  /** Subscribes to the one state channel; the callback only ever receives the state object. */
  onStateChanged: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on(WINDOW_STATE_CHANNEL, listener);
    return () => ipcRenderer.removeListener(WINDOW_STATE_CHANNEL, listener);
  },
});

contextBridge.exposeInMainWorld(
  "changeAssuranceDesktop",
  Object.freeze({ api, runtime, repositories, exports: exportsApi, diagnostics, windowControls }),
);
