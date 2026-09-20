import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Field, FormDialog, useDialogState, useFormAction } from "@/components/FormDialog";
import { StatusLabel } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { connectGithub, disconnectGithub, githubStatusQuery } from "@/services/actions";

const PROVIDER = [["providers"]] as const;

/** GitHub connection state and its two actions. Shared by Settings and Delivery. The token is sent once and never displayed or kept. */
export function GithubConnection() {
  const status = useQuery(githubStatusQuery());
  const [token, setToken] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const dlg = useDialogState(() => { setToken(""); setErr(null); connect.reset(); connect.renewKey(); });
  const connect = useFormAction({ run: (t: string) => connectGithub(t), invalidate: [...PROVIDER], onSuccess: () => { setToken(""); dlg.close(); } });
  const disconnect = useFormAction({ run: () => disconnectGithub(), invalidate: [...PROVIDER], onSuccess: () => setConfirm(false) });
  const configured = status.data?.configured;

  return (
    <div className="flex flex-wrap items-center gap-3">
      {status.isPending ? (
        <span className="text-sm text-muted-foreground" role="status">Checking…</span>
      ) : status.isError ? (
        <StatusLabel status={{ label: "Status unavailable", tone: "warn" }} />
      ) : (
        <StatusLabel status={configured ? { label: "Connected", tone: "ok" } : { label: "Not connected", tone: "neutral" }} />
      )}
      <Button size="sm" variant={configured ? "outline" : "default"} onClick={dlg.show}>{configured ? "Replace token" : "Connect GitHub"}</Button>
      {configured ? <Button size="sm" variant="ghost" className="text-danger" onClick={() => { disconnect.reset(); setConfirm(true); }}>Disconnect</Button> : null}

      <FormDialog
        open={dlg.open}
        onOpenChange={dlg.onOpenChange}
        title="Connect GitHub"
        description="Paste a personal access token. It is stored in this computer's credential store, sent once, and never shown again."
        submitLabel="Connect"
        pending={connect.isPending}
        error={connect.error}
        submit={() => (token.trim() ? (setErr(null), connect.mutate(token.trim())) : setErr("Paste a token to continue."))}
      >
        <Field id="gh-token" label="Personal access token" error={err} hint="Needs repository read and pull-request write for the repositories you use.">
          <Input id="gh-token" type="password" autoComplete="off" spellCheck={false} value={token} onChange={(e) => setToken(e.target.value)} aria-describedby="gh-token-h" />
        </Field>
      </FormDialog>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Disconnect GitHub?"
        description="The stored token is removed. Existing grants stop working, and pull-request actions are unavailable until you connect again."
        confirmLabel="Disconnect"
        pending={disconnect.isPending}
        error={disconnect.error}
        onConfirm={() => disconnect.mutate(undefined)}
      />
    </div>
  );
}
