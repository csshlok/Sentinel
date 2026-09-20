import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Section } from "@/components/product";
import { Button } from "@/components/ui/button";
import { useActors } from "@/features/authority/useActors";
import { ActorPicker } from "@/components/pickers";
import { tuiCommands } from "@/lib/tui";
import { runtimeQuery } from "@/services/system";

function CommandRow({ label, command }: { label: string; command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1.5">
      <p className="text-[13px] font-medium">{label}</p>
      <div className="flex items-start gap-2">
        <pre className="mono min-w-0 flex-1 overflow-x-auto whitespace-pre-wrap break-all rounded-md border bg-secondary px-3 py-2 text-xs" tabIndex={0} aria-label={label}>{command}</pre>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={async () => {
            try { await navigator.clipboard.writeText(command); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* selecting the text still works */ }
          }}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          <span className="sr-only">{`Copy: ${label}`}</span>
          <span aria-hidden="true">{copied ? "Copied" : "Copy"}</span>
        </Button>
      </div>
    </div>
  );
}

/** How to use Sentinel's terminal UI with the same service as this app. The API token is never shown; it is read from its file in the shell. */
export function TerminalCard() {
  const runtime = useQuery(runtimeQuery());
  const { actors } = useActors();
  const [actor, setActor] = useState("");
  const managed = runtime.data?.backend.mode === "managed";
  const apiUrl = runtime.data?.backend.url || "http://127.0.0.1:8000";
  const cmds = tuiCommands({ apiUrl, actorId: actor || undefined });
  return (
    <Section title="Terminal (TUI)" description="Prefer a terminal? Run the same workflow from the command line, against the same service and data.">
      {managed ? (
        <p className="mb-4 text-sm text-muted-foreground">
          This app is running its own private service, which keeps its token in memory, so a terminal can't sign in to it. To use the terminal, start the service yourself
          (<code>python -m uvicorn backend.app.main:app --port 8000</code>) and run the commands below against it.
        </p>
      ) : null}
      {cmds === null ? (
        <p className="text-sm text-muted-foreground">The service address isn't a local address, so no command is shown.</p>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">Run these from the repository root, in PowerShell, in order.</p>
          <CommandRow label="1. Install the terminal UI (once)" command={cmds.install} />
          <CommandRow label="2. Load the API token for this shell" command={cmds.token} />
          <div className="max-w-sm"><ActorPicker id="tui-actor" label="Act as (optional)" actors={actors} value={actor} onChange={setActor} hint="Adds --actor-id, needed for recovery and delegations." /></div>
          <CommandRow label="3. Start the terminal UI" command={cmds.run} />
        </div>
      )}
    </Section>
  );
}
