export interface BridgeFailure {
  ok: false;
  error: { code: string; message: string };
}
export interface BridgeResponse {
  ok: true;
  status: number;
  body: unknown;
}

export type BackendState = "idle" | "starting" | "ready" | "failed" | "exited" | "stopping";

/** Safe runtime description. Never contains the token. */
export interface RuntimeStatus {
  ok: true;
  packaged: boolean;
  backend: {
    mode: "external" | "managed";
    state: BackendState;
    url: string;
    detail: string | null;
  };
  hasToken: boolean;
  git: { available: boolean; version: string | null };
}

export interface DesktopWindowState {
  maximized: boolean;
  fullScreen: boolean;
}

declare global {
  interface Window {
    changeAssuranceDesktop?: {
      api: {
        request(input: {
          method: "GET" | "POST" | "PUT" | "DELETE";
          path: string;
          body?: unknown;
          idempotencyKey?: string;
          timeoutMs?: number;
        }): Promise<BridgeResponse | BridgeFailure>;
      };
      runtime: {
        getStatus(): Promise<RuntimeStatus | BridgeFailure>;
        restartBackend(): Promise<RuntimeStatus | BridgeFailure>;
      };
      repositories: {
        selectFolder(): Promise<{ ok: true; path: string | null } | BridgeFailure>;
      };
      diagnostics: {
        /** Opens the desktop logs folder in the system file manager. Takes no path. */
        openLogs(): Promise<{ ok: true } | BridgeFailure>;
      };
      exports: {
        /** Saves JSON to a path the user chooses in a native dialog. `path` is null when they cancel. */
        saveJson(input: { suggestedName: string; content: string }): Promise<{ ok: true; path: string | null } | BridgeFailure>;
      };
      windowControls: {
        getState(): Promise<DesktopWindowState>;
        minimize(): Promise<boolean>;
        toggleMaximize(): Promise<DesktopWindowState>;
        close(): Promise<boolean>;
        onStateChanged(callback: (state: DesktopWindowState) => void): () => void;
      };
    };
  }
}
