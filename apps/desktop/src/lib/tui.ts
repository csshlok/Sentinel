export interface TuiCommands {
  /** One-time install of the terminal UI's dependency, run from the repository root. */
  install: string;
  /** Loads the API token for this shell session without printing it. */
  token: string;
  /** Starts the terminal UI against the running Sentinel service. */
  run: string;
}

const isLoopback = (url: string) => /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):\d+\/?$/.test(url);

/**
 * The commands to use Sentinel's terminal UI (`backend.app.tui.app`) with the same service the desktop app shows. The token itself is
 * never placed in a command: it is read from a file into an environment variable. A non-loopback URL is refused, so a pasted or odd
 * address can't produce a command that sends a token elsewhere.
 */
export function tuiCommands(input: { apiUrl: string; actorId?: string; tokenFile?: string }): TuiCommands | null {
  if (!isLoopback(input.apiUrl)) return null;
  const url = input.apiUrl.replace(/\/$/, "");
  const file = input.tokenFile ?? ".change-assurance\\api_token";
  const actor = input.actorId && /^[0-9a-f-]{8,}$/i.test(input.actorId) ? ` --actor-id ${input.actorId}` : "";
  return {
    install: 'python -m pip install -e ".[tui]"',
    token: `$env:CHANGE_ASSURANCE_API_TOKEN = (Get-Content "${file}" -Raw).Trim()`,
    run: `python -m backend.app.tui.app --api-url ${url}${actor}`,
  };
}
